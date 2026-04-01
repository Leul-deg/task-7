"""
Data retention service — monthly aggregation and raw event pruning.

CLI command: flask data-cleanup
  1. Aggregate raw AnalyticsEvent records older than 90 days into
     MonthlyAnalyticsSummary rows (upsert).
  2. Delete raw AnalyticsEvent records older than 90 days.
  3. Delete MonthlyAnalyticsSummary records older than 13 months.
"""
import calendar
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import click
from flask import Flask
from sqlalchemy import func, distinct

from app.extensions import db
from app.models.analytics import AnalyticsEvent, MonthlyAnalyticsSummary
from app.models.review import Review
from app.models.studio import Reservation

logger = logging.getLogger(__name__)

_RAW_RETENTION_DAYS = 90
_SUMMARY_RETENTION_MONTHS = 13


# ── helpers ───────────────────────────────────────────────────────────────────

def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return (start_inclusive, end_exclusive) for the given year/month."""
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


def _heartbeat_dwell_seconds_for_range(start: datetime, end: datetime) -> float:
    """Compute average dwell (heartbeat × 15 s) for the given time window."""
    events = (
        AnalyticsEvent.query
        .filter(
            AnalyticsEvent.event_type == "heartbeat",
            AnalyticsEvent.created_at >= start,
            AnalyticsEvent.created_at < end,
        )
        .all()
    )
    if not events:
        return 0.0

    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        key = ev.session_id or f"anon-{ev.ip_address or ev.id}"
        counts[key] += 1

    dwell_list = [c * 15 for c in counts.values()]
    return round(sum(dwell_list) / len(dwell_list), 2) if dwell_list else 0.0


# ── core: aggregate one calendar month ───────────────────────────────────────

def aggregate_month(year: int, month: int) -> MonthlyAnalyticsSummary:
    """
    Build (or update) a MonthlyAnalyticsSummary for the given year/month.

    Reads raw AnalyticsEvent + Reservation + Review data and upserts the summary.
    """
    start, end = _month_bounds(year, month)

    # Page views
    pv = (
        db.session.query(func.count(AnalyticsEvent.id))
        .filter(
            AnalyticsEvent.event_type == "page_view",
            AnalyticsEvent.created_at >= start,
            AnalyticsEvent.created_at < end,
        )
        .scalar()
    ) or 0

    # Unique visitors (authenticated only — anon sessions counted if session_id exists)
    uv = (
        db.session.query(func.count(distinct(AnalyticsEvent.user_id)))
        .filter(
            AnalyticsEvent.event_type == "page_view",
            AnalyticsEvent.created_at >= start,
            AnalyticsEvent.created_at < end,
            AnalyticsEvent.user_id.isnot(None),
        )
        .scalar()
    ) or 0

    # Bookings created this month
    total_bookings = (
        db.session.query(func.count(Reservation.id))
        .filter(Reservation.created_at >= start, Reservation.created_at < end)
        .scalar()
    ) or 0

    # Cancellations updated this month
    cancellations = (
        db.session.query(func.count(Reservation.id))
        .filter(
            Reservation.status == "canceled",
            Reservation.updated_at >= start,
            Reservation.updated_at < end,
        )
        .scalar()
    ) or 0

    # No-shows updated this month
    no_shows = (
        db.session.query(func.count(Reservation.id))
        .filter(
            Reservation.status == "no_show",
            Reservation.updated_at >= start,
            Reservation.updated_at < end,
        )
        .scalar()
    ) or 0

    avg_dwell = _heartbeat_dwell_seconds_for_range(start, end)

    # Reviews created this month
    reviews = (
        Review.query
        .filter(
            Review.created_at >= start,
            Review.created_at < end,
            Review.status != "removed",
        )
        .all()
    )
    total_reviews = len(reviews)
    avg_rating = (
        round(sum(r.rating for r in reviews) / total_reviews, 2)
        if total_reviews else None
    )

    # Upsert
    summary = MonthlyAnalyticsSummary.query.filter_by(year=year, month=month).first()
    if summary is None:
        summary = MonthlyAnalyticsSummary(year=year, month=month)
        db.session.add(summary)

    summary.total_page_views = pv
    summary.unique_visitors = uv
    summary.total_bookings = total_bookings
    summary.cancellations = cancellations
    summary.no_shows = no_shows
    summary.avg_dwell_seconds = avg_dwell
    summary.total_reviews = total_reviews
    summary.avg_rating = avg_rating
    db.session.commit()

    return summary


# ── core: run cleanup ─────────────────────────────────────────────────────────

def run_data_cleanup() -> dict:
    """
    Full data-retention pass:

    1. Find all calendar months that have raw events older than 90 days.
    2. Aggregate each such month into MonthlyAnalyticsSummary.
    3. Delete raw AnalyticsEvent records older than 90 days.
    4. Delete MonthlyAnalyticsSummary records older than 13 months.

    Returns a summary dict.
    """
    now = datetime.utcnow()
    raw_cutoff = now - timedelta(days=_RAW_RETENTION_DAYS)
    summary_cutoff = now - timedelta(days=_SUMMARY_RETENTION_MONTHS * 30)

    # ── step 1 & 2: aggregate old months ─────────────────────────────────────
    old_events = (
        AnalyticsEvent.query
        .filter(AnalyticsEvent.created_at < raw_cutoff)
        .all()
    )

    # Collect distinct (year, month) pairs
    months_to_aggregate: set[tuple[int, int]] = set()
    for ev in old_events:
        if ev.created_at:
            months_to_aggregate.add((ev.created_at.year, ev.created_at.month))

    aggregated = 0
    for year, month in sorted(months_to_aggregate):
        aggregate_month(year, month)
        aggregated += 1
        logger.info("Aggregated analytics for %d-%02d", year, month)

    # ── step 3: delete old raw events ────────────────────────────────────────
    deleted_events = (
        AnalyticsEvent.query
        .filter(AnalyticsEvent.created_at < raw_cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()

    # ── step 4: delete stale summaries (> 13 months old) ─────────────────────
    deleted_summaries = (
        MonthlyAnalyticsSummary.query
        .filter(MonthlyAnalyticsSummary.updated_at < summary_cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()

    result = {
        "months_aggregated": aggregated,
        "events_deleted": deleted_events,
        "summaries_deleted": deleted_summaries,
    }
    logger.info(
        "Data cleanup complete: months_aggregated=%d events_deleted=%d summaries_deleted=%d",
        aggregated, deleted_events, deleted_summaries,
    )
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def register_cleanup_cli(app: Flask) -> None:
    """Register `flask data-cleanup` on the given app."""

    @app.cli.command("data-cleanup")
    @click.option("--dry-run", is_flag=True, help="Show what would be deleted without acting.")
    def data_cleanup_cmd(dry_run: bool):
        """Aggregate old analytics events and prune raw data beyond retention window."""
        now = datetime.utcnow()
        raw_cutoff = now - timedelta(days=_RAW_RETENTION_DAYS)

        pending_events = (
            AnalyticsEvent.query
            .filter(AnalyticsEvent.created_at < raw_cutoff)
            .count()
        )

        if dry_run:
            click.echo(
                f"[DRY RUN] Would aggregate+delete {pending_events} raw events "
                f"older than {raw_cutoff.strftime('%Y-%m-%d')}."
            )
            return

        result = run_data_cleanup()
        click.echo(
            f"Cleanup done — months_aggregated={result['months_aggregated']} "
            f"events_deleted={result['events_deleted']} "
            f"summaries_deleted={result['summaries_deleted']}"
        )
