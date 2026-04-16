"""
HTTP-layer tests for admin appeal resolution.

Routes under test:
  GET  /admin/appeals                        – appeals dashboard
  POST /admin/appeals/<id>/resolve           – resolve an appeal
"""
import pytest
from datetime import datetime, timedelta

from app.models.studio import StudioSession, Reservation
from app.models.review import Review, Appeal


# ── helpers ────────────────────────────────────────────────────────────────────

def _login(client, username, password="TestPass123!"):
    return client.post(
        "/auth/login",
        data={"identifier": username, "password": password},
        follow_redirects=True,
    )


def _make_review_with_appeal(db, sample_users, sample_room):
    """Create a completed session → reservation → review → pending appeal."""
    start = datetime.utcnow() - timedelta(hours=3)
    session = StudioSession(
        title="Appeal Test Class",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start,
        end_time=start + timedelta(hours=1),
        capacity=15,
        is_active=True,
    )
    db.session.add(session)
    db.session.commit()

    reservation = Reservation(
        user_id=sample_users["customer"].id,
        session_id=session.id,
        status="completed",
    )
    db.session.add(reservation)
    db.session.commit()

    review = Review(
        reservation_id=reservation.id,
        user_id=sample_users["customer"].id,
        rating=1,
        tags="[]",
        text="Terrible class, instructor was awful.",
        status="active",
        reviewer_role="customer",
    )
    db.session.add(review)
    db.session.commit()

    appeal = Appeal(
        review_id=review.id,
        user_id=sample_users["staff"].id,
        reason="This review contains false information and is damaging to my career.",
        status="pending",
        deadline=datetime.utcnow() + timedelta(days=5),
    )
    db.session.add(appeal)
    db.session.commit()

    return {"session": session, "reservation": reservation, "review": review, "appeal": appeal}


# ── Appeals dashboard ─────────────────────────────────────────────────────────

class TestAppealsDashboard:
    def test_admin_can_access(self, client, db, sample_users, sample_room):
        _login(client, "testadmin")
        resp = client.get("/admin/appeals")
        assert resp.status_code == 200

    def test_non_admin_is_forbidden(self, client, db, sample_users):
        _login(client, "testcustomer")
        resp = client.get("/admin/appeals", follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_unauthenticated_redirects(self, client, db):
        resp = client.get("/admin/appeals", follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_pending_appeal_listed(self, client, db, sample_users, sample_room):
        _make_review_with_appeal(db, sample_users, sample_room)
        _login(client, "testadmin")
        resp = client.get("/admin/appeals")
        assert resp.status_code == 200
        assert b"Appeal Test Class" in resp.data or b"pending" in resp.data.lower()


# ── Resolve appeal ─────────────────────────────────────────────────────────────

class TestResolveAppeal:
    def test_uphold_appeal_returns_200(self, client, db, sample_users, sample_room):
        """Admin upholding an appeal gets a 200 with resolution fragment."""
        data = _make_review_with_appeal(db, sample_users, sample_room)
        _login(client, "testadmin")
        resp = client.post(
            f"/admin/appeals/{data['appeal'].id}/resolve",
            data={
                "decision": "upheld",
                "resolution_text": "The review has been removed after investigation.",
            },
        )
        assert resp.status_code == 200
        assert b"upheld" in resp.data.lower() or b"resolved" in resp.data.lower()

    def test_uphold_appeal_deducts_dispute_credit(self, client, db, sample_users, sample_room):
        """Upholding an appeal records a -5 dispute_upheld credit event for the reviewer."""
        from app.models.analytics import CreditHistory
        data = _make_review_with_appeal(db, sample_users, sample_room)
        _login(client, "testadmin")
        client.post(
            f"/admin/appeals/{data['appeal'].id}/resolve",
            data={
                "decision": "upheld",
                "resolution_text": "Review removed after investigation.",
            },
        )
        credit = CreditHistory.query.filter_by(
            user_id=sample_users["customer"].id,
            event_type="dispute_upheld",
        ).first()
        assert credit is not None
        assert credit.points == -5

    def test_reject_appeal_returns_200(self, client, db, sample_users, sample_room):
        """Admin rejecting an appeal gets a 200 and review stays active."""
        data = _make_review_with_appeal(db, sample_users, sample_room)
        _login(client, "testadmin")
        resp = client.post(
            f"/admin/appeals/{data['appeal'].id}/resolve",
            data={
                "decision": "rejected",
                "resolution_text": "Review is within community guidelines.",
            },
        )
        assert resp.status_code == 200
        db.session.refresh(data["review"])
        assert data["review"].status == "active"

    def test_upheld_appeal_changes_review_status(self, client, db, sample_users, sample_room):
        """When an appeal is upheld, the underlying review is hidden/removed."""
        data = _make_review_with_appeal(db, sample_users, sample_room)
        _login(client, "testadmin")
        client.post(
            f"/admin/appeals/{data['appeal'].id}/resolve",
            data={
                "decision": "upheld",
                "resolution_text": "Upheld after investigation.",
            },
        )
        db.session.refresh(data["review"])
        assert data["review"].status in ("hidden", "removed", "upheld")

    def test_non_admin_cannot_resolve(self, client, db, sample_users, sample_room):
        """A customer or staff member cannot resolve appeals."""
        data = _make_review_with_appeal(db, sample_users, sample_room)
        _login(client, "testcustomer")
        resp = client.post(
            f"/admin/appeals/{data['appeal'].id}/resolve",
            data={"decision": "upheld", "resolution_text": "Unauthorized attempt."},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403)

    def test_unauthenticated_cannot_resolve(self, client, db, sample_users, sample_room):
        """Unauthenticated requests to resolve an appeal are redirected/rejected."""
        data = _make_review_with_appeal(db, sample_users, sample_room)
        resp = client.post(
            f"/admin/appeals/{data['appeal'].id}/resolve",
            data={"decision": "upheld", "resolution_text": "No auth."},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 401)

    def test_invalid_decision_returns_error(self, client, db, sample_users, sample_room):
        """An unrecognized decision value (not 'upheld' or 'rejected') must not silently succeed."""
        data = _make_review_with_appeal(db, sample_users, sample_room)
        _login(client, "testadmin")
        resp = client.post(
            f"/admin/appeals/{data['appeal'].id}/resolve",
            data={"decision": "dismissed", "resolution_text": "Some text."},
        )
        assert resp.status_code in (200, 400)
        # If 200, it must be an error fragment rather than a success fragment
        if resp.status_code == 200:
            assert b"unknown" in resp.data.lower() or b"error" in resp.data.lower()

    def test_resolve_nonexistent_appeal(self, client, db, sample_users):
        """Resolving a nonexistent appeal must not 500."""
        _login(client, "testadmin")
        resp = client.post(
            "/admin/appeals/999999/resolve",
            data={"decision": "upheld", "resolution_text": "Ghost appeal."},
        )
        assert resp.status_code in (200, 400, 404)
