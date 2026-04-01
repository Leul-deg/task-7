"""
API-level tests for booking HTTP endpoints.
All interactions go through the Flask test client.
"""
import pytest
from datetime import datetime, timedelta

from app.models.user import User
from app.models.studio import StudioSession, Reservation, Resource
from app.services.auth_service import hash_password


def test_schedule_page_loads(client, sample_users, login_as):
    """GET /schedule returns 200 when logged in."""
    login_as("testcustomer", "TestPass123!")
    resp = client.get("/schedule")
    assert resp.status_code == 200


def test_schedule_requires_login(client):
    """GET /schedule without login redirects to login page."""
    resp = client.get("/schedule", follow_redirects=False)
    assert resp.status_code in (401, 302)


def test_book_session_requires_login(client, sample_session):
    """POST /booking/reserve without login returns 401 or redirect."""
    resp = client.post("/booking/reserve", data={"session_id": sample_session.id})
    assert resp.status_code in (401, 302)


def test_book_session_success(client, login_as, sample_users, sample_session):
    """POST /booking/reserve with valid data returns 201."""
    login_as("testcustomer", "TestPass123!")
    resp = client.post("/booking/reserve", data={"session_id": str(sample_session.id)})
    assert resp.status_code == 201


def test_book_session_duplicate_returns_error(client, login_as, sample_users, sample_session):
    """POST /booking/reserve twice for the same session returns 409."""
    login_as("testcustomer", "TestPass123!")
    client.post("/booking/reserve", data={"session_id": str(sample_session.id)})
    resp = client.post("/booking/reserve", data={"session_id": str(sample_session.id)})
    assert resp.status_code == 409


def test_cancel_reservation_success(client, login_as, sample_users, sample_session, db):
    """POST /booking/{id}/cancel returns 200."""
    login_as("testcustomer", "TestPass123!")
    client.post("/booking/reserve", data={"session_id": str(sample_session.id)})
    reservation = Reservation.query.filter_by(user_id=sample_users["customer"].id).first()
    resp = client.post(f"/booking/{reservation.id}/cancel")
    assert resp.status_code == 200


def test_cancel_other_users_reservation_forbidden(client, login_as, sample_users, sample_session, db):
    """POST /booking/{id}/cancel for someone else's reservation returns 403."""
    # Staff books
    from app.services.booking_service import create_reservation
    create_result = create_reservation(sample_users["staff"].id, sample_session.id)
    reservation_id = create_result["reservation_id"]

    # Customer tries to cancel it
    login_as("testcustomer", "TestPass123!")
    resp = client.post(f"/booking/{reservation_id}/cancel")
    assert resp.status_code == 403


def test_my_bookings_page(client, login_as, sample_users):
    """GET /booking/my-bookings returns 200 when logged in."""
    login_as("testcustomer", "TestPass123!")
    resp = client.get("/booking/my-bookings")
    assert resp.status_code == 200


def test_my_bookings_requires_login(client):
    """GET /booking/my-bookings without login redirects."""
    resp = client.get("/booking/my-bookings", follow_redirects=False)
    assert resp.status_code in (401, 302)


def test_my_bookings_htmx_tab_returns_fragment(client, login_as, sample_users):
    """GET /booking/my-bookings with HX-Request header returns partial HTML."""
    login_as("testcustomer", "TestPass123!")
    resp = client.get(
        "/booking/my-bookings?tab=upcoming",
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    # Fragment should not contain the full page nav
    assert b"<!DOCTYPE" not in resp.data


def test_join_waitlist_success(client, login_as, sample_users, sample_room, db):
    """POST /booking/waitlist for a full session returns 201."""
    login_as("testcustomer", "TestPass123!")
    tomorrow = datetime.utcnow() + timedelta(days=1)
    start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    session = StudioSession(
        title="Full",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start,
        end_time=start + timedelta(hours=1),
        capacity=0,
        is_active=True,
    )
    db.session.add(session)
    db.session.commit()
    resp = client.post("/booking/waitlist", data={"session_id": str(session.id)})
    assert resp.status_code == 201


def test_join_waitlist_requires_login(client, sample_session):
    """POST /booking/waitlist without login returns 401 or redirect."""
    resp = client.post("/booking/waitlist", data={"session_id": str(sample_session.id)})
    assert resp.status_code in (401, 302)


def test_session_detail_page_loads(client, login_as, sample_users, sample_session):
    """GET /schedule/sessions/{id} returns 200."""
    login_as("testcustomer", "TestPass123!")
    resp = client.get(f"/schedule/sessions/{sample_session.id}")
    assert resp.status_code == 200


def test_session_detail_contains_title(client, login_as, sample_users, sample_session):
    """Session detail page body includes the session title."""
    login_as("testcustomer", "TestPass123!")
    resp = client.get(f"/schedule/sessions/{sample_session.id}")
    assert b"Morning Yoga" in resp.data


def test_session_detail_404_for_missing(client, login_as, sample_users):
    """GET /schedule/sessions/99999 returns 404."""
    login_as("testcustomer", "TestPass123!")
    resp = client.get("/schedule/sessions/99999")
    assert resp.status_code == 404


def test_reschedule_success(client, login_as, sample_users, sample_room, db):
    """POST /booking/{id}/reschedule moves to the new session."""
    login_as("testcustomer", "TestPass123!")
    tomorrow = datetime.utcnow() + timedelta(days=1)
    start1 = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    start2 = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    session1 = StudioSession(
        title="AM Yoga",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start1,
        end_time=start1 + timedelta(hours=1),
        capacity=15,
        is_active=True,
    )
    session2 = StudioSession(
        title="PM Yoga",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start2,
        end_time=start2 + timedelta(hours=1),
        capacity=15,
        is_active=True,
    )
    db.session.add_all([session1, session2])
    db.session.commit()

    # Book the first session
    book_resp = client.post("/booking/reserve", data={"session_id": str(session1.id)})
    assert book_resp.status_code == 201

    reservation = Reservation.query.filter_by(
        user_id=sample_users["customer"].id, session_id=session1.id
    ).first()

    # Reschedule to second session
    resp = client.post(
        f"/booking/{reservation.id}/reschedule",
        data={"new_session_id": str(session2.id)},
    )
    assert resp.status_code == 200
    assert reservation.status == "rescheduled"


def test_available_sessions_returns_fragment(client, login_as, sample_users, sample_session, db):
    """GET /booking/available-sessions returns HTMX fragment."""
    login_as("testcustomer", "TestPass123!")
    # First book so we have a reservation_id
    from app.services.booking_service import create_reservation
    result = create_reservation(sample_users["customer"].id, sample_session.id)
    reservation_id = result["reservation_id"]

    date_str = sample_session.start_time.strftime("%m/%d/%Y")
    resp = client.get(
        f"/booking/available-sessions?reservation_id={reservation_id}&date={date_str}"
    )
    assert resp.status_code == 200
