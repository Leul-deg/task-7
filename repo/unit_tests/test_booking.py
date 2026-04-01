"""
Unit tests for app/services/booking_service.py.
All tests use an in-memory SQLite database and call service functions directly.
"""
import pytest
from datetime import datetime, timedelta

from app.models.user import User
from app.models.studio import StudioSession, Reservation, Waitlist, Resource
from app.services.auth_service import hash_password
from app.services.booking_service import (
    get_sessions_for_date,
    check_booking_conflicts,
    create_reservation,
    cancel_reservation,
    reschedule_reservation,
    join_waitlist,
    promote_waitlist,
    get_user_bookings,
    leave_waitlist,
)


def test_get_sessions_for_date_returns_sessions(app, db, sample_session):
    """Verify sessions are returned for the correct date in correct format."""
    with app.app_context():
        date_str = sample_session.start_time.strftime("%m/%d/%Y")
        result = get_sessions_for_date(date_str)
        assert len(result) == 1
        assert result[0]["title"] == "Morning Yoga"
        assert result[0]["spots_remaining"] == 15
        assert "AM" in result[0]["start_time"] or "PM" in result[0]["start_time"]


def test_get_sessions_invalid_date_raises(app):
    """Verify ValueError raised for bad date format."""
    with app.app_context():
        with pytest.raises(ValueError, match="Invalid date format"):
            get_sessions_for_date("2026-03-31")  # wrong format


def test_create_reservation_success(app, db, sample_users, sample_session):
    """Verify successful booking creates a confirmed reservation."""
    with app.app_context():
        result = create_reservation(sample_users["customer"].id, sample_session.id)
        assert result["success"] is True
        assert "reservation_id" in result
        reservation = Reservation.query.get(result["reservation_id"])
        assert reservation.status == "confirmed"
        assert reservation.user_id == sample_users["customer"].id


def test_create_reservation_duplicate_blocked(app, db, sample_users, sample_session):
    """Verify user cannot double-book the same session."""
    with app.app_context():
        create_reservation(sample_users["customer"].id, sample_session.id)
        result = create_reservation(sample_users["customer"].id, sample_session.id)
        assert result["success"] is False
        assert "already have a reservation" in result["reason"]


def test_conflict_detection(app, db, sample_users, sample_room):
    """Verify overlapping session times are detected."""
    with app.app_context():
        tomorrow = datetime.utcnow() + timedelta(days=1)
        start1 = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        session1 = StudioSession(
            title="Yoga",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start1,
            end_time=start1 + timedelta(hours=1),
            capacity=15,
            is_active=True,
        )
        session2 = StudioSession(
            title="Pilates",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start1 + timedelta(minutes=30),
            end_time=start1 + timedelta(hours=1, minutes=30),
            capacity=15,
            is_active=True,
        )
        db.session.add_all([session1, session2])
        db.session.commit()

        create_reservation(sample_users["customer"].id, session1.id)
        result = create_reservation(sample_users["customer"].id, session2.id)
        assert result["success"] is False
        assert result["action"] == "conflict"


def test_capacity_full_offers_waitlist(app, db, sample_users, sample_room):
    """Verify full session returns waitlist option."""
    with app.app_context():
        tomorrow = datetime.utcnow() + timedelta(days=1)
        start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        session = StudioSession(
            title="Full Class",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            capacity=1,
            is_active=True,
        )
        db.session.add(session)
        db.session.commit()

        create_reservation(sample_users["customer"].id, session.id)  # fills the 1 spot

        other_user = User(
            username="other",
            email="other@test.com",
            role="customer",
            credit_score=100,
            password_hash=hash_password("TestPass123!"),
        )
        db.session.add(other_user)
        db.session.commit()

        result = create_reservation(other_user.id, session.id)
        assert result["success"] is False
        assert result["action"] == "waitlist"


def test_cancel_before_12h_no_breach(app, db, sample_users, sample_session):
    """Cancel >12 hours before start: no breach flag."""
    with app.app_context():
        create_result = create_reservation(sample_users["customer"].id, sample_session.id)
        result = cancel_reservation(create_result["reservation_id"], sample_users["customer"].id)
        assert result["success"] is True
        assert result["breach"] is False
        reservation = Reservation.query.get(create_result["reservation_id"])
        assert reservation.status == "canceled"
        assert reservation.breach_flag is False


def test_cancel_within_12h_breach(app, db, sample_users, sample_room):
    """Cancel <12 hours before start: breach flag set, credit deducted."""
    with app.app_context():
        start = datetime.utcnow() + timedelta(hours=6)  # 6 hours from now
        session = StudioSession(
            title="Soon",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            capacity=15,
            is_active=True,
        )
        db.session.add(session)
        db.session.commit()

        create_result = create_reservation(sample_users["customer"].id, session.id)
        result = cancel_reservation(create_result["reservation_id"], sample_users["customer"].id)
        assert result["success"] is True
        assert result["breach"] is True

        from app.models.analytics import CreditHistory
        credit = CreditHistory.query.filter_by(
            user_id=sample_users["customer"].id, event_type="late_cancel"
        ).first()
        assert credit is not None
        assert credit.points == -1


def test_reschedule_within_12h_breach(app, db, sample_users, sample_room):
    """Reschedule <12 hours before start: allowed, breach flag set, credit deducted."""
    with app.app_context():
        start = datetime.utcnow() + timedelta(hours=6)
        target_start = datetime.utcnow() + timedelta(days=2)
        session1 = StudioSession(
            title="Soon Session",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            capacity=15,
            is_active=True,
        )
        session2 = StudioSession(
            title="Later Session",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=target_start,
            end_time=target_start + timedelta(hours=1),
            capacity=15,
            is_active=True,
        )
        db.session.add_all([session1, session2])
        db.session.commit()

        create_result = create_reservation(sample_users["customer"].id, session1.id)
        result = reschedule_reservation(
            create_result["reservation_id"], session2.id, sample_users["customer"].id
        )

        assert result["success"] is True
        assert result["breach"] is True

        old = Reservation.query.get(create_result["reservation_id"])
        assert old.breach_flag is True
        assert old.status == "rescheduled"

        from app.models.analytics import CreditHistory
        credit = CreditHistory.query.filter_by(
            user_id=sample_users["customer"].id, event_type="late_cancel"
        ).first()
        assert credit is not None
        assert credit.points == -1


def test_waitlist_promotion_on_cancel(app, db, sample_users, sample_room):
    """When a reservation is canceled, waitlist #1 gets promoted."""
    with app.app_context():
        tomorrow = datetime.utcnow() + timedelta(days=1)
        start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        session = StudioSession(
            title="Full",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            capacity=1,
            is_active=True,
        )
        db.session.add(session)
        db.session.commit()

        create_result = create_reservation(sample_users["customer"].id, session.id)

        waitlister = User(
            username="waiter",
            email="wait@test.com",
            role="customer",
            credit_score=100,
            password_hash=hash_password("TestPass123!"),
        )
        db.session.add(waitlister)
        db.session.commit()

        join_waitlist(waitlister.id, session.id)
        cancel_reservation(create_result["reservation_id"], sample_users["customer"].id)

        promoted = Reservation.query.filter_by(
            user_id=waitlister.id, session_id=session.id, status="confirmed"
        ).first()
        assert promoted is not None


def test_reschedule_creates_linked_reservation(app, db, sample_users, sample_room):
    """Reschedule cancels old, creates new, and links them."""
    with app.app_context():
        tomorrow = datetime.utcnow() + timedelta(days=1)
        start1 = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        start2 = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
        session1 = StudioSession(
            title="AM",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start1,
            end_time=start1 + timedelta(hours=1),
            capacity=15,
            is_active=True,
        )
        session2 = StudioSession(
            title="PM",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start2,
            end_time=start2 + timedelta(hours=1),
            capacity=15,
            is_active=True,
        )
        db.session.add_all([session1, session2])
        db.session.commit()

        create_result = create_reservation(sample_users["customer"].id, session1.id)
        result = reschedule_reservation(
            create_result["reservation_id"], session2.id, sample_users["customer"].id
        )

        assert result["success"] is True
        old = Reservation.query.get(create_result["reservation_id"])
        assert old.status == "rescheduled"
        new = Reservation.query.get(result["new_reservation_id"])
        assert new.status == "confirmed"
        assert new.original_reservation_id == old.id


def test_low_credit_requires_approval(app, db, sample_users, sample_session):
    """User with credit < 50 gets pending_approval status."""
    with app.app_context():
        user = sample_users["customer"]
        user.credit_score = 40
        db.session.commit()

        result = create_reservation(user.id, sample_session.id)
        assert result["success"] is True
        reservation = Reservation.query.get(result["reservation_id"])
        assert reservation.status == "pending_approval"


def test_very_low_credit_blocked(app, db, sample_users, sample_session):
    """User with credit < 20 is blocked entirely."""
    with app.app_context():
        user = sample_users["customer"]
        user.credit_score = 15
        db.session.commit()

        result = create_reservation(user.id, sample_session.id)
        assert result["success"] is False
        assert result["action"] == "blocked"
