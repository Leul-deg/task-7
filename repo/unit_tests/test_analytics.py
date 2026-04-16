"""
Unit tests for analytics_service and credit_service.

Covers:
  - track_event (rate limiting)
  - compute_dwell_time
  - compute_page_metrics (PV/UV counting)
  - compute_booking_funnel
  - recalculate_credit (base formula, floor, cap, 90-day window)
  - run_data_cleanup
"""
import pytest
from datetime import datetime, timedelta

from app.models.analytics import AnalyticsEvent, CreditHistory, MonthlyAnalyticsSummary
from app.models.studio import Reservation
from app.services.analytics_service import (
    track_event,
    compute_dwell_time,
    compute_page_metrics,
    compute_booking_funnel,
    get_overview_metrics,
    get_review_summary,
    get_content_engagement,
)
from app.services.credit_service import (
    recalculate_credit,
    run_nightly_recalculation,
    get_credit_distribution,
)
from app.services.data_retention_service import run_data_cleanup


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_event(db, event_type, page="/test", session_id="sess1",
                user_id=None, created_at=None):
    ev = AnalyticsEvent(
        event_type=event_type,
        page=page,
        session_id=session_id,
        user_id=user_id,
        data="{}",
    )
    if created_at:
        ev.created_at = created_at
    db.session.add(ev)
    db.session.commit()
    return ev


def _make_credit_history(db, user_id, event_type, points, days_ago=1):
    entry = CreditHistory(
        user_id=user_id,
        event_type=event_type,
        points=points,
        created_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.session.add(entry)
    db.session.commit()
    return entry


# ── TestDwellTimeCalculation ──────────────────────────────────────────────────

class TestDwellTimeCalculation:
    def test_empty_returns_zeros(self, db):
        result = compute_dwell_time()
        assert result["total_visits"] == 0
        assert result["avg_dwell_seconds"] == 0

    def test_single_session_one_heartbeat(self, db):
        _make_event(db, "heartbeat", session_id="s1", page="/content/1")
        result = compute_dwell_time(page="/content/1")
        assert result["total_visits"] == 1
        assert result["avg_dwell_seconds"] == 15

    def test_multi_heartbeat_same_session(self, db):
        for _ in range(4):
            _make_event(db, "heartbeat", session_id="s2", page="/content/2")
        result = compute_dwell_time(page="/content/2")
        assert result["total_visits"] == 1
        assert result["avg_dwell_seconds"] == 4 * 15  # 60s

    def test_two_sessions(self, db):
        for _ in range(2):
            _make_event(db, "heartbeat", session_id="sa", page="/content/3")
        for _ in range(4):
            _make_event(db, "heartbeat", session_id="sb", page="/content/3")
        result = compute_dwell_time(page="/content/3")
        assert result["total_visits"] == 2
        # avg of 30s and 60s = 45s
        assert result["avg_dwell_seconds"] == 45.0

    def test_distribution_buckets_present(self, db):
        _make_event(db, "heartbeat", session_id="sd1")
        result = compute_dwell_time()
        assert "distribution" in result
        assert "0-30s" in result["distribution"]
        assert "15min+" in result["distribution"]

    def test_date_filter_excludes_old(self, db):
        old_time = datetime.utcnow() - timedelta(days=10)
        ev = _make_event(db, "heartbeat", session_id="s_old")
        ev.created_at = old_time
        db.session.commit()

        start = datetime.utcnow() - timedelta(days=1)
        result = compute_dwell_time(start_date=start)
        assert result["total_visits"] == 0


# ── TestPVUVCounting ──────────────────────────────────────────────────────────

class TestPVUVCounting:
    def test_pv_counted_per_event(self, db, sample_users):
        for _ in range(3):
            _make_event(db, "page_view", page="/schedule",
                        user_id=sample_users["customer"].id, session_id="p1")
        metrics = compute_page_metrics()
        schedule_row = next((m for m in metrics if m["page"] == "/schedule"), None)
        assert schedule_row is not None
        assert schedule_row["page_views"] == 3

    def test_uv_distinct_users(self, db, sample_users):
        _make_event(db, "page_view", page="/browse", user_id=sample_users["customer"].id, session_id="u1")
        _make_event(db, "page_view", page="/browse", user_id=sample_users["staff"].id, session_id="u2")
        _make_event(db, "page_view", page="/browse", user_id=sample_users["customer"].id, session_id="u1")
        metrics = compute_page_metrics()
        browse_row = next((m for m in metrics if m["page"] == "/browse"), None)
        assert browse_row is not None
        assert browse_row["page_views"] == 3
        assert browse_row["unique_visitors"] == 2

    def test_sorted_by_pv_desc(self, db, sample_users):
        _make_event(db, "page_view", page="/a", session_id="x1")
        _make_event(db, "page_view", page="/b", session_id="x2")
        _make_event(db, "page_view", page="/b", session_id="x3")
        metrics = compute_page_metrics()
        pvs = [m["page_views"] for m in metrics]
        assert pvs == sorted(pvs, reverse=True)


# ── TestFunnelComputation ─────────────────────────────────────────────────────

class TestFunnelComputation:
    def test_empty_funnel(self, db):
        funnel = compute_booking_funnel()
        assert funnel["view_schedule"] == 0
        assert funnel["overall_conversion_pct"] == 0.0

    def test_full_funnel(self, db, sample_users):
        # 3 view, 2 start, 1 complete — all same user
        cid = sample_users["customer"].id
        _make_event(db, "view_schedule", user_id=cid, session_id="f1")
        _make_event(db, "booking_start", user_id=cid, session_id="f1")
        _make_event(db, "booking_complete", user_id=cid, session_id="f1")

        _make_event(db, "view_schedule", user_id=sample_users["staff"].id, session_id="f2")
        _make_event(db, "booking_start", user_id=sample_users["staff"].id, session_id="f2")

        _make_event(db, "view_schedule", user_id=sample_users["admin"].id, session_id="f3")

        funnel = compute_booking_funnel()
        assert funnel["view_schedule"] == 3
        assert funnel["booking_start"] == 2
        assert funnel["booking_complete"] == 1
        assert funnel["overall_conversion_pct"] == round(1 / 3 * 100, 1)


# ── TestCreditRecalculation ───────────────────────────────────────────────────

class TestCreditRecalculation:
    def test_base_100_with_no_history(self, db, sample_users):
        score = recalculate_credit(sample_users["customer"].id)
        assert score == 100

    def test_positive_events_increase_score(self, db, sample_users):
        _make_credit_history(db, sample_users["customer"].id, "on_time", +5)
        _make_credit_history(db, sample_users["customer"].id, "on_time", +5)
        score = recalculate_credit(sample_users["customer"].id)
        assert score == 110

    def test_negative_events_decrease_score(self, db, sample_users):
        _make_credit_history(db, sample_users["customer"].id, "no_show", -20)
        score = recalculate_credit(sample_users["customer"].id)
        assert score == 80

    def test_credit_floor_zero(self, db, sample_users):
        for _ in range(20):
            _make_credit_history(db, sample_users["customer"].id, "no_show", -20)
        score = recalculate_credit(sample_users["customer"].id)
        assert score == 0

    def test_credit_cap_200(self, db, sample_users):
        for _ in range(30):
            _make_credit_history(db, sample_users["customer"].id, "on_time", +10)
        score = recalculate_credit(sample_users["customer"].id)
        assert score == 200

    def test_90_day_window_excludes_old(self, db, sample_users):
        # Old event (95 days ago) should not count
        _make_credit_history(db, sample_users["customer"].id, "no_show", -20, days_ago=95)
        score = recalculate_credit(sample_users["customer"].id)
        assert score == 100  # base, old event excluded

    def test_90_day_window_includes_recent(self, db, sample_users):
        _make_credit_history(db, sample_users["customer"].id, "on_time", +5, days_ago=89)
        score = recalculate_credit(sample_users["customer"].id)
        assert score == 105

    def test_persists_to_user(self, db, sample_users):
        _make_credit_history(db, sample_users["customer"].id, "on_time", +10)
        recalculate_credit(sample_users["customer"].id)
        db.session.refresh(sample_users["customer"])
        assert sample_users["customer"].credit_score == 110

    def test_run_nightly_recalculation(self, db, sample_users):
        result = run_nightly_recalculation()
        assert result["users_processed"] >= 1
        assert "avg_score" in result
        assert "below_threshold" in result

    def test_credit_distribution_brackets(self, db, sample_users):
        # Force customer to 110
        _make_credit_history(db, sample_users["customer"].id, "on_time", +10)
        recalculate_credit(sample_users["customer"].id)
        dist = get_credit_distribution()
        assert "100+" in dist
        assert dist["100+"] >= 1


# ── TestDataCleanup ────────────────────────────────────────────────────────────

class TestDataCleanup:
    def test_deletes_old_events(self, db):
        old = datetime.utcnow() - timedelta(days=95)
        ev = AnalyticsEvent(
            event_type="page_view", page="/old", data="{}",
            created_at=old,
        )
        db.session.add(ev)
        db.session.commit()
        old_id = ev.id

        result = run_data_cleanup()
        assert result["events_deleted"] >= 1
        assert AnalyticsEvent.query.get(old_id) is None

    def test_preserves_recent_events(self, db):
        _make_event(db, "page_view", page="/recent")
        count_before = AnalyticsEvent.query.count()
        run_data_cleanup()
        count_after = AnalyticsEvent.query.count()
        assert count_after == count_before  # nothing deleted

    def test_aggregates_old_month(self, db):
        old = datetime.utcnow() - timedelta(days=95)
        for _ in range(3):
            ev = AnalyticsEvent(event_type="page_view", page="/old2", data="{}", created_at=old)
            db.session.add(ev)
        db.session.commit()

        run_data_cleanup()
        summary = MonthlyAnalyticsSummary.query.filter_by(
            year=old.year, month=old.month
        ).first()
        assert summary is not None
        assert summary.total_page_views >= 3


# ── TestRateLimit ─────────────────────────────────────────────────────────────

class TestRateLimit:
    def test_page_view_dedup_within_5s(self, db):
        r1 = track_event("page_view", page="/sched", session_id="rl1")
        r2 = track_event("page_view", page="/sched", session_id="rl1")
        assert r1 is True
        assert r2 is False  # duplicate within 5s

    def test_different_pages_not_deduped(self, db):
        r1 = track_event("page_view", page="/page-a", session_id="rl2")
        r2 = track_event("page_view", page="/page-b", session_id="rl2")
        assert r1 is True
        assert r2 is True

    def test_heartbeat_dedup_within_14s(self, db):
        r1 = track_event("heartbeat", session_id="rl3")
        r2 = track_event("heartbeat", session_id="rl3")
        assert r1 is True
        assert r2 is False

    def test_no_session_id_not_rate_limited(self, db):
        r1 = track_event("page_view", page="/x", session_id=None)
        r2 = track_event("page_view", page="/x", session_id=None)
        # No session → no dedup check
        assert r1 is True
        assert r2 is True

    def test_other_event_types_not_rate_limited(self, db):
        r1 = track_event("booking_start", session_id="rl4")
        r2 = track_event("booking_start", session_id="rl4")
        assert r1 is True
        assert r2 is True  # only page_view and heartbeat are rate-limited


# ── TestContentEngagement ─────────────────────────────────────────────────────

class TestContentEngagement:
    """Unit tests for analytics_service.get_content_engagement()."""

    def test_empty_returns_empty_list(self, db):
        """No events → empty result list."""
        result = get_content_engagement()
        assert result == []

    def test_page_views_are_counted(self, db, sample_users):
        """Page view events on /content/<id> are counted and returned."""
        from app.models.analytics import AnalyticsEvent
        ev = AnalyticsEvent(
            event_type="page_view",
            page="/content/42",
            user_id=sample_users["customer"].id,
        )
        db.session.add(ev)
        db.session.commit()

        result = get_content_engagement()
        assert len(result) == 1
        assert result[0]["content_id"] == 42
        assert result[0]["page_views"] == 1

    def test_unique_visitors_counted_once_per_user(self, db, sample_users):
        """Multiple PV events from the same user count as one unique visitor."""
        from app.models.analytics import AnalyticsEvent
        for _ in range(3):
            db.session.add(AnalyticsEvent(
                event_type="page_view",
                page="/content/7",
                user_id=sample_users["customer"].id,
            ))
        db.session.commit()

        result = get_content_engagement()
        assert result[0]["unique_visitors"] == 1

    def test_multiple_users_distinct_uvs(self, db, sample_users):
        """Two different users each contribute one unique visitor."""
        from app.models.analytics import AnalyticsEvent
        db.session.add(AnalyticsEvent(
            event_type="page_view", page="/content/9",
            user_id=sample_users["customer"].id,
        ))
        db.session.add(AnalyticsEvent(
            event_type="page_view", page="/content/9",
            user_id=sample_users["staff"].id,
        ))
        db.session.commit()

        result = get_content_engagement()
        assert result[0]["unique_visitors"] == 2

    def test_sorted_by_page_views_descending(self, db, sample_users):
        """Result is sorted by page_views descending."""
        from app.models.analytics import AnalyticsEvent
        # Content 1 gets 3 PVs, content 2 gets 1 PV
        for _ in range(3):
            db.session.add(AnalyticsEvent(
                event_type="page_view", page="/content/1",
                user_id=sample_users["customer"].id,
            ))
        db.session.add(AnalyticsEvent(
            event_type="page_view", page="/content/2",
            user_id=sample_users["customer"].id,
        ))
        db.session.commit()

        result = get_content_engagement()
        assert result[0]["content_id"] == 1
        assert result[1]["content_id"] == 2

    def test_limit_parameter_respected(self, db, sample_users):
        """limit=1 returns only the top-ranked content item."""
        from app.models.analytics import AnalyticsEvent
        for cid in (10, 11, 12):
            db.session.add(AnalyticsEvent(
                event_type="page_view", page=f"/content/{cid}",
                user_id=sample_users["customer"].id,
            ))
        db.session.commit()

        result = get_content_engagement(limit=1)
        assert len(result) == 1

    def test_result_shape_has_required_keys(self, db, sample_users):
        """Each result dict has all expected keys."""
        from app.models.analytics import AnalyticsEvent
        db.session.add(AnalyticsEvent(
            event_type="page_view", page="/content/5",
            user_id=sample_users["customer"].id,
        ))
        db.session.commit()

        result = get_content_engagement()
        item = result[0]
        for key in ("content_id", "title", "content_type", "page_views",
                    "unique_visitors", "avg_dwell_seconds"):
            assert key in item, f"Missing key: {key}"

    def test_non_content_pages_ignored(self, db, sample_users):
        """Page view events that don't match /content/<id> are not counted."""
        from app.models.analytics import AnalyticsEvent
        db.session.add(AnalyticsEvent(
            event_type="page_view", page="/schedule",
            user_id=sample_users["customer"].id,
        ))
        db.session.commit()

        result = get_content_engagement()
        assert result == []
