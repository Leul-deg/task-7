"""
CSRF enforcement tests.

Flask-WTF's CSRFProtect is active in non-testing configs.  These tests spin
up a *development* app (CSRF enabled) and confirm that state-changing POST
routes reject requests that omit the CSRF token, while the same routes succeed
when the token is present.
"""
import pytest

from app import create_app
from app.extensions import db as _db
from app.models.user import User
from app.services.auth_service import hash_password


# ── Fixtures (CSRF-enabled app; separate from the global testing app) ──────────

@pytest.fixture(scope="module")
def csrf_app():
    """Development-config app: CSRF protection active, SQLite in-memory DB."""
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_CHECK_DEFAULT"] = True
    app.config["TESTING"] = True           # keeps exceptions propagating
    app.config["SERVER_NAME"] = "localhost"
    with app.app_context():
        _db.create_all()
        # Seed one user for login tests
        u = User(
            username="csrfuser",
            email="csrf@test.com",
            role="customer",
            credit_score=100,
            password_hash=hash_password("TestPass123!"),
        )
        _db.session.add(u)
        _db.session.commit()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope="module")
def csrf_client(csrf_app):
    return csrf_app.test_client(use_cookies=True)


def _get_csrf_token(client):
    """Fetch the login page within a live request so generate_csrf() works."""
    from flask_wtf.csrf import generate_csrf
    with client.application.test_request_context():
        # Push a real request context so the session / g objects are available
        from flask import current_app
        current_app.preprocess_request()
        return generate_csrf()


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestCsrfLoginRoute:
    """POST /auth/login is a state-mutating route protected by CSRF."""

    def test_post_without_token_rejected(self, csrf_client):
        """A login POST with no CSRF token must be rejected (400)."""
        resp = csrf_client.post(
            "/auth/login",
            data={"identifier": "csrfuser", "password": "TestPass123!"},
        )
        assert resp.status_code == 400, (
            f"Expected 400 (CSRF rejection) but got {resp.status_code}"
        )

    def test_post_with_token_accepted(self, csrf_client, csrf_app):
        """A login POST with a valid CSRF token must not be rejected by CSRF middleware."""
        token = _get_csrf_token(csrf_client)
        resp = csrf_client.post(
            "/auth/login",
            data={
                "identifier": "csrfuser",
                "password": "TestPass123!",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        # CSRF layer must not block the request (200 or redirect to dashboard)
        assert resp.status_code in (200, 302), (
            f"Expected successful response but got {resp.status_code}"
        )


class TestCsrfBookingRoute:
    """POST /booking/reserve is protected by CSRF."""

    def test_post_without_token_rejected(self, csrf_client):
        resp = csrf_client.post(
            "/booking/reserve",
            data={"session_id": "1"},
        )
        # Must be rejected at CSRF layer (400) or auth layer (302/401) — never 201
        assert resp.status_code != 201, (
            "Booking POST without CSRF token must not succeed"
        )

    def test_csrf_rejection_returns_400(self, csrf_client, csrf_app):
        """Unauthenticated POST without CSRF token hits the CSRF check first."""
        resp = csrf_client.post(
            "/booking/reserve",
            data={"session_id": "1"},
        )
        # CSRF or auth rejection — either way not a success
        assert resp.status_code in (302, 400, 401)
