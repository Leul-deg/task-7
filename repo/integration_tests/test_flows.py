"""
Integration tests — end-to-end user flows across multiple blueprints.

Flow 1: Full booking flow
  register → login → view schedule → book session → view my bookings → cancel

Flow 2: Review submission flow
  login as customer with completed reservation → submit review → view session reviews

Flow 3: Admin analytics & report export flow
  login as admin → view analytics dashboard → generate CSV/JSON export

Flow 4: Staff check-in & credit flow
  login as staff → check-in customer (session in progress) → view credit dashboard

Flow 5: Admin feature flag lifecycle
  login as admin → create flag → toggle enable → verify enabled → delete flag
"""
import json
import pytest
from datetime import datetime, timedelta

from app.extensions import db
from app.models.studio import CheckIn, StudioSession, Reservation, Resource
from app.models.user import User
from app.models.ops import FeatureFlag
from app.models.review import Review
from app.services.auth_service import hash_password


# ── helpers ────────────────────────────────────────────────────────────────────

def _login(client, username, password="TestPass123!"):
    return client.post(
        "/auth/login",
        data={"identifier": username, "password": password},
        follow_redirects=True,
    )


def _register(client, username, email, password="TestPass123!"):
    """POST to the register route using the fields the form actually expects."""
    return client.post(
        "/auth/register",
        data={
            "username": username,
            "email": email,
            "password": password,
            "confirm": password,          # field name in auth blueprint
        },
        follow_redirects=True,
    )


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def flow_users(db):
    staff = User(username="flowstaff", email="flowstaff@test.com",
                 role="staff", credit_score=100,
                 password_hash=hash_password("TestPass123!"))
    customer = User(username="flowcustomer", email="flowcustomer@test.com",
                    role="customer", credit_score=100,
                    password_hash=hash_password("TestPass123!"))
    admin = User(username="flowadmin", email="flowadmin@test.com",
                 role="admin", credit_score=100,
                 password_hash=hash_password("TestPass123!"))
    db.session.add_all([staff, customer, admin])
    db.session.commit()
    return {"staff": staff, "customer": customer, "admin": admin}


@pytest.fixture
def flow_session(db, flow_users):
    """Upcoming session for booking tests."""
    room = Resource(type="room", name="Integration Room", capacity=10)
    db.session.add(room)
    db.session.flush()
    now = datetime.utcnow()
    sess = StudioSession(
        title="Integration Flow Session",
        instructor_id=flow_users["staff"].id,
        room_id=room.id,
        start_time=now + timedelta(days=2),
        end_time=now + timedelta(days=2, hours=1),
        capacity=10,
        equipment_ids="[]",
        is_active=True,
    )
    db.session.add(sess)
    db.session.commit()
    return {"session": sess, "room": room}


@pytest.fixture
def active_session(db, flow_users):
    """Session that started 30 min ago — valid for staff check-in."""
    room = Resource(type="room", name="Active Room", capacity=10)
    db.session.add(room)
    db.session.flush()
    now = datetime.utcnow()
    sess = StudioSession(
        title="Active Flow Session",
        instructor_id=flow_users["staff"].id,
        room_id=room.id,
        start_time=now - timedelta(minutes=30),
        end_time=now + timedelta(minutes=30),
        capacity=10,
        equipment_ids="[]",
        is_active=True,
    )
    db.session.add(sess)
    db.session.commit()
    return sess


@pytest.fixture
def completed_flow_reservation(db, flow_users):
    """Completed reservation for review tests (session already ended)."""
    room = Resource(type="room", name="Past Room", capacity=10)
    db.session.add(room)
    db.session.flush()
    now = datetime.utcnow()
    past_sess = StudioSession(
        title="Past Flow Session",
        instructor_id=flow_users["staff"].id,
        room_id=room.id,
        start_time=now - timedelta(days=3),
        end_time=now - timedelta(days=3) + timedelta(hours=1),
        capacity=10,
        equipment_ids="[]",
        is_active=True,
    )
    db.session.add(past_sess)
    db.session.flush()
    res = Reservation(
        user_id=flow_users["customer"].id,
        session_id=past_sess.id,
        status="completed",
    )
    db.session.add(res)
    db.session.commit()
    return {"reservation": res, "session": past_sess}


# ════════════════════════════════════════════════════════════════════════════════
# FLOW 1 — Full Booking Flow
# ════════════════════════════════════════════════════════════════════════════════

class TestBookingFlow:
    """register → login → schedule → book → my-bookings → cancel"""

    def test_register_new_user(self, client, db):
        resp = _register(client, "newbooker", "newbooker@test.com")
        assert resp.status_code == 200
        # User must be persisted after a successful registration
        user = User.query.filter_by(username="newbooker").first()
        assert user is not None
        assert user.role == "customer"

    def test_login_redirects_to_schedule(self, client, db, flow_users):
        resp = _login(client, "flowcustomer")
        assert resp.status_code == 200
        # Should land somewhere with nav visible (user is authenticated)
        assert b"flowcustomer" in resp.data or b"Schedule" in resp.data

    def test_schedule_page_loads(self, client, db, flow_users, flow_session):
        _login(client, "flowcustomer")
        resp = client.get("/schedule")
        assert resp.status_code == 200
        # Page must contain schedule UI landmarks
        assert b"Schedule" in resp.data or b"Class" in resp.data

    def test_book_session(self, client, db, flow_users, flow_session):
        _login(client, "flowcustomer")
        sess = flow_session["session"]
        resp = client.post(
            "/booking/reserve",
            data={"session_id": sess.id},
            follow_redirects=False,
        )
        # Route returns 201 Created for successful HTMX booking
        assert resp.status_code in (200, 201, 302)
        res = Reservation.query.filter_by(
            user_id=flow_users["customer"].id,
            session_id=sess.id,
        ).first()
        assert res is not None
        assert res.status == "confirmed"

    def test_my_bookings_shows_reservation(self, client, db, flow_users, flow_session):
        _login(client, "flowcustomer")
        client.post("/booking/reserve", data={"session_id": flow_session["session"].id})
        resp = client.get("/booking/my-bookings")
        assert resp.status_code == 200
        assert b"Integration Flow Session" in resp.data

    def test_cancel_reservation(self, client, db, flow_users, flow_session):
        _login(client, "flowcustomer")
        client.post("/booking/reserve", data={"session_id": flow_session["session"].id})
        res = Reservation.query.filter_by(
            user_id=flow_users["customer"].id,
            session_id=flow_session["session"].id,
        ).first()
        assert res is not None
        resp = client.post(f"/booking/{res.id}/cancel", data={}, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(res)
        assert res.status == "canceled"


# ════════════════════════════════════════════════════════════════════════════════
# FLOW 2 — Review Submission Flow
# ════════════════════════════════════════════════════════════════════════════════

class TestReviewFlow:
    """customer with completed reservation → submit review → visible on session page"""

    def test_submit_review_for_completed_reservation(self, client, db, flow_users, completed_flow_reservation):
        _login(client, "flowcustomer")
        res = completed_flow_reservation["reservation"]
        resp = client.post(
            "/reviews",
            data={
                "reservation_id": res.id,
                "rating": "4",
                "text": "Integration test review — great class!",
                "tags": "",
            },
            follow_redirects=False,
        )
        # Route returns 201 for HTMX review submission
        assert resp.status_code in (200, 201)
        rv = Review.query.filter_by(reservation_id=res.id).first()
        assert rv is not None
        assert rv.rating == 4

    def test_session_reviews_visible(self, client, db, flow_users, completed_flow_reservation):
        _login(client, "flowcustomer")
        res = completed_flow_reservation["reservation"]
        client.post(
            "/reviews",
            data={"reservation_id": res.id, "rating": "5",
                  "text": "Visible review text", "tags": ""},
        )
        sess_id = completed_flow_reservation["session"].id
        resp = client.get(f"/reviews/session/{sess_id}")
        assert resp.status_code == 200
        assert b"Visible review text" in resp.data

    def test_my_reviews_page(self, client, db, flow_users):
        _login(client, "flowcustomer")
        resp = client.get("/reviews/my-reviews")
        assert resp.status_code == 200

    def test_cannot_review_without_completed_reservation(self, client, db, flow_users, flow_session):
        """Attempting to review a future/confirmed session should be rejected."""
        _login(client, "flowcustomer")
        client.post("/booking/reserve", data={"session_id": flow_session["session"].id})
        res = Reservation.query.filter_by(
            user_id=flow_users["customer"].id,
            session_id=flow_session["session"].id,
        ).first()
        resp = client.post(
            "/reviews",
            data={"reservation_id": res.id, "rating": "5", "text": "Early review", "tags": ""},
            follow_redirects=False,
        )
        # Must not create a review for a non-completed reservation
        rv = Review.query.filter_by(reservation_id=res.id).first()
        assert rv is None


# ════════════════════════════════════════════════════════════════════════════════
# FLOW 3 — Admin Analytics & Report Export
# ════════════════════════════════════════════════════════════════════════════════

class TestAdminAnalyticsFlow:
    """admin → dashboard → generate CSV/JSON report download"""

    def test_dashboard_accessible(self, client, db, flow_users):
        _login(client, "flowadmin")
        resp = client.get("/admin/dashboard")
        assert resp.status_code == 200
        assert b"Analytics" in resp.data or b"Overview" in resp.data

    def test_report_export_page(self, client, db, flow_users):
        _login(client, "flowadmin")
        resp = client.get("/admin/reports/export")
        assert resp.status_code == 200

    def test_generate_csv_overview(self, client, db, flow_users):
        _login(client, "flowadmin")
        resp = client.post(
            "/admin/reports/generate",
            data={
                "report_type": "overview",
                "format": "csv",
                "start": "01/01/2024",
                "end": "12/31/2024",
            },
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        assert len(resp.data) > 0

    def test_generate_json_trends(self, client, db, flow_users):
        _login(client, "flowadmin")
        resp = client.post(
            "/admin/reports/generate",
            data={
                "report_type": "trends",
                "format": "json",
                "start": "01/01/2024",
                "end": "12/31/2024",
            },
        )
        assert resp.status_code == 200
        assert "application/json" in resp.content_type
        payload = json.loads(resp.data)
        assert isinstance(payload, list)

    def test_non_admin_blocked(self, client, db, flow_users):
        _login(client, "flowcustomer")
        resp = client.get("/admin/dashboard")
        assert resp.status_code in (302, 403)


# ════════════════════════════════════════════════════════════════════════════════
# FLOW 4 — Staff Check-in & Credit Dashboard
# ════════════════════════════════════════════════════════════════════════════════

class TestStaffFlow:
    """staff login → check-in customer on active session → credit dashboard"""

    def test_staff_index_accessible(self, client, db, flow_users):
        _login(client, "flowstaff")
        resp = client.get("/staff/")
        assert resp.status_code in (200, 302)

    def test_staff_checkin_confirmed_reservation(self, client, db, flow_users, active_session):
        """Check-in on a session that started 30 min ago succeeds."""
        res = Reservation(
            user_id=flow_users["customer"].id,
            session_id=active_session.id,
            status="confirmed",
        )
        db.session.add(res)
        db.session.commit()

        _login(client, "flowstaff")
        resp = client.post(
            f"/staff/checkin/{res.id}",
            data={},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        ci = CheckIn.query.filter_by(reservation_id=res.id).first()
        assert ci is not None

    def test_credit_dashboard_visible_to_staff(self, client, db, flow_users):
        _login(client, "flowstaff")
        resp = client.get("/staff/credit-dashboard")
        assert resp.status_code == 200

    def test_customer_blocked_from_credit_dashboard(self, client, db, flow_users):
        _login(client, "flowcustomer")
        resp = client.get("/staff/credit-dashboard")
        assert resp.status_code in (302, 403)

    def test_staff_schedule_loads(self, client, db, flow_users):
        _login(client, "flowstaff")
        resp = client.get("/staff/schedule")
        assert resp.status_code == 200


# ════════════════════════════════════════════════════════════════════════════════
# FLOW 5 — Admin Feature Flag Lifecycle
# ════════════════════════════════════════════════════════════════════════════════

class TestFeatureFlagFlow:
    """admin → create flag → toggle enable → verify → delete"""

    def test_flags_page_accessible(self, client, db, flow_users):
        _login(client, "flowadmin")
        resp = client.get("/admin/flags")
        assert resp.status_code == 200

    def test_create_flag(self, client, db, flow_users):
        _login(client, "flowadmin")
        resp = client.post(
            "/admin/flags",
            data={"name": "integration_test_flag", "description": "Created by integration test"},
            follow_redirects=True,
        )
        assert resp.status_code in (200, 201)
        flag = FeatureFlag.query.filter_by(name="integration_test_flag").first()
        assert flag is not None
        assert flag.is_enabled is False  # off by default

    def test_toggle_flag_enables_it(self, client, db, flow_users):
        _login(client, "flowadmin")
        client.post("/admin/flags",
                    data={"name": "toggle_flow_flag", "description": "toggle test"})
        flag = FeatureFlag.query.filter_by(name="toggle_flow_flag").first()
        assert flag is not None and flag.is_enabled is False

        resp = client.post(f"/admin/flags/{flag.name}/toggle",
                           headers={"HX-Request": "true"})
        assert resp.status_code == 200
        db.session.refresh(flag)
        assert flag.is_enabled is True

    def test_delete_flag(self, client, db, flow_users):
        _login(client, "flowadmin")
        client.post("/admin/flags",
                    data={"name": "delete_flow_flag", "description": "to delete"})
        flag = FeatureFlag.query.filter_by(name="delete_flow_flag").first()
        assert flag is not None

        resp = client.delete(f"/admin/flags/{flag.name}")
        assert resp.status_code == 200
        assert FeatureFlag.query.filter_by(name="delete_flow_flag").first() is None

    def test_non_admin_cannot_create_flag(self, client, db, flow_users):
        _login(client, "flowcustomer")
        resp = client.post(
            "/admin/flags",
            data={"name": "unauthorized_flag"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403)
        assert FeatureFlag.query.filter_by(name="unauthorized_flag").first() is None


# ════════════════════════════════════════════════════════════════════════════════
# FLOW 6 — Content Editorial Workflow
# ════════════════════════════════════════════════════════════════════════════════

class TestContentEditorialFlow:
    """editor creates draft → submits for review → admin publishes → visible publicly"""

    def test_editor_creates_draft(self, client, db, flow_users):
        """Editor can create a new draft article."""
        from app.models.content import Content
        _login(client, "flowadmin")  # admin can also act as editor
        resp = client.post("/content/editor/save", data={
            "title": "Editorial Flow Article",
            "content_type": "article",
            "body": "This article is part of the editorial integration flow.",
            "body_format": "markdown",
            "status": "draft",
        }, follow_redirects=False)
        assert resp.status_code in (200, 302)
        content = Content.query.filter_by(title="Editorial Flow Article").first()
        assert content is not None
        assert content.status == "draft"

    def test_editor_submits_for_review(self, client, db, flow_users):
        """After creating a draft, editor submits it for review."""
        from app.models.content import Content
        from app.models.user import User
        from app.services.auth_service import hash_password

        # Create a dedicated editor for this flow
        editor = User(
            username="flow_editor",
            email="flow_editor@test.com",
            role="editor",
            credit_score=100,
            password_hash=hash_password("TestPass123!"),
        )
        db.session.add(editor)
        db.session.commit()

        _login(client, "flow_editor")
        client.post("/content/editor/save", data={
            "title": "Submit For Review Article",
            "content_type": "article",
            "body": "Body for submit-for-review test.",
            "body_format": "markdown",
            "status": "draft",
        })
        content = Content.query.filter_by(title="Submit For Review Article").first()
        assert content is not None

        resp = client.post(f"/content/{content.id}/submit-review")
        assert resp.status_code == 200
        db.session.refresh(content)
        assert content.status == "in_review"

    def test_admin_publishes_content(self, client, db, flow_users):
        """Admin publishes content that is in_review — it becomes publicly visible."""
        from app.models.content import Content
        from app.models.user import User
        from app.services.auth_service import hash_password

        # Create editor and draft content
        editor = User(
            username="flow_editor2",
            email="flow_editor2@test.com",
            role="editor",
            credit_score=100,
            password_hash=hash_password("TestPass123!"),
        )
        db.session.add(editor)
        db.session.commit()

        _login(client, "flow_editor2")
        client.post("/content/editor/save", data={
            "title": "To Be Published Article",
            "content_type": "article",
            "body": "This article will be published by an admin.",
            "body_format": "markdown",
            "status": "draft",
        })
        content = Content.query.filter_by(title="To Be Published Article").first()
        assert content is not None

        # Editor submits for review
        client.post(f"/content/{content.id}/submit-review")
        db.session.refresh(content)
        assert content.status == "in_review"

        # Log out editor, log in as admin to publish
        client.post("/auth/logout")
        _login(client, "flowadmin")
        resp = client.post(f"/content/{content.id}/publish")
        assert resp.status_code == 200
        db.session.refresh(content)
        assert content.status == "published"

    def test_published_content_visible_publicly(self, client, db, flow_users):
        """Published content appears on the public browse page."""
        from app.models.content import Content
        from app.models.user import User
        from app.services.auth_service import hash_password
        from datetime import datetime

        # Create content and fast-track it to published
        editor = User(
            username="flow_editor3",
            email="flow_editor3@test.com",
            role="editor",
            credit_score=100,
            password_hash=hash_password("TestPass123!"),
        )
        db.session.add(editor)
        db.session.commit()

        _login(client, "flow_editor3")
        client.post("/content/editor/save", data={
            "title": "Publicly Visible Article",
            "content_type": "article",
            "body": "Visible to the public after publishing.",
            "body_format": "markdown",
            "status": "draft",
        })
        content = Content.query.filter_by(title="Publicly Visible Article").first()
        content.status = "published"
        content.published_at = datetime.utcnow()
        db.session.commit()

        # Unauthenticated browse should include the published article
        resp = client.get("/content/")
        assert resp.status_code == 200
        assert b"Publicly Visible Article" in resp.data

    def test_admin_rejects_content_returns_to_draft(self, client, db, flow_users):
        """Admin can reject in_review content — it returns to draft."""
        from app.models.content import Content
        from app.models.user import User
        from app.services.auth_service import hash_password

        editor = User(
            username="flow_editor4",
            email="flow_editor4@test.com",
            role="editor",
            credit_score=100,
            password_hash=hash_password("TestPass123!"),
        )
        db.session.add(editor)
        db.session.commit()

        _login(client, "flow_editor4")
        client.post("/content/editor/save", data={
            "title": "Article To Reject",
            "content_type": "article",
            "body": "This one will be rejected.",
            "body_format": "markdown",
            "status": "draft",
        })
        content = Content.query.filter_by(title="Article To Reject").first()
        client.post(f"/content/{content.id}/submit-review")

        client.post("/auth/logout")
        _login(client, "flowadmin")
        resp = client.post(f"/content/{content.id}/reject",
                           data={"rejection_note": "Needs significant improvements."})
        assert resp.status_code == 200
        db.session.refresh(content)
        assert content.status == "draft"


# ════════════════════════════════════════════════════════════════════════════════
# FLOW 7 — Waitlist Promotion
# ════════════════════════════════════════════════════════════════════════════════

class TestWaitlistPromotionFlow:
    """capacity-1 session: user A books → full; user B joins waitlist;
    user A cancels → user B promoted to confirmed reservation"""

    @pytest.fixture
    def full_session(self, db, flow_users):
        """Create a capacity-1 session and have customer A book it."""
        room = Resource(type="room", name="Tiny Room", capacity=1)
        db.session.add(room)
        db.session.flush()
        now = datetime.utcnow()
        sess = StudioSession(
            title="Waitlist Promo Session",
            instructor_id=flow_users["staff"].id,
            room_id=room.id,
            start_time=now + timedelta(days=3),
            end_time=now + timedelta(days=3, hours=1),
            capacity=1,
            equipment_ids="[]",
            is_active=True,
        )
        db.session.add(sess)
        db.session.commit()
        return sess

    @pytest.fixture
    def waitlist_users(self, db):
        """Two extra customers: user_a books, user_b waits."""
        user_a = User(
            username="waitlist_a",
            email="waitlist_a@test.com",
            role="customer",
            credit_score=100,
            password_hash=hash_password("TestPass123!"),
        )
        user_b = User(
            username="waitlist_b",
            email="waitlist_b@test.com",
            role="customer",
            credit_score=100,
            password_hash=hash_password("TestPass123!"),
        )
        db.session.add_all([user_a, user_b])
        db.session.commit()
        return {"a": user_a, "b": user_b}

    def test_session_full_after_first_booking(self, client, db, flow_users, full_session, waitlist_users):
        """After user A books, the session is at capacity."""
        _login(client, "waitlist_a")
        resp = client.post("/booking/reserve",
                           data={"session_id": full_session.id},
                           follow_redirects=False)
        assert resp.status_code in (200, 201, 302)
        booked = Reservation.query.filter_by(
            user_id=waitlist_users["a"].id,
            session_id=full_session.id,
            status="confirmed",
        ).first()
        assert booked is not None

    def test_user_b_joins_waitlist_when_full(self, client, db, flow_users, full_session, waitlist_users):
        """User B gets placed on the waitlist because the session is full."""
        from app.models.studio import Waitlist

        # User A fills the session
        _login(client, "waitlist_a")
        client.post("/booking/reserve", data={"session_id": full_session.id})
        client.post("/auth/logout")

        # User B tries to join the waitlist (session is now full)
        _login(client, "waitlist_b")
        resp = client.post("/booking/waitlist",
                           data={"session_id": full_session.id})
        assert resp.status_code in (200, 201)
        wl = Waitlist.query.filter_by(
            user_id=waitlist_users["b"].id,
            session_id=full_session.id,
            is_active=True,
        ).first()
        assert wl is not None
        assert wl.position == 1

    def test_waitlist_promoted_on_cancel(self, client, db, flow_users, full_session, waitlist_users):
        """When user A cancels, user B is promoted from waitlist to confirmed."""
        from app.models.studio import Waitlist

        # User A books the session
        _login(client, "waitlist_a")
        client.post("/booking/reserve", data={"session_id": full_session.id})
        res_a = Reservation.query.filter_by(
            user_id=waitlist_users["a"].id,
            session_id=full_session.id,
            status="confirmed",
        ).first()
        assert res_a is not None
        client.post("/auth/logout")

        # User B joins the waitlist
        _login(client, "waitlist_b")
        client.post("/booking/waitlist", data={"session_id": full_session.id})
        wl = Waitlist.query.filter_by(
            user_id=waitlist_users["b"].id,
            session_id=full_session.id,
            is_active=True,
        ).first()
        assert wl is not None
        client.post("/auth/logout")

        # User A cancels — triggers waitlist promotion
        _login(client, "waitlist_a")
        resp = client.post(f"/booking/{res_a.id}/cancel", follow_redirects=True)
        assert resp.status_code == 200

        # User A's reservation should be canceled
        db.session.refresh(res_a)
        assert res_a.status == "canceled"

        # User B's waitlist entry should be deactivated
        db.session.refresh(wl)
        assert wl.is_active is False

        # User B should have a new confirmed reservation
        promoted_res = Reservation.query.filter_by(
            user_id=waitlist_users["b"].id,
            session_id=full_session.id,
            status="confirmed",
        ).first()
        assert promoted_res is not None
