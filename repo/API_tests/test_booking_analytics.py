"""
API-level tests: booking UI flow emits the three funnel analytics events.

view_schedule   — emitted on full (non-HTMX) GET /schedule
booking_start   — emitted on GET /schedule/sessions/<id> by a customer
booking_complete — emitted on successful POST /booking/reserve
"""
import pytest
from datetime import datetime, timedelta

from app.models.analytics import AnalyticsEvent
from app.models.studio import StudioSession


def _login(client, username="testcustomer", password="TestPass123!"):
    client.post(
        "/auth/login",
        data={"identifier": username, "password": password},
        follow_redirects=True,
    )


def _event_count(db, event_type):
    return AnalyticsEvent.query.filter_by(event_type=event_type).count()


# ── view_schedule ─────────────────────────────────────────────────────────────

class TestViewScheduleEvent:
    def test_full_page_load_emits_event(self, client, db, sample_users, sample_session):
        """GET /schedule (full page) records a view_schedule event."""
        _login(client)
        before = _event_count(db, "view_schedule")
        client.get("/schedule")
        assert _event_count(db, "view_schedule") == before + 1

    def test_htmx_partial_does_not_emit_event(self, client, db, sample_users, sample_session):
        """GET /schedule with HX-Request (HTMX partial) must not double-count."""
        _login(client)
        before = _event_count(db, "view_schedule")
        client.get("/schedule", headers={"HX-Request": "true"})
        assert _event_count(db, "view_schedule") == before

    def test_event_page_field_set(self, client, db, sample_users, sample_session):
        """view_schedule event's page field is '/schedule'."""
        _login(client)
        client.get("/schedule")
        event = AnalyticsEvent.query.filter_by(event_type="view_schedule").first()
        assert event is not None
        assert event.page == "/schedule"


# ── booking_start ─────────────────────────────────────────────────────────────

class TestBookingStartEvent:
    def test_session_detail_emits_booking_start_for_customer(
        self, client, db, sample_users, sample_session
    ):
        """GET /schedule/sessions/<id> by a customer emits booking_start."""
        _login(client)
        before = _event_count(db, "booking_start")
        client.get(f"/schedule/sessions/{sample_session.id}")
        assert _event_count(db, "booking_start") == before + 1

    def test_session_detail_no_event_for_staff(
        self, client, db, sample_users, sample_session
    ):
        """Staff viewing a session detail page must NOT emit booking_start."""
        _login(client, "teststaff")
        before = _event_count(db, "booking_start")
        client.get(f"/schedule/sessions/{sample_session.id}")
        assert _event_count(db, "booking_start") == before

    def test_event_carries_session_id(self, client, db, sample_users, sample_session):
        """booking_start event data includes the session_id."""
        import json
        _login(client)
        client.get(f"/schedule/sessions/{sample_session.id}")
        event = AnalyticsEvent.query.filter_by(event_type="booking_start").first()
        assert event is not None
        data = json.loads(event.data or "{}")
        assert data.get("session_id") == sample_session.id


# ── booking_complete ──────────────────────────────────────────────────────────

class TestBookingCompleteEvent:
    def test_successful_reserve_emits_event(
        self, client, db, sample_users, sample_session
    ):
        """POST /booking/reserve success records a booking_complete event."""
        _login(client)
        before = _event_count(db, "booking_complete")
        client.post("/booking/reserve", data={"session_id": str(sample_session.id)})
        assert _event_count(db, "booking_complete") == before + 1

    def test_failed_reserve_does_not_emit_event(
        self, client, db, sample_users, sample_session
    ):
        """A duplicate booking attempt must not emit booking_complete."""
        _login(client)
        client.post("/booking/reserve", data={"session_id": str(sample_session.id)})
        before = _event_count(db, "booking_complete")
        client.post("/booking/reserve", data={"session_id": str(sample_session.id)})
        assert _event_count(db, "booking_complete") == before

    def test_event_carries_reservation_id(
        self, client, db, sample_users, sample_session
    ):
        """booking_complete event data includes reservation_id."""
        import json
        _login(client)
        client.post("/booking/reserve", data={"session_id": str(sample_session.id)})
        event = AnalyticsEvent.query.filter_by(event_type="booking_complete").first()
        assert event is not None
        data = json.loads(event.data or "{}")
        assert "reservation_id" in data
        assert data.get("session_id") == sample_session.id


# ── Funnel coherence ──────────────────────────────────────────────────────────

class TestFunnelCoherence:
    def test_full_flow_populates_all_three_stages(
        self, client, db, sample_users, sample_session
    ):
        """
        Simulate a complete customer journey and confirm all three funnel
        event types are recorded in the database.
        """
        _login(client)
        client.get("/schedule")                                          # view_schedule
        client.get(f"/schedule/sessions/{sample_session.id}")           # booking_start
        client.post("/booking/reserve",                                  # booking_complete
                    data={"session_id": str(sample_session.id)})

        assert _event_count(db, "view_schedule") >= 1
        assert _event_count(db, "booking_start") >= 1
        assert _event_count(db, "booking_complete") >= 1
