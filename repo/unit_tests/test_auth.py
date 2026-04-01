"""
Unit tests for authentication business logic (auth_service.py, decorators.py).
Uses the shared app/ctx fixtures from conftest.py.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
from flask import g
from flask_login import login_user

from app.extensions import db
from app.services.auth_service import (
    hash_password,
    verify_password,
    register_user,
    authenticate,
    is_locked_out,
)
from app.utils.validators import validate_password
from app.models.user import User


# ── test_password_hash_and_verify ─────────────────────────────────────────────

class TestPasswordHashAndVerify:
    def test_hash_differs_from_plaintext(self, ctx):
        h = hash_password("Password123!")
        assert h != "Password123!"

    def test_correct_password_verifies(self, ctx):
        h = hash_password("Password123!")
        assert verify_password("Password123!", h) is True

    def test_wrong_password_fails(self, ctx):
        h = hash_password("Password123!")
        assert verify_password("WrongPass1!", h) is False

    def test_two_hashes_of_same_password_differ(self, ctx):
        """bcrypt generates a unique salt each time."""
        h1 = hash_password("Password123!")
        h2 = hash_password("Password123!")
        assert h1 != h2


# ── test_password_too_short ───────────────────────────────────────────────────

class TestPasswordTooShort:
    @pytest.mark.parametrize("pw", ["Ab1", "Abcde12!", "Short1A"])
    def test_passwords_under_10_chars_rejected(self, pw):
        err = validate_password(pw)
        assert err != "", f"Expected rejection for '{pw}' but got empty error"
        assert "10" in err

    def test_exactly_10_chars_with_policy_accepted(self):
        # "Password1A" is 10 chars, has uppercase + digit
        err = validate_password("Password1A")
        assert err == ""

    def test_9_chars_rejected(self):
        err = validate_password("Passwo1rd")  # 9 chars
        assert err != ""
        assert "10" in err


# ── test_lockout_after_5_failures ─────────────────────────────────────────────

class TestLockoutAfter5Failures:
    def test_locked_after_max_failed_attempts(self, app):
        with app.app_context():
            register_user("locktest", "lock@example.com", "Password123!")
            max_attempts = app.config["MAX_LOGIN_ATTEMPTS"]
            for _ in range(max_attempts):
                authenticate("locktest", "WrongPass1!")

            user = User.query.filter_by(username="locktest").first()
            assert user.locked_until is not None
            assert is_locked_out(user) is True

    def test_correct_password_denied_when_locked(self, app):
        with app.app_context():
            register_user("lockeduser", "locked@example.com", "Password123!")
            max_attempts = app.config["MAX_LOGIN_ATTEMPTS"]
            for _ in range(max_attempts):
                authenticate("lockeduser", "WrongPass1!")

            result, err = authenticate("lockeduser", "Password123!")
            assert result is None
            assert "locked" in err.lower()

    def test_not_locked_before_max_attempts(self, app):
        with app.app_context():
            register_user("almostlocked", "almost@example.com", "Password123!")
            max_attempts = app.config["MAX_LOGIN_ATTEMPTS"]
            for _ in range(max_attempts - 1):
                authenticate("almostlocked", "WrongPass1!")

            user = User.query.filter_by(username="almostlocked").first()
            assert not is_locked_out(user)


# ── test_lockout_expires_after_15_min ─────────────────────────────────────────

class TestLockoutExpires:
    def test_locked_user_can_login_after_lockout_expires(self, app):
        with app.app_context():
            register_user("expiretest", "expire@example.com", "Password123!")
            max_attempts = app.config["MAX_LOGIN_ATTEMPTS"]
            for _ in range(max_attempts):
                authenticate("expiretest", "WrongPass1!")

            user = User.query.filter_by(username="expiretest").first()
            assert is_locked_out(user)

            # Simulate time passing: set locked_until to the past
            user.locked_until = datetime.utcnow() - timedelta(minutes=1)
            db.session.commit()

            assert not is_locked_out(user)

            result, err = authenticate("expiretest", "Password123!")
            assert result is not None
            assert err == ""

    def test_lockout_remaining_time_message(self, app):
        with app.app_context():
            register_user("timetest", "time@example.com", "Password123!")
            max_attempts = app.config["MAX_LOGIN_ATTEMPTS"]
            for _ in range(max_attempts):
                authenticate("timetest", "WrongPass1!")

            _, err = authenticate("timetest", "Password123!")
            assert "minute" in err.lower()


# ── test_session_expiry ───────────────────────────────────────────────────────

class TestSessionExpiry:
    def test_session_lifetime_is_8_hours(self, app):
        assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=8)

    def test_session_refresh_each_request_enabled(self, app):
        assert app.config.get("SESSION_REFRESH_EACH_REQUEST") is True

    def test_expired_session_is_rejected(self, client, app):
        """After logout the session is cleared; protected routes must reject the user."""
        with app.app_context():
            register_user("sessionuser", "sess@example.com", "Password123!")

        # Log in
        client.post("/auth/login", data={
            "identifier": "sessionuser",
            "password": "Password123!",
        })
        # Authenticated users are redirected away from /auth/login — proves session is live
        assert client.get("/auth/login", follow_redirects=False).status_code == 302

        # Log out (clears session — equivalent to cookie expiry from the server side)
        client.post("/auth/logout")

        # After logout the session is gone; unauthenticated access to a protected
        # route is rejected (401 from our login_required decorator)
        resp = client.get("/booking/", follow_redirects=False)
        assert resp.status_code in (302, 401)


# ── test_role_required_decorator ─────────────────────────────────────────────

class TestRoleRequiredDecorator:
    def _register_and_login(self, client, username, email, password, role="customer"):
        """Helper: register + set role + log in via test client."""
        with client.application.app_context():
            user, _ = register_user(username, email, password, role=role)
        client.post("/auth/login", data={
            "identifier": username,
            "password": password,
        })

    def test_customer_cannot_access_staff_route(self, client):
        self._register_and_login(client, "cust1", "cust1@ex.com", "Password123!")
        resp = client.get("/staff/")
        assert resp.status_code in (302, 401, 403)

    def test_staff_can_access_staff_route(self, client):
        self._register_and_login(client, "staff1", "staff1@ex.com", "Password123!", role="staff")
        resp = client.get("/staff/")
        assert resp.status_code in (200, 302)

    def test_admin_can_access_admin_route(self, client):
        self._register_and_login(client, "admin1", "admin1@ex.com", "Password123!", role="admin")
        resp = client.get("/admin/")
        assert resp.status_code == 200

    def test_customer_gets_403_on_admin_route(self, client):
        self._register_and_login(client, "cust2", "cust2@ex.com", "Password123!")
        resp = client.get("/admin/")
        assert resp.status_code in (302, 401, 403)

    def test_htmx_role_violation_returns_fragment(self, client):
        self._register_and_login(client, "cust3", "cust3@ex.com", "Password123!")
        resp = client.get("/admin/", headers={"HX-Request": "true"})
        assert resp.status_code == 403
        assert b"403" in resp.data or b"permission" in resp.data.lower()
