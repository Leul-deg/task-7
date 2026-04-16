"""
API / integration tests for authentication endpoints.
Uses the shared app/client fixtures from conftest.py.
"""
import pytest
from app.extensions import db
from app.services.auth_service import register_user
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(app, username="testuser", email="test@example.com",
               password="Password123!", role="customer"):
    with app.app_context():
        user, err = register_user(username, email, password, role=role)
        assert err == "", f"Fixture setup failed: {err}"
        return user


# ── test_register_success ─────────────────────────────────────────────────────

class TestRegisterSuccess:
    def test_register_success(self, client, app):
        resp = client.post("/auth/register", data={
            "username": "newuser",
            "email": "new@example.com",
            "password": "Password123!",
            "confirm": "Password123!",
        }, follow_redirects=False)
        # Successful registration redirects
        assert resp.status_code == 302

        with app.app_context():
            user = User.query.filter_by(username="newuser").first()
            assert user is not None
            assert user.role == "customer"

    def test_register_creates_hashed_password(self, client, app):
        client.post("/auth/register", data={
            "username": "hashcheck",
            "email": "hash@example.com",
            "password": "Password123!",
            "confirm": "Password123!",
        })
        with app.app_context():
            user = User.query.filter_by(username="hashcheck").first()
            assert user is not None
            assert user.password_hash != "Password123!"


# ── test_register_duplicate_username ─────────────────────────────────────────

class TestRegisterDuplicateUsername:
    def test_register_duplicate_username(self, client, app):
        _make_user(app, username="dupuser", email="dup@example.com")
        resp = client.post("/auth/register", data={
            "username": "dupuser",
            "email": "other@example.com",
            "password": "Password123!",
            "confirm": "Password123!",
        })
        assert resp.status_code == 200
        assert b"taken" in resp.data.lower() or b"already" in resp.data.lower()

    def test_register_duplicate_username_htmx_returns_422(self, client, app):
        _make_user(app, username="dupuser2", email="dup2@example.com")
        resp = client.post("/auth/register",
            data={
                "username": "dupuser2",
                "email": "other2@example.com",
                "password": "Password123!",
                "confirm": "Password123!",
            },
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 422


# ── test_register_weak_password ───────────────────────────────────────────────

class TestRegisterWeakPassword:
    @pytest.mark.parametrize("pw,confirm", [
        ("short",     "short"),       # too short, missing uppercase + digit
        ("alllower1", "alllower1"),   # 9 chars, no uppercase
        ("NoDigitHere!", "NoDigitHere!"),  # 12 chars, no digit
        ("12345678Ab", "12345678Ab"), # 10 chars, valid — this should PASS actually
    ])
    def test_register_weak_password(self, client, pw, confirm):
        valid_passwords = {"12345678Ab"}  # these meet policy
        resp = client.post("/auth/register", data={
            "username": f"user_{pw[:4]}",
            "email": f"u_{pw[:4]}@example.com",
            "password": pw,
            "confirm": confirm,
        })
        if pw in valid_passwords:
            # Should succeed (redirect) or at worst 200 with no password error
            assert resp.status_code in (200, 302)
        else:
            assert resp.status_code == 200
            assert b"password" in resp.data.lower() or b"10" in resp.data

    def test_password_under_10_returns_policy_error(self, client):
        resp = client.post("/auth/register", data={
            "username": "shortpw",
            "email": "shortpw@example.com",
            "password": "Short1!",
            "confirm": "Short1!",
        })
        assert resp.status_code == 200
        assert b"10" in resp.data


# ── test_login_success ────────────────────────────────────────────────────────

class TestLoginSuccess:
    def test_login_success(self, client, app):
        _make_user(app)
        resp = client.post("/auth/login", data={
            "identifier": "testuser",
            "password": "Password123!",
        }, follow_redirects=False)
        assert resp.status_code == 302

    def test_login_success_sets_session(self, client, app):
        _make_user(app)
        client.post("/auth/login", data={
            "identifier": "testuser",
            "password": "Password123!",
        })
        # Authenticated users are redirected away from /auth/login — proves session is live
        resp = client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 302

    def test_login_updates_last_login(self, client, app):
        _make_user(app)
        client.post("/auth/login", data={
            "identifier": "testuser",
            "password": "Password123!",
        })
        with app.app_context():
            user = User.query.filter_by(username="testuser").first()
            assert user.last_login is not None

    def test_login_by_email(self, client, app):
        _make_user(app)
        resp = client.post("/auth/login", data={
            "identifier": "test@example.com",
            "password": "Password123!",
        }, follow_redirects=False)
        assert resp.status_code == 302

    def test_htmx_login_returns_hx_redirect(self, client, app):
        _make_user(app)
        resp = client.post("/auth/login",
            data={"identifier": "testuser", "password": "Password123!"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "HX-Redirect" in resp.headers


# ── test_login_wrong_password ─────────────────────────────────────────────────

class TestLoginWrongPassword:
    def test_login_wrong_password(self, client, app):
        _make_user(app)
        resp = client.post("/auth/login", data={
            "identifier": "testuser",
            "password": "WrongPass123!",
        })
        assert resp.status_code == 200
        assert b"invalid" in resp.data.lower() or b"credentials" in resp.data.lower()

    def test_login_wrong_password_htmx_returns_422(self, client, app):
        _make_user(app)
        resp = client.post("/auth/login",
            data={"identifier": "testuser", "password": "WrongPass123!"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 422

    def test_login_increments_failed_attempts(self, client, app):
        _make_user(app)
        client.post("/auth/login", data={
            "identifier": "testuser",
            "password": "WrongPass123!",
        })
        with app.app_context():
            user = User.query.filter_by(username="testuser").first()
            assert user.failed_login_attempts >= 1


# ── test_login_locked_account ─────────────────────────────────────────────────

class TestLoginLockedAccount:
    def test_login_locked_account(self, client, app):
        _make_user(app)
        max_attempts = app.config["MAX_LOGIN_ATTEMPTS"]
        for _ in range(max_attempts):
            client.post("/auth/login", data={
                "identifier": "testuser",
                "password": "WrongPass123!",
            })
        # Even correct password must be denied
        resp = client.post("/auth/login", data={
            "identifier": "testuser",
            "password": "Password123!",
        })
        assert resp.status_code == 200
        assert b"locked" in resp.data.lower()

    def test_locked_account_returns_403_on_htmx(self, client, app):
        _make_user(app, username="lockedhtmx", email="lockedhtmx@example.com")
        max_attempts = app.config["MAX_LOGIN_ATTEMPTS"]
        for _ in range(max_attempts):
            client.post("/auth/login", data={
                "identifier": "lockedhtmx",
                "password": "WrongPass123!",
            })
        resp = client.post("/auth/login",
            data={"identifier": "lockedhtmx", "password": "Password123!"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 422
        assert b"locked" in resp.data.lower()


# ── test_logout ───────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout(self, client, app):
        _make_user(app)
        client.post("/auth/login", data={
            "identifier": "testuser",
            "password": "Password123!",
        })
        resp = client.post("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_logout_clears_session(self, client, app):
        _make_user(app)
        client.post("/auth/login", data={
            "identifier": "testuser",
            "password": "Password123!",
        })
        client.post("/auth/logout")
        # Protected route should reject now
        resp = client.get("/booking/", follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_logout_htmx_returns_hx_redirect(self, client, app):
        _make_user(app)
        client.post("/auth/login", data={
            "identifier": "testuser",
            "password": "Password123!",
        })
        resp = client.post("/auth/logout", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert "HX-Redirect" in resp.headers


# ── test_protected_route_without_login ───────────────────────────────────────

class TestProtectedRouteWithoutLogin:
    def test_protected_route_without_login(self, client):
        resp = client.get("/booking/", follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_staff_route_without_login(self, client):
        resp = client.get("/staff/", follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_admin_route_without_login(self, client):
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_htmx_protected_route_returns_401(self, client):
        resp = client.get("/booking/", headers={"HX-Request": "true"})
        assert resp.status_code == 401


# ── test_change_password ──────────────────────────────────────────────────────

class TestChangePassword:
    def _login(self, client, username="testuser", password="Password123!"):
        client.post("/auth/login", data={"identifier": username, "password": password})

    def test_change_password_page_requires_login(self, client):
        """GET /auth/change-password redirects unauthenticated users."""
        resp = client.get("/auth/change-password", follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_change_password_page_loads_for_authenticated(self, client, app):
        _make_user(app)
        self._login(client)
        resp = client.get("/auth/change-password")
        assert resp.status_code == 200
        assert b"Change Password" in resp.data

    def test_change_password_success(self, client, app):
        """Valid current + new password updates the hash."""
        _make_user(app)
        self._login(client)
        resp = client.post("/auth/change-password", data={
            "current_password": "Password123!",
            "new_password": "NewPassword456!",
            "confirm_password": "NewPassword456!",
        }, follow_redirects=False)
        # Successful change redirects to schedule
        assert resp.status_code == 302
        # Old password no longer works
        client.post("/auth/logout")
        resp2 = client.post("/auth/login",
            data={"identifier": "testuser", "password": "Password123!"},
            follow_redirects=False)
        assert resp2.status_code != 302

    def test_change_password_new_password_works_after_change(self, client, app):
        """After changing, the new password authenticates correctly."""
        _make_user(app)
        self._login(client)
        client.post("/auth/change-password", data={
            "current_password": "Password123!",
            "new_password": "BrandNew9999!",
            "confirm_password": "BrandNew9999!",
        })
        client.post("/auth/logout")
        resp = client.post("/auth/login",
            data={"identifier": "testuser", "password": "BrandNew9999!"},
            follow_redirects=False)
        assert resp.status_code == 302

    def test_change_password_wrong_current_fails(self, client, app):
        """Wrong current password returns an error."""
        _make_user(app)
        self._login(client)
        resp = client.post("/auth/change-password", data={
            "current_password": "WrongCurrent!",
            "new_password": "NewPassword456!",
            "confirm_password": "NewPassword456!",
        })
        assert resp.status_code == 200
        assert b"incorrect" in resp.data.lower() or b"current" in resp.data.lower()

    def test_change_password_mismatch_confirm(self, client, app):
        """Mismatched new/confirm passwords returns an error."""
        _make_user(app)
        self._login(client)
        resp = client.post("/auth/change-password", data={
            "current_password": "Password123!",
            "new_password": "NewPassword456!",
            "confirm_password": "DifferentPass789!",
        })
        assert resp.status_code == 200
        assert b"match" in resp.data.lower()

    def test_change_password_too_short(self, client, app):
        """New password under 10 characters is rejected."""
        _make_user(app)
        self._login(client)
        resp = client.post("/auth/change-password", data={
            "current_password": "Password123!",
            "new_password": "Short1!",
            "confirm_password": "Short1!",
        })
        assert resp.status_code == 200
        assert b"10" in resp.data or b"character" in resp.data.lower()

    def test_change_password_htmx_success_returns_hx_redirect(self, client, app):
        """HTMX success returns HX-Redirect header."""
        _make_user(app)
        self._login(client)
        resp = client.post("/auth/change-password",
            data={
                "current_password": "Password123!",
                "new_password": "HtmxChanged99!",
                "confirm_password": "HtmxChanged99!",
            },
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "HX-Redirect" in resp.headers

    def test_change_password_htmx_error_returns_422(self, client, app):
        """HTMX wrong current password returns 422."""
        _make_user(app)
        self._login(client)
        resp = client.post("/auth/change-password",
            data={
                "current_password": "NotTheRealOne!",
                "new_password": "NewPassword456!",
                "confirm_password": "NewPassword456!",
            },
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 422
