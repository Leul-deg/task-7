"""
API-level tests for the reviews blueprint.

Routes under test:
  GET  /reviews/session/<session_id>       – session_reviews (public)
  POST /reviews                            – submit_review (auth required)
  DELETE /reviews/<review_id>             – delete_review (auth required)
  POST /reviews/<review_id>/appeal        – file_appeal (auth required)
  GET  /reviews/my-reviews                – my_reviews (auth required)
"""
import pytest
from datetime import datetime, timedelta

from app.models.review import Review


# ── helpers ────────────────────────────────────────────────────────────────────

def _login(client, username="testcustomer", password="TestPass123!"):
    return client.post(
        "/auth/login",
        data={"identifier": username, "password": password},
        follow_redirects=True,
    )


def _make_review(db, reservation_id, user_id, rating=5, text="Great class!"):
    r = Review(
        reservation_id=reservation_id,
        user_id=user_id,
        rating=rating,
        tags="[]",
        text=text,
        status="active",
        reviewer_role="customer",
    )
    db.session.add(r)
    db.session.commit()
    return r


# ── TestSessionReviewsPublic ───────────────────────────────────────────────────

class TestSessionReviewsPublic:
    def test_returns_200(self, client, db, sample_session):
        resp = client.get(f"/reviews/session/{sample_session.id}")
        assert resp.status_code == 200

    def test_contains_session_title(self, client, db, sample_session):
        resp = client.get(f"/reviews/session/{sample_session.id}")
        assert b"Morning Yoga" in resp.data

    def test_htmx_returns_partial(self, client, db, sample_session):
        resp = client.get(
            f"/reviews/session/{sample_session.id}",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        # Partial should NOT include full page structure
        assert b"<!DOCTYPE" not in resp.data

    def test_sort_param_accepted(self, client, db, sample_session):
        for sort in ("recent", "highest", "lowest"):
            resp = client.get(f"/reviews/session/{sample_session.id}?sort={sort}")
            assert resp.status_code == 200

    def test_nonexistent_session_404(self, client, db):
        resp = client.get("/reviews/session/999999")
        assert resp.status_code == 404


# ── TestSubmitReview ──────────────────────────────────────────────────────────

class TestSubmitReview:
    def test_submit_success(self, client, db, completed_reservation, sample_users):
        _login(client, "testcustomer")
        res = completed_reservation["reservation"]
        resp = client.post(
            "/reviews",
            data={
                "reservation_id": res.id,
                "rating": "5",
                "text": "Amazing session, highly recommend.",
            },
        )
        assert resp.status_code == 201
        assert b"submitted" in resp.data.lower() or b"review" in resp.data.lower()

    def test_submit_invalid_rating(self, client, db, completed_reservation, sample_users):
        _login(client, "testcustomer")
        res = completed_reservation["reservation"]
        resp = client.post(
            "/reviews",
            data={
                "reservation_id": res.id,
                "rating": "0",
                "text": "Bad rating value.",
            },
        )
        assert resp.status_code == 400

    def test_submit_unauthenticated_redirects(self, client, db, completed_reservation):
        res = completed_reservation["reservation"]
        resp = client.post(
            "/reviews",
            data={"reservation_id": res.id, "rating": "4"},
        )
        # login_required should redirect or return 401
        assert resp.status_code in (302, 401)

    def test_duplicate_review_blocked(self, client, db, completed_reservation, sample_users):
        _login(client, "testcustomer")
        res = completed_reservation["reservation"]
        # First submission
        client.post(
            "/reviews",
            data={"reservation_id": res.id, "rating": "5", "text": "Great!"},
        )
        # Second submission same reservation
        resp = client.post(
            "/reviews",
            data={"reservation_id": res.id, "rating": "4", "text": "Another attempt"},
        )
        assert resp.status_code == 400

    def test_submit_with_content_filter(self, client, db, completed_reservation, sample_users, sample_filter):
        _login(client, "testcustomer")
        res = completed_reservation["reservation"]
        resp = client.post(
            "/reviews",
            data={
                "reservation_id": res.id,
                "rating": "3",
                "text": "This class was badword awful.",
            },
        )
        assert resp.status_code == 400


# ── TestDeleteReview ──────────────────────────────────────────────────────────

class TestDeleteReview:
    def test_author_can_delete(self, client, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        _login(client, "testcustomer")
        resp = client.delete(f"/reviews/{review.id}")
        assert resp.status_code == 200

    def test_non_author_cannot_delete(self, client, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        _login(client, "teststaff")
        resp = client.delete(f"/reviews/{review.id}")
        assert resp.status_code == 400

    def test_unauthenticated_delete_blocked(self, client, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        resp = client.delete(f"/reviews/{review.id}")
        assert resp.status_code in (302, 401)


# ── TestFileAppeal ────────────────────────────────────────────────────────────

class TestFileAppealAPI:
    def test_file_appeal_success(self, client, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        _login(client, "teststaff")
        resp = client.post(
            f"/reviews/{review.id}/appeal",
            data={"reason": "This review makes false claims that are harmful to my reputation."},
        )
        assert resp.status_code == 201
        assert b"dispute" in resp.data.lower() or b"appeal" in resp.data.lower()

    def test_short_reason_rejected(self, client, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        _login(client, "teststaff")
        resp = client.post(
            f"/reviews/{review.id}/appeal",
            data={"reason": "Short."},
        )
        assert resp.status_code == 400

    def test_unauthenticated_appeal_blocked(self, client, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        resp = client.post(
            f"/reviews/{review.id}/appeal",
            data={"reason": "This review makes false claims that are harmful."},
        )
        assert resp.status_code in (302, 401)


# ── TestMyReviews ──────────────────────────────────────────────────────────────

class TestMyReviews:
    def test_my_reviews_authenticated(self, client, db, sample_users):
        _login(client, "testcustomer")
        resp = client.get("/reviews/my-reviews")
        assert resp.status_code == 200
        assert b"My Reviews" in resp.data

    def test_my_reviews_unauthenticated_redirects(self, client, db):
        resp = client.get("/reviews/my-reviews")
        assert resp.status_code in (302, 401)

    def test_my_reviews_shows_written(self, client, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        _make_review(db, res.id, sample_users["customer"].id)
        _login(client, "testcustomer")
        resp = client.get("/reviews/my-reviews")
        assert resp.status_code == 200
        assert b"Great class" in resp.data
