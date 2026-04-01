"""
API-level tests for staff HTTP endpoints.
All interactions go through the Flask test client.
"""
import pytest
from datetime import datetime, timedelta

from app.models.studio import Reservation, StudioSession, Resource


def test_staff_schedule_requires_staff_role(client, login_as, sample_users):
    """Customer cannot access /staff/schedule — returns 403."""
    login_as("testcustomer", "TestPass123!")
    resp = client.get("/staff/schedule")
    assert resp.status_code == 403


def test_staff_schedule_returns_200(client, login_as, sample_users):
    """Staff can access their schedule."""
    login_as("teststaff", "TestPass123!")
    resp = client.get("/staff/schedule")
    assert resp.status_code == 200


def test_staff_schedule_htmx_returns_fragment(client, login_as, sample_users):
    """HTMX request to /staff/schedule returns a fragment (no DOCTYPE)."""
    login_as("teststaff", "TestPass123!")
    resp = client.get("/staff/schedule", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert b"<!DOCTYPE" not in resp.data


def test_admin_can_access_staff_schedule(client, login_as, sample_users):
    """Admin role can also access the staff schedule."""
    login_as("testadmin", "TestPass123!")
    resp = client.get("/staff/schedule")
    assert resp.status_code == 200


def test_checkin_endpoint(client, login_as, sample_users, completed_session_with_reservation):
    """POST /staff/checkin/{id} returns 200 and updated row."""
    login_as("teststaff", "TestPass123!")
    data = completed_session_with_reservation
    resp = client.post(f"/staff/checkin/{data['reservation'].id}")
    assert resp.status_code == 200


def test_noshow_endpoint(client, login_as, sample_users, ended_session_with_reservation):
    """POST /staff/no-show/{id} returns 200 and updated row."""
    login_as("teststaff", "TestPass123!")
    data = ended_session_with_reservation
    resp = client.post(f"/staff/no-show/{data['reservation'].id}")
    assert resp.status_code == 200


def test_customer_cannot_checkin(client, login_as, sample_users, completed_session_with_reservation):
    """Customer role gets 403 on check-in endpoint."""
    login_as("testcustomer", "TestPass123!")
    data = completed_session_with_reservation
    resp = client.post(f"/staff/checkin/{data['reservation'].id}")
    assert resp.status_code == 403


def test_customer_cannot_no_show(client, login_as, sample_users, ended_session_with_reservation):
    """Customer role gets 403 on no-show endpoint."""
    login_as("testcustomer", "TestPass123!")
    data = ended_session_with_reservation
    resp = client.post(f"/staff/no-show/{data['reservation'].id}")
    assert resp.status_code == 403


def test_create_session_success(client, login_as, sample_users, sample_room, db):
    """POST /staff/sessions creates a new session and returns 201."""
    login_as("testadmin", "TestPass123!")
    tomorrow = datetime.utcnow() + timedelta(days=1)
    resp = client.post("/staff/sessions", data={
        "title": "New Yoga",
        "description": "A new class",
        "instructor_id": str(sample_users["staff"].id),
        "room_id": str(sample_room.id),
        "date": tomorrow.strftime("%m/%d/%Y"),
        "start_time": "10:00",
        "end_time": "11:00",
        "capacity": "15",
    })
    assert resp.status_code == 201


def test_create_session_requires_admin(client, login_as, sample_users, sample_room):
    """Staff (non-admin) cannot create sessions."""
    login_as("teststaff", "TestPass123!")
    tomorrow = datetime.utcnow() + timedelta(days=1)
    resp = client.post("/staff/sessions", data={
        "title": "Unauthorized Yoga",
        "instructor_id": str(sample_users["staff"].id),
        "room_id": str(sample_room.id),
        "date": tomorrow.strftime("%m/%d/%Y"),
        "start_time": "10:00",
        "end_time": "11:00",
        "capacity": "15",
    })
    assert resp.status_code == 403


def test_create_session_invalid_data(client, login_as, sample_users, sample_room):
    """POST /staff/sessions with empty title returns 400."""
    login_as("testadmin", "TestPass123!")
    tomorrow = datetime.utcnow() + timedelta(days=1)
    resp = client.post("/staff/sessions", data={
        "title": "",  # invalid — empty
        "instructor_id": str(sample_users["staff"].id),
        "room_id": str(sample_room.id),
        "date": tomorrow.strftime("%m/%d/%Y"),
        "start_time": "10:00",
        "end_time": "11:00",
        "capacity": "15",
    })
    assert resp.status_code == 400


def test_pending_approvals_page(client, login_as, sample_users):
    """GET /staff/pending-approvals returns 200 for staff."""
    login_as("teststaff", "TestPass123!")
    resp = client.get("/staff/pending-approvals")
    assert resp.status_code == 200


def test_pending_approvals_shows_pending(client, login_as, sample_users, sample_session, db):
    """Pending approval reservation appears on the page."""
    reservation = Reservation(
        user_id=sample_users["customer"].id,
        session_id=sample_session.id,
        status="pending_approval",
    )
    db.session.add(reservation)
    db.session.commit()

    login_as("teststaff", "TestPass123!")
    resp = client.get("/staff/pending-approvals")
    assert resp.status_code == 200
    assert b"testcustomer" in resp.data


def test_approve_endpoint(client, login_as, sample_users, sample_session, db):
    """POST /staff/approve/{id} confirms a pending reservation."""
    reservation = Reservation(
        user_id=sample_users["customer"].id,
        session_id=sample_session.id,
        status="pending_approval",
    )
    db.session.add(reservation)
    db.session.commit()

    login_as("teststaff", "TestPass123!")
    resp = client.post(f"/staff/approve/{reservation.id}")
    assert resp.status_code == 200

    db.session.refresh(reservation)
    assert reservation.status == "confirmed"


def test_deny_endpoint(client, login_as, sample_users, sample_session, db):
    """POST /staff/deny/{id} cancels a pending reservation."""
    reservation = Reservation(
        user_id=sample_users["customer"].id,
        session_id=sample_session.id,
        status="pending_approval",
    )
    db.session.add(reservation)
    db.session.commit()

    login_as("teststaff", "TestPass123!")
    resp = client.post(f"/staff/deny/{reservation.id}")
    assert resp.status_code == 200

    db.session.refresh(reservation)
    assert reservation.status == "canceled"


def test_resource_warnings_page(client, login_as, sample_users):
    """GET /staff/resource-warnings returns 200."""
    login_as("teststaff", "TestPass123!")
    resp = client.get("/staff/resource-warnings")
    assert resp.status_code == 200


def test_resources_page_requires_admin(client, login_as, sample_users):
    """Staff cannot access /staff/resources — admin only."""
    login_as("teststaff", "TestPass123!")
    resp = client.get("/staff/resources")
    assert resp.status_code == 403


def test_resources_page_admin_access(client, login_as, sample_users):
    """Admin can access /staff/resources."""
    login_as("testadmin", "TestPass123!")
    resp = client.get("/staff/resources")
    assert resp.status_code == 200


def test_roster_page_returns_200(client, login_as, sample_users,
                                  completed_session_with_reservation):
    """GET /staff/session/{id}/roster returns 200 for the session's instructor."""
    login_as("teststaff", "TestPass123!")
    data = completed_session_with_reservation
    resp = client.get(f"/staff/session/{data['session'].id}/roster")
    assert resp.status_code == 200


def test_roster_shows_customer_name(client, login_as, sample_users,
                                     completed_session_with_reservation):
    """Roster page lists the booked customer's name."""
    login_as("teststaff", "TestPass123!")
    data = completed_session_with_reservation
    resp = client.get(f"/staff/session/{data['session'].id}/roster")
    assert b"testcustomer" in resp.data


# ── Cross-staff object-level authorization (API-level) ────────────────────────

@pytest.fixture
def other_staff_user(db):
    """Second staff member (not the instructor on any pre-built session)."""
    from app.models.user import User
    from app.services.auth_service import hash_password
    user = User(
        username="otherstaffuser",
        email="otherstaff@test.com",
        role="staff",
        credit_score=100,
        password_hash=hash_password("TestPass123!"),
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_checkin_by_non_owner_staff_rejected(
    client, login_as, sample_users, other_staff_user,
    completed_session_with_reservation, db,
):
    """POST /staff/checkin/<id>: staff who does not own the session gets 200 error fragment."""
    login_as("otherstaffuser", "TestPass123!")
    data = completed_session_with_reservation
    resp = client.post(f"/staff/checkin/{data['reservation'].id}")
    # Service returns success=False → blueprint returns error fragment (200 with error HTML)
    # or a non-201 status. The key check: reservation must NOT become completed.
    db.session.refresh(data["reservation"])
    assert data["reservation"].status != "completed"


def test_checkin_by_owner_staff_succeeds(
    client, login_as, sample_users,
    completed_session_with_reservation, db,
):
    """POST /staff/checkin/<id>: the session instructor can check in."""
    login_as("teststaff", "TestPass123!")
    data = completed_session_with_reservation
    resp = client.post(f"/staff/checkin/{data['reservation'].id}")
    assert resp.status_code == 200
    db.session.refresh(data["reservation"])
    assert data["reservation"].status == "completed"


def test_checkin_by_admin_succeeds_for_any_session(
    client, login_as, sample_users,
    completed_session_with_reservation, db,
):
    """POST /staff/checkin/<id>: admin can check in on any session."""
    login_as("testadmin", "TestPass123!")
    data = completed_session_with_reservation
    resp = client.post(f"/staff/checkin/{data['reservation'].id}")
    assert resp.status_code == 200
    db.session.refresh(data["reservation"])
    assert data["reservation"].status == "completed"


def test_noshow_by_non_owner_staff_rejected(
    client, login_as, sample_users, other_staff_user,
    ended_session_with_reservation, db,
):
    """POST /staff/no-show/<id>: staff who does not own the session is rejected."""
    login_as("otherstaffuser", "TestPass123!")
    data = ended_session_with_reservation
    resp = client.post(f"/staff/no-show/{data['reservation'].id}")
    db.session.refresh(data["reservation"])
    assert data["reservation"].status != "no_show"


def test_noshow_by_owner_staff_succeeds(
    client, login_as, sample_users,
    ended_session_with_reservation, db,
):
    """POST /staff/no-show/<id>: the session instructor can mark no-show."""
    login_as("teststaff", "TestPass123!")
    data = ended_session_with_reservation
    resp = client.post(f"/staff/no-show/{data['reservation'].id}")
    assert resp.status_code == 200
    db.session.refresh(data["reservation"])
    assert data["reservation"].status == "no_show"


def test_noshow_by_admin_succeeds_for_any_session(
    client, login_as, sample_users,
    ended_session_with_reservation, db,
):
    """POST /staff/no-show/<id>: admin can mark no-show on any session."""
    login_as("testadmin", "TestPass123!")
    data = ended_session_with_reservation
    resp = client.post(f"/staff/no-show/{data['reservation'].id}")
    assert resp.status_code == 200
    db.session.refresh(data["reservation"])
    assert data["reservation"].status == "no_show"
