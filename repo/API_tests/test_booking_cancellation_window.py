"""
HTTP-layer tests for the 12-hour cancellation/reschedule window.

Within 12 hours: operations are ALLOWED but flagged as breaches and a
late-cancel credit penalty is applied.
Outside 12 hours: operations succeed with no breach.
"""
import pytest
from datetime import datetime, timedelta

from app.models.studio import StudioSession, Reservation
from app.models.analytics import CreditHistory
from app.services.booking_service import create_reservation


def _login(client, username="testcustomer", password="TestPass123!"):
    return client.post(
        "/auth/login",
        data={"identifier": username, "password": password},
        follow_redirects=True,
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def imminent_session(db, sample_users, sample_room):
    """A session starting in 6 hours (inside the 12-hour breach window)."""
    start = datetime.utcnow() + timedelta(hours=6)
    s = StudioSession(
        title="Imminent Yoga",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start,
        end_time=start + timedelta(hours=1),
        capacity=15,
        is_active=True,
    )
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture
def imminent_reservation(db, sample_users, imminent_session):
    """A confirmed reservation on the imminent session."""
    result = create_reservation(sample_users["customer"].id, imminent_session.id)
    return Reservation.query.get(result["reservation_id"])


@pytest.fixture
def future_session(db, sample_users, sample_room):
    """A session starting in 48 hours (safely outside the 12-hour window)."""
    start = datetime.utcnow() + timedelta(hours=48)
    s = StudioSession(
        title="Future Yoga",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start,
        end_time=start + timedelta(hours=1),
        capacity=15,
        is_active=True,
    )
    db.session.add(s)
    db.session.commit()
    return s


# ── Cancel within 12 hours — allowed, breach recorded ─────────────────────────

class TestCancelWithin12Hours:
    def test_cancel_returns_200(self, client, sample_users, imminent_reservation):
        """POST /booking/<id>/cancel within 12 h is allowed and returns 200."""
        _login(client)
        resp = client.post(f"/booking/{imminent_reservation.id}/cancel")
        assert resp.status_code == 200

    def test_cancel_sets_reservation_canceled(self, client, db, sample_users, imminent_reservation):
        """Reservation status becomes 'canceled' after a late cancel."""
        _login(client)
        client.post(f"/booking/{imminent_reservation.id}/cancel")
        db.session.refresh(imminent_reservation)
        assert imminent_reservation.status == "canceled"

    def test_cancel_sets_breach_flag(self, client, db, sample_users, imminent_reservation):
        """breach_flag is True after a late cancel."""
        _login(client)
        client.post(f"/booking/{imminent_reservation.id}/cancel")
        db.session.refresh(imminent_reservation)
        assert imminent_reservation.breach_flag is True

    def test_cancel_deducts_credit(self, client, db, sample_users, imminent_reservation):
        """A late_cancel CreditHistory entry is recorded with -1 points."""
        _login(client)
        client.post(f"/booking/{imminent_reservation.id}/cancel")
        entry = CreditHistory.query.filter_by(
            user_id=sample_users["customer"].id,
            event_type="late_cancel",
        ).first()
        assert entry is not None
        assert entry.points == -1

    def test_cancel_response_warns_breach(self, client, sample_users, imminent_reservation):
        """Response body mentions the breach / 12-hour window."""
        _login(client)
        resp = client.post(f"/booking/{imminent_reservation.id}/cancel")
        assert b"12" in resp.data or b"breach" in resp.data.lower() or b"late" in resp.data.lower()


# ── Cancel outside 12 hours — no breach ───────────────────────────────────────

class TestCancelOutside12Hours:
    def test_cancel_returns_200(self, client, sample_users, db, sample_session):
        """POST /booking/<id>/cancel with >12 h remaining returns 200."""
        _login(client)
        result = create_reservation(sample_users["customer"].id, sample_session.id)
        resp = client.post(f"/booking/{result['reservation_id']}/cancel")
        assert resp.status_code == 200

    def test_no_breach_flag(self, client, db, sample_users, sample_session):
        """breach_flag stays False for a timely cancel."""
        _login(client)
        result = create_reservation(sample_users["customer"].id, sample_session.id)
        client.post(f"/booking/{result['reservation_id']}/cancel")
        res = Reservation.query.get(result["reservation_id"])
        assert res.breach_flag is not True


# ── Reschedule within 12 hours — allowed, breach recorded ─────────────────────

class TestRescheduleWithin12Hours:
    def test_reschedule_returns_200(self, client, db, sample_users,
                                    imminent_reservation, future_session):
        """POST /booking/<id>/reschedule within 12 h is allowed and returns 200."""
        _login(client)
        resp = client.post(
            f"/booking/{imminent_reservation.id}/reschedule",
            data={"new_session_id": str(future_session.id)},
        )
        assert resp.status_code == 200

    def test_reschedule_sets_breach_flag(self, client, db, sample_users,
                                         imminent_reservation, future_session):
        """Old reservation has breach_flag=True after a late reschedule."""
        _login(client)
        client.post(
            f"/booking/{imminent_reservation.id}/reschedule",
            data={"new_session_id": str(future_session.id)},
        )
        db.session.refresh(imminent_reservation)
        assert imminent_reservation.breach_flag is True

    def test_reschedule_deducts_credit(self, client, db, sample_users,
                                       imminent_reservation, future_session):
        """A late_cancel CreditHistory entry is recorded for a late reschedule."""
        _login(client)
        client.post(
            f"/booking/{imminent_reservation.id}/reschedule",
            data={"new_session_id": str(future_session.id)},
        )
        entry = CreditHistory.query.filter_by(
            user_id=sample_users["customer"].id,
            event_type="late_cancel",
        ).first()
        assert entry is not None
        assert entry.points == -1
