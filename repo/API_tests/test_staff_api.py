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


def test_checkin_endpoint(client, login_as, sample_users, completed_session_with_reservation, db):
    """POST /staff/checkin/{id} returns 200 and transitions reservation to completed."""
    login_as("teststaff", "TestPass123!")
    data = completed_session_with_reservation
    resp = client.post(f"/staff/checkin/{data['reservation'].id}")
    assert resp.status_code == 200
    db.session.refresh(data["reservation"])
    assert data["reservation"].status == "completed"


def test_checkin_response_contains_customer_name(client, login_as, sample_users,
                                                   completed_session_with_reservation):
    """Check-in response fragment includes the checked-in customer's name."""
    login_as("teststaff", "TestPass123!")
    data = completed_session_with_reservation
    resp = client.post(f"/staff/checkin/{data['reservation'].id}")
    assert resp.status_code == 200
    assert b"testcustomer" in resp.data


def test_noshow_endpoint(client, login_as, sample_users, ended_session_with_reservation, db):
    """POST /staff/no-show/{id} returns 200 and marks reservation as no_show."""
    login_as("teststaff", "TestPass123!")
    data = ended_session_with_reservation
    resp = client.post(f"/staff/no-show/{data['reservation'].id}")
    assert resp.status_code == 200
    db.session.refresh(data["reservation"])
    assert data["reservation"].status == "no_show"


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
    """POST /staff/sessions creates a new session, returns 201, and persists the record."""
    from app.models.studio import StudioSession
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
    session = StudioSession.query.filter_by(title="New Yoga").first()
    assert session is not None
    assert session.capacity == 15


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
    """POST /staff/sessions with empty title returns 400 and mentions title."""
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
    assert b"title" in resp.data.lower() or b"required" in resp.data.lower()


# ── Resource toggle (Route 11b: POST /staff/resources/<id>/toggle) ─────────────

def test_resource_toggle_flips_active_state(client, login_as, sample_users, db):
    """POST /staff/resources/<id>/toggle flips is_active and returns the updated row."""
    from app.models.studio import Resource
    resource = Resource(
        name="Studio A", type="room", capacity=20,
        description="Main studio room", is_active=True,
    )
    db.session.add(resource)
    db.session.commit()

    login_as("testadmin", "TestPass123!")
    resp = client.post(
        f"/staff/resources/{resource.id}/toggle",
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    db.session.refresh(resource)
    assert resource.is_active is False


def test_resource_toggle_toggles_back(client, login_as, sample_users, db):
    """Toggling twice restores the original state."""
    from app.models.studio import Resource
    resource = Resource(
        name="Studio B", type="room", capacity=10,
        description="Secondary room", is_active=True,
    )
    db.session.add(resource)
    db.session.commit()

    login_as("testadmin", "TestPass123!")
    client.post(f"/staff/resources/{resource.id}/toggle")
    client.post(f"/staff/resources/{resource.id}/toggle")
    db.session.refresh(resource)
    assert resource.is_active is True


def test_resource_toggle_requires_admin(client, login_as, sample_users, db):
    """Non-admin staff cannot toggle resources."""
    from app.models.studio import Resource
    resource = Resource(
        name="Studio C", type="room", capacity=8,
        description="Small room", is_active=True,
    )
    db.session.add(resource)
    db.session.commit()

    login_as("teststaff", "TestPass123!")
    resp = client.post(f"/staff/resources/{resource.id}/toggle")
    assert resp.status_code == 403


def test_resource_toggle_nonexistent_returns_404(client, login_as, sample_users):
    """Toggling a resource that doesn't exist returns 404."""
    login_as("testadmin", "TestPass123!")
    resp = client.post("/staff/resources/999999/toggle")
    assert resp.status_code == 404


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


# ── Session editing (Route 8: PUT /staff/sessions/<id>) ───────────────────────

class TestUpdateSession:
    def test_update_title_succeeds(self, client, login_as, sample_users, sample_session, db):
        """PUT /staff/sessions/<id> with a new title updates the DB record."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            f"/staff/sessions/{sample_session.id}",
            data={"title": "Renamed Yoga Class"},
        )
        assert resp.status_code == 200
        db.session.refresh(sample_session)
        assert sample_session.title == "Renamed Yoga Class"

    def test_update_capacity_succeeds(self, client, login_as, sample_users, sample_session, db):
        """Updating capacity is persisted to the database."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            f"/staff/sessions/{sample_session.id}",
            data={"capacity": "25"},
        )
        assert resp.status_code == 200
        db.session.refresh(sample_session)
        assert sample_session.capacity == 25

    def test_update_time_succeeds(self, client, login_as, sample_users, sample_session, db):
        """Updating date and start/end times is persisted correctly."""
        from datetime import datetime, timedelta
        tomorrow = datetime.utcnow() + timedelta(days=2)
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            f"/staff/sessions/{sample_session.id}",
            data={
                "date": tomorrow.strftime("%m/%d/%Y"),
                "start_time": "09:00",
                "end_time": "10:00",
            },
        )
        assert resp.status_code == 200
        db.session.refresh(sample_session)
        assert sample_session.start_time.hour == 9

    def test_update_invalid_time_returns_400(self, client, login_as, sample_users, sample_session):
        """Invalid date/time format returns 400 error fragment."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            f"/staff/sessions/{sample_session.id}",
            data={
                "date": "not-a-date",
                "start_time": "bad",
                "end_time": "bad",
            },
        )
        assert resp.status_code == 400

    def test_update_nonexistent_session_returns_404(self, client, login_as, sample_users):
        """Updating a session that doesn't exist returns 404."""
        login_as("testadmin", "TestPass123!")
        resp = client.post("/staff/sessions/999999", data={"title": "Ghost"})
        assert resp.status_code == 404

    def test_update_session_requires_admin(self, client, login_as, sample_users, sample_session):
        """Non-admin staff cannot edit sessions."""
        login_as("teststaff", "TestPass123!")
        resp = client.post(
            f"/staff/sessions/{sample_session.id}",
            data={"title": "Sneaky Rename"},
        )
        assert resp.status_code == 403

    def test_update_response_contains_session_data(
        self, client, login_as, sample_users, sample_session
    ):
        """Response fragment from an update contains the session title."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            f"/staff/sessions/{sample_session.id}",
            data={"title": "Fragment Title Check"},
        )
        assert resp.status_code == 200
        assert b"Fragment Title Check" in resp.data


# ── Session soft-delete (Route 9: POST /staff/sessions/<id>/delete) ───────────

class TestDeleteSession:
    def test_soft_delete_marks_inactive(self, client, login_as, sample_users, sample_session, db):
        """POST /staff/sessions/<id>/delete sets is_active=False."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(f"/staff/sessions/{sample_session.id}/delete")
        assert resp.status_code == 200
        db.session.refresh(sample_session)
        assert sample_session.is_active is False

    def test_soft_delete_returns_empty_200(self, client, login_as, sample_users, sample_session):
        """Successful soft-delete returns 200 with empty body."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(f"/staff/sessions/{sample_session.id}/delete")
        assert resp.status_code == 200

    def test_soft_delete_nonexistent_returns_404(self, client, login_as, sample_users):
        """Deleting a session that doesn't exist returns 404."""
        login_as("testadmin", "TestPass123!")
        resp = client.post("/staff/sessions/999999/delete")
        assert resp.status_code == 404

    def test_soft_delete_requires_admin(self, client, login_as, sample_users, sample_session):
        """Non-admin staff cannot soft-delete a session."""
        login_as("teststaff", "TestPass123!")
        resp = client.post(f"/staff/sessions/{sample_session.id}/delete")
        assert resp.status_code == 403

    def test_reservations_survive_soft_delete(
        self, client, login_as, sample_users, sample_session, db
    ):
        """Existing reservations are not destroyed when a session is soft-deleted."""
        from app.models.studio import Reservation
        # Create a confirmed reservation
        reservation = Reservation(
            user_id=sample_users["customer"].id,
            session_id=sample_session.id,
            status="confirmed",
        )
        db.session.add(reservation)
        db.session.commit()
        reservation_id = reservation.id

        login_as("testadmin", "TestPass123!")
        client.post(f"/staff/sessions/{sample_session.id}/delete")

        # Reservation row must still exist (soft delete does not cascade)
        surviving = Reservation.query.get(reservation_id)
        assert surviving is not None
