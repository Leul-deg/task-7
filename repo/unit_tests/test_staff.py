"""
Unit tests for app/services/staff_service.py.
Tests call service functions directly within an app context.
"""
import pytest
from datetime import datetime, timedelta

from app.models.analytics import CreditHistory
from app.models.studio import CheckIn, Reservation, Resource, StudioSession
from app.services import staff_service


# ── Check-in tests ────────────────────────────────────────────────────────────

def test_checkin_creates_record(app, db, sample_users, completed_session_with_reservation):
    """Check-in creates a CheckIn record with correct staff_id."""
    with app.app_context():
        data = completed_session_with_reservation
        result = staff_service.perform_checkin(
            data["reservation"].id, sample_users["staff"].id
        )
        assert result["success"] is True
        checkin = CheckIn.query.filter_by(reservation_id=data["reservation"].id).first()
        assert checkin is not None
        assert checkin.staff_id == sample_users["staff"].id


def test_checkin_updates_reservation_status(app, db, sample_users, completed_session_with_reservation):
    """Check-in sets reservation status to 'completed'."""
    with app.app_context():
        data = completed_session_with_reservation
        staff_service.perform_checkin(data["reservation"].id, sample_users["staff"].id)
        reservation = Reservation.query.get(data["reservation"].id)
        assert reservation.status == "completed"


def test_checkin_awards_credit(app, db, sample_users, completed_session_with_reservation):
    """Check-in records +2 credit for the customer."""
    with app.app_context():
        data = completed_session_with_reservation
        staff_service.perform_checkin(data["reservation"].id, sample_users["staff"].id)
        credit = CreditHistory.query.filter_by(
            user_id=sample_users["customer"].id, event_type="on_time"
        ).first()
        assert credit is not None
        assert credit.points == 2


def test_checkin_before_session_start_fails(app, db, sample_users, sample_session):
    """Cannot check in before session has started (sample_session is tomorrow)."""
    with app.app_context():
        reservation = Reservation(
            user_id=sample_users["customer"].id,
            session_id=sample_session.id,
            status="confirmed",
        )
        db.session.add(reservation)
        db.session.commit()
        result = staff_service.perform_checkin(reservation.id, sample_users["staff"].id)
        assert result["success"] is False
        assert "before the session has started" in result["reason"]


def test_double_checkin_fails(app, db, sample_users, completed_session_with_reservation):
    """Second check-in attempt fails with 'already checked in'."""
    with app.app_context():
        data = completed_session_with_reservation
        staff_service.perform_checkin(data["reservation"].id, sample_users["staff"].id)
        result = staff_service.perform_checkin(data["reservation"].id, sample_users["staff"].id)
        assert result["success"] is False
        assert "already checked in" in result["reason"]


# ── No-show tests ─────────────────────────────────────────────────────────────

def test_noshow_deducts_credit(app, db, sample_users, ended_session_with_reservation):
    """No-show records -3 credit."""
    with app.app_context():
        data = ended_session_with_reservation
        result = staff_service.mark_no_show(
            data["reservation"].id, sample_users["staff"].id
        )
        assert result["success"] is True
        credit = CreditHistory.query.filter_by(
            user_id=sample_users["customer"].id, event_type="no_show"
        ).first()
        assert credit is not None
        assert credit.points == -3


def test_noshow_sets_status(app, db, sample_users, ended_session_with_reservation):
    """No-show sets reservation status to 'no_show'."""
    with app.app_context():
        data = ended_session_with_reservation
        staff_service.mark_no_show(data["reservation"].id, sample_users["staff"].id)
        reservation = Reservation.query.get(data["reservation"].id)
        assert reservation.status == "no_show"


def test_noshow_before_session_end_fails(app, db, sample_users, completed_session_with_reservation):
    """Cannot mark no-show if session end_time hasn't passed yet."""
    with app.app_context():
        data = completed_session_with_reservation
        # Create a session that started 30 min ago but ends 30 min from now
        ongoing_session = StudioSession(
            title="Ongoing",
            instructor_id=sample_users["staff"].id,
            room_id=data["session"].room_id,
            start_time=datetime.utcnow() - timedelta(minutes=30),
            end_time=datetime.utcnow() + timedelta(minutes=30),
            capacity=15,
            is_active=True,
        )
        db.session.add(ongoing_session)
        db.session.commit()
        reservation = Reservation(
            user_id=sample_users["customer"].id,
            session_id=ongoing_session.id,
            status="confirmed",
        )
        db.session.add(reservation)
        db.session.commit()
        result = staff_service.mark_no_show(reservation.id, sample_users["staff"].id)
        assert result["success"] is False
        assert "session has ended" in result["reason"]


# ── Cross-staff object-level authorization tests ──────────────────────────────

def _make_started_session_with_reservation(db, instructor, customer, room):
    """Helper: session started 30 min ago, with one confirmed reservation."""
    start = datetime.utcnow() - timedelta(minutes=30)
    session = StudioSession(
        title="Active Session",
        instructor_id=instructor.id,
        room_id=room.id,
        start_time=start,
        end_time=start + timedelta(hours=1),
        capacity=15,
        is_active=True,
    )
    db.session.add(session)
    db.session.commit()
    reservation = Reservation(
        user_id=customer.id,
        session_id=session.id,
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()
    return session, reservation


def _make_ended_session_with_reservation(db, instructor, customer, room):
    """Helper: session ended 10 min ago, with one confirmed reservation."""
    start = datetime.utcnow() - timedelta(hours=2)
    end = datetime.utcnow() - timedelta(minutes=10)
    session = StudioSession(
        title="Ended Session",
        instructor_id=instructor.id,
        room_id=room.id,
        start_time=start,
        end_time=end,
        capacity=15,
        is_active=True,
    )
    db.session.add(session)
    db.session.commit()
    reservation = Reservation(
        user_id=customer.id,
        session_id=session.id,
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()
    return session, reservation


def _make_other_staff(db):
    from app.services.auth_service import hash_password
    from app.models.user import User
    other = User(
        username="otherstaff",
        email="otherstaff@test.com",
        role="staff",
        credit_score=100,
        password_hash=hash_password("TestPass123!"),
    )
    db.session.add(other)
    db.session.commit()
    return other


def test_checkin_unauthorized_staff_rejected(app, db, sample_users, sample_room):
    """Staff B cannot check in a customer in Staff A's session."""
    with app.app_context():
        other_staff = _make_other_staff(db)
        _, reservation = _make_started_session_with_reservation(
            db, sample_users["staff"], sample_users["customer"], sample_room
        )
        result = staff_service.perform_checkin(reservation.id, other_staff.id)
        assert result["success"] is False
        assert "not authorized" in result["reason"].lower()


def test_checkin_authorized_instructor_succeeds(app, db, sample_users, sample_room):
    """The assigned instructor can check in customers in their own session."""
    with app.app_context():
        _, reservation = _make_started_session_with_reservation(
            db, sample_users["staff"], sample_users["customer"], sample_room
        )
        result = staff_service.perform_checkin(reservation.id, sample_users["staff"].id)
        assert result["success"] is True


def test_checkin_admin_can_act_on_any_session(app, db, sample_users, sample_room):
    """Admin can check in customers regardless of session instructor."""
    with app.app_context():
        _, reservation = _make_started_session_with_reservation(
            db, sample_users["staff"], sample_users["customer"], sample_room
        )
        result = staff_service.perform_checkin(reservation.id, sample_users["admin"].id)
        assert result["success"] is True


def test_noshow_unauthorized_staff_rejected(app, db, sample_users, sample_room):
    """Staff B cannot mark no-show in Staff A's session."""
    with app.app_context():
        other_staff = _make_other_staff(db)
        _, reservation = _make_ended_session_with_reservation(
            db, sample_users["staff"], sample_users["customer"], sample_room
        )
        result = staff_service.mark_no_show(reservation.id, other_staff.id)
        assert result["success"] is False
        assert "not authorized" in result["reason"].lower()


def test_noshow_authorized_instructor_succeeds(app, db, sample_users, sample_room):
    """The assigned instructor can mark no-shows in their own session."""
    with app.app_context():
        _, reservation = _make_ended_session_with_reservation(
            db, sample_users["staff"], sample_users["customer"], sample_room
        )
        result = staff_service.mark_no_show(reservation.id, sample_users["staff"].id)
        assert result["success"] is True


def test_noshow_admin_can_act_on_any_session(app, db, sample_users, sample_room):
    """Admin can mark no-shows regardless of session instructor."""
    with app.app_context():
        _, reservation = _make_ended_session_with_reservation(
            db, sample_users["staff"], sample_users["customer"], sample_room
        )
        result = staff_service.mark_no_show(reservation.id, sample_users["admin"].id)
        assert result["success"] is True


# ── Resource availability tests ───────────────────────────────────────────────

def test_instructor_conflict_detected(app, db, sample_users, sample_room):
    """Detect instructor double-booking across overlapping sessions."""
    with app.app_context():
        tomorrow = datetime.utcnow() + timedelta(days=1)
        start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)

        room2 = Resource(type="room", name="Studio B", capacity=15)
        db.session.add(room2)
        db.session.commit()

        session1 = StudioSession(
            title="Yoga A",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            capacity=15,
            is_active=True,
        )
        session2 = StudioSession(
            title="Yoga B",
            instructor_id=sample_users["staff"].id,
            room_id=room2.id,
            start_time=start + timedelta(minutes=30),
            end_time=start + timedelta(hours=1, minutes=30),
            capacity=15,
            is_active=True,
        )
        db.session.add_all([session1, session2])
        db.session.commit()

        result = staff_service.check_resource_availability(session2.id)
        assert result["has_issues"] is True
        assert any(c["type"] == "instructor_double_booked" for c in result["conflicts"])


# ── Session creation tests ────────────────────────────────────────────────────

def test_create_session_validates_end_time(app, db, sample_users, sample_room):
    """End time before start time is rejected."""
    with app.app_context():
        tomorrow = datetime.utcnow() + timedelta(days=1)
        start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        result = staff_service.create_studio_session(
            title="Bad",
            description="",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start,
            end_time=start - timedelta(hours=1),
            capacity=15,
        )
        assert result["success"] is False
        assert "End time must be after start time" in result["reason"]


def test_create_session_requires_title(app, db, sample_users, sample_room):
    """Empty title is rejected."""
    with app.app_context():
        tomorrow = datetime.utcnow() + timedelta(days=1)
        start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        result = staff_service.create_studio_session(
            title="",
            description="",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            capacity=15,
        )
        assert result["success"] is False
        assert "Title is required" in result["reason"]


def test_create_session_requires_staff_instructor(app, db, sample_users, sample_room):
    """Non-staff instructor ID is rejected."""
    with app.app_context():
        tomorrow = datetime.utcnow() + timedelta(days=1)
        start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        result = staff_service.create_studio_session(
            title="Good Title",
            description="",
            instructor_id=sample_users["customer"].id,  # customer, not staff
            room_id=sample_room.id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            capacity=15,
        )
        assert result["success"] is False
        assert "staff member" in result["reason"]


def test_create_session_success(app, db, sample_users, sample_room):
    """Valid inputs create a new session."""
    with app.app_context():
        tomorrow = datetime.utcnow() + timedelta(days=1)
        start = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
        result = staff_service.create_studio_session(
            title="Afternoon Pilates",
            description="Core strength class",
            instructor_id=sample_users["staff"].id,
            room_id=sample_room.id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            capacity=12,
        )
        assert result["success"] is True
        assert "session_id" in result
        session = StudioSession.query.get(result["session_id"])
        assert session is not None
        assert session.title == "Afternoon Pilates"
        assert session.capacity == 12


# ── Approval tests ────────────────────────────────────────────────────────────

def test_approve_pending_booking(app, db, sample_users, sample_session):
    """Approving a pending reservation sets status to confirmed."""
    with app.app_context():
        reservation = Reservation(
            user_id=sample_users["customer"].id,
            session_id=sample_session.id,
            status="pending_approval",
        )
        db.session.add(reservation)
        db.session.commit()
        result = staff_service.resolve_approval(
            reservation.id, approved=True, staff_id=sample_users["staff"].id
        )
        assert result["success"] is True
        updated = Reservation.query.get(reservation.id)
        assert updated.status == "confirmed"


def test_deny_pending_booking(app, db, sample_users, sample_session):
    """Denying sets status to canceled."""
    with app.app_context():
        reservation = Reservation(
            user_id=sample_users["customer"].id,
            session_id=sample_session.id,
            status="pending_approval",
        )
        db.session.add(reservation)
        db.session.commit()
        staff_service.resolve_approval(
            reservation.id, approved=False, staff_id=sample_users["staff"].id
        )
        updated = Reservation.query.get(reservation.id)
        assert updated.status == "canceled"


def test_resolve_non_pending_fails(app, db, sample_users, sample_session):
    """resolve_approval on an already-confirmed reservation returns an error."""
    with app.app_context():
        reservation = Reservation(
            user_id=sample_users["customer"].id,
            session_id=sample_session.id,
            status="confirmed",
        )
        db.session.add(reservation)
        db.session.commit()
        result = staff_service.resolve_approval(
            reservation.id, approved=True, staff_id=sample_users["staff"].id
        )
        assert result["success"] is False
        assert "not pending approval" in result["reason"]


# ── Roster tests ──────────────────────────────────────────────────────────────

def test_get_session_roster_structure(app, db, sample_users, completed_session_with_reservation):
    """get_session_roster returns expected dict structure."""
    with app.app_context():
        data = completed_session_with_reservation
        result = staff_service.get_session_roster(data["session"].id)
        assert "session" in result
        assert "roster" in result
        assert "summary" in result
        assert len(result["roster"]) == 1
        row = result["roster"][0]
        assert row["customer_name"] == sample_users["customer"].username
        assert row["checked_in"] is False
        assert row["is_no_show"] is False
        assert result["summary"]["total"] == 1
        assert result["summary"]["pending"] == 1


def test_get_session_roster_invalid_session(app, db):
    """get_session_roster raises ValueError for unknown session_id."""
    with app.app_context():
        with pytest.raises(ValueError, match="not found"):
            staff_service.get_session_roster(99999)
