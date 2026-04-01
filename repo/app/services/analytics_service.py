"""
Analytics service — event tracking, dwell time, page metrics, booking funnel,
overview dashboard, booking trends, review summary, content engagement.
"""
import json
import logging
import statistics
from datetime import datetime, timedelta
from collections import defaultdict

from sqlalchemy import func, distinct

from app.extensions import db
from app.models.analytics import AnalyticsEvent, CreditHistory
from app.models.review import Review, Appeal
from app.models.studio import Reservation, Waitlist
from app.models.user import User
from app.models.content import Content

logger = logging.getLogger(__name__)

# Heartbeat interval the client uses (seconds)
_HEARTBEAT_INTERVAL = 15


# ── helpers ────────────────────────────────────────────────────────────────────

def _fmt_date(dt: datetime | None) -> str | None:
    return dt.strftime("%m/%d/%Y") if dt else None


def _apply_date_filter(query, model_column, start_date, end_date):
    if start_date:
        query = query.filter(model_column >= start_date)
    if end_date:
        query = query.filter(model_column <= end_date)
    return query


def _dwell_stats(dwell_seconds_list: list[int]) -> dict:
    """Compute avg / median / max and distribution buckets from a list of dwell values."""
    if not dwell_seconds_list:
        return {
            "avg_dwell_seconds": 0,
            "median_dwell_seconds": 0,
            "max_dwell_seconds": 0,
            "distribution": {"0-30s": 0, "31-60s": 0, "1-5min": 0, "5-15min": 0, "15min+": 0},
        }

    avg = round(sum(dwell_seconds_list) / len(dwell_seconds_list), 1)
    med = round(statistics.median(dwell_seconds_list), 1)
    mx = max(dwell_seconds_list)

    buckets = {"0-30s": 0, "31-60s": 0, "1-5min": 0, "5-15min": 0, "15min+": 0}
    for s in dwell_seconds_list:
        if s <= 30:
            buckets["0-30s"] += 1
        elif s <= 60:
            buckets["31-60s"] += 1
        elif s <= 300:
            buckets["1-5min"] += 1
        elif s <= 900:
            buckets["5-15min"] += 1
        else:
            buckets["15min+"] += 1

    return {
        "avg_dwell_seconds": avg,
        "median_dwell_seconds": med,
        "max_dwell_seconds": mx,
        "distribution": buckets,
    }


def _heartbeat_dwell_per_session(events: list) -> list[int]:
    """Group heartbeat events by session_id, return list of dwell_seconds per session."""
    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        key = ev.session_id or f"anon-{ev.ip_address or ev.id}"
        counts[key] += 1
    return [c * _HEARTBEAT_INTERVAL for c in counts.values()]


# ── FUNCTION 1: track_event ───────────────────────────────────────────────────

def track_event(
    event_type: str,
    page: str = None,
    user_id: int = None,
    session_id: str = None,
    data: dict = None,
    ip_address: str = None,
    user_agent: str = None,
) -> bool:
    """
    Record an analytics event with rate-limiting.

    Rate limits:
      - page_view: same session_id + page within 5 s → skip
      - heartbeat:  same session_id within 14 s         → skip

    Returns True if the event was recorded, False if skipped or on error.
    """
    try:
        now = datetime.utcnow()

        if session_id:
            if event_type == "page_view":
                cutoff = now - timedelta(seconds=5)
                duplicate = (
                    AnalyticsEvent.query
                    .filter(
                        AnalyticsEvent.event_type == "page_view",
                        AnalyticsEvent.session_id == session_id,
                        AnalyticsEvent.page == page,
                        AnalyticsEvent.created_at >= cutoff,
                    )
                    .first()
                )
                if duplicate:
                    logger.debug(
                        "Skipped duplicate page_view: session=%s page=%s", session_id, page
                    )
                    return False

            elif event_type == "heartbeat":
                cutoff = now - timedelta(seconds=14)
                duplicate = (
                    AnalyticsEvent.query
                    .filter(
                        AnalyticsEvent.event_type == "heartbeat",
                        AnalyticsEvent.session_id == session_id,
                        AnalyticsEvent.created_at >= cutoff,
                    )
                    .first()
                )
                if duplicate:
                    logger.debug("Skipped duplicate heartbeat: session=%s", session_id)
                    return False

        event = AnalyticsEvent(
            event_type=event_type,
            page=page[:500] if page else None,
            user_id=user_id,
            session_id=session_id[:100] if session_id else None,
            data=json.dumps(data) if data else "{}",
            ip_address=ip_address[:45] if ip_address else None,
            user_agent=user_agent[:500] if user_agent else None,
        )
        db.session.add(event)
        db.session.commit()
        return True

    except Exception:
        logger.exception("track_event failed: event_type=%s", event_type)
        db.session.rollback()
        return False


# ── FUNCTION 2: compute_dwell_time ────────────────────────────────────────────

def compute_dwell_time(
    page: str = None,
    content_id: int = None,
    start_date: datetime = None,
    end_date: datetime = None,
) -> dict:
    """
    Compute dwell time statistics from heartbeat events.

    Groups heartbeats by browser session_id; dwell = count * 15 s.

    Returns:
        total_visits, avg_dwell_seconds, median_dwell_seconds,
        max_dwell_seconds, distribution (bucketed counts).
    """
    query = AnalyticsEvent.query.filter(AnalyticsEvent.event_type == "heartbeat")

    if page:
        query = query.filter(AnalyticsEvent.page == page)

    if content_id:
        # Match data JSON field: {"content_id": <N>}
        query = query.filter(
            AnalyticsEvent.data.contains(f'"content_id": {content_id}')
        )

    query = _apply_date_filter(query, AnalyticsEvent.created_at, start_date, end_date)

    events = query.all()
    dwell_list = _heartbeat_dwell_per_session(events)
    total_visits = len(dwell_list)

    result = {"total_visits": total_visits}
    result.update(_dwell_stats(dwell_list))
    return result


# ── FUNCTION 3: compute_page_metrics ─────────────────────────────────────────

def compute_page_metrics(
    start_date: datetime = None,
    end_date: datetime = None,
) -> list[dict]:
    """
    Per-page metrics: page views, unique visitors, average dwell time.

    Sorts by page views descending.
    """
    # Page views per page
    pv_query = (
        db.session.query(
            AnalyticsEvent.page,
            func.count(AnalyticsEvent.id).label("pv"),
            func.count(distinct(AnalyticsEvent.user_id)).label("uv"),
        )
        .filter(AnalyticsEvent.event_type == "page_view")
    )
    pv_query = _apply_date_filter(pv_query, AnalyticsEvent.created_at, start_date, end_date)
    pv_rows = pv_query.group_by(AnalyticsEvent.page).all()

    # Heartbeats per page
    hb_query = (
        AnalyticsEvent.query
        .filter(AnalyticsEvent.event_type == "heartbeat")
    )
    hb_query = _apply_date_filter(hb_query, AnalyticsEvent.created_at, start_date, end_date)
    hb_events = hb_query.all()

    # Group heartbeats by page → dwell per session
    hb_by_page: dict[str, list] = defaultdict(list)
    for ev in hb_events:
        if ev.page:
            hb_by_page[ev.page].append(ev)

    metrics = []
    for row in pv_rows:
        page = row.page or "(unknown)"
        dwell_list = _heartbeat_dwell_per_session(hb_by_page.get(page, []))
        avg_dwell = (
            round(sum(dwell_list) / len(dwell_list), 1) if dwell_list else 0
        )
        metrics.append({
            "page": page,
            "page_views": row.pv,
            "unique_visitors": row.uv,
            "avg_dwell_seconds": avg_dwell,
        })

    metrics.sort(key=lambda x: x["page_views"], reverse=True)
    return metrics


# ── FUNCTION 4: compute_booking_funnel ───────────────────────────────────────

def compute_booking_funnel(
    start_date: datetime = None,
    end_date: datetime = None,
) -> dict:
    """
    Count unique users at each funnel stage and calculate conversion rates.

    Funnel stages: view_schedule → booking_start → booking_complete
    """
    def _unique_users(event_type: str) -> int:
        q = (
            db.session.query(func.count(distinct(AnalyticsEvent.user_id)))
            .filter(AnalyticsEvent.event_type == event_type)
        )
        q = _apply_date_filter(q, AnalyticsEvent.created_at, start_date, end_date)
        return q.scalar() or 0

    views = _unique_users("view_schedule")
    starts = _unique_users("booking_start")
    completes = _unique_users("booking_complete")

    view_to_start = round(starts / views * 100, 1) if views else 0.0
    start_to_complete = round(completes / starts * 100, 1) if starts else 0.0
    overall = round(completes / views * 100, 1) if views else 0.0

    return {
        "view_schedule": views,
        "booking_start": starts,
        "booking_complete": completes,
        "view_to_start_pct": view_to_start,
        "start_to_complete_pct": start_to_complete,
        "overall_conversion_pct": overall,
    }


# ── FUNCTION 5: get_overview_metrics ─────────────────────────────────────────

def get_overview_metrics(
    start_date: datetime = None,
    end_date: datetime = None,
) -> dict:
    """
    High-level dashboard numbers for the given date range.

    Returns:
        total_pv, total_uv, total_bookings, avg_dwell,
        cancellation_rate, avg_credit_score
    """
    # Page views / unique visitors
    pv_query = (
        db.session.query(
            func.count(AnalyticsEvent.id),
            func.count(distinct(AnalyticsEvent.user_id)),
        )
        .filter(AnalyticsEvent.event_type == "page_view")
    )
    pv_query = _apply_date_filter(pv_query, AnalyticsEvent.created_at, start_date, end_date)
    pv_row = pv_query.one()
    total_pv = pv_row[0] or 0
    total_uv = pv_row[1] or 0

    # Total bookings (booking_complete events)
    bc_query = (
        db.session.query(func.count(AnalyticsEvent.id))
        .filter(AnalyticsEvent.event_type == "booking_complete")
    )
    bc_query = _apply_date_filter(bc_query, AnalyticsEvent.created_at, start_date, end_date)
    total_bookings = bc_query.scalar() or 0

    # Average dwell time
    hb_query = AnalyticsEvent.query.filter(AnalyticsEvent.event_type == "heartbeat")
    hb_query = _apply_date_filter(hb_query, AnalyticsEvent.created_at, start_date, end_date)
    hb_events = hb_query.all()
    dwell_list = _heartbeat_dwell_per_session(hb_events)
    avg_dwell = round(sum(dwell_list) / len(dwell_list), 1) if dwell_list else 0.0

    # Cancellation rate: canceled / (confirmed + canceled + completed + no_show)
    res_query = db.session.query(Reservation.status, func.count(Reservation.id))
    res_query = _apply_date_filter(res_query, Reservation.created_at, start_date, end_date)
    res_query = res_query.filter(
        Reservation.status.in_(["confirmed", "canceled", "completed", "no_show"])
    )
    status_counts = dict(res_query.group_by(Reservation.status).all())
    total_res = sum(status_counts.values()) or 0
    canceled = status_counts.get("canceled", 0)
    cancellation_rate = round(canceled / total_res * 100, 1) if total_res else 0.0

    # Average credit score across all customers
    avg_score_row = (
        db.session.query(func.avg(User.credit_score))
        .filter(User.role == "customer")
        .scalar()
    )
    avg_credit_score = round(float(avg_score_row), 1) if avg_score_row else 0.0

    return {
        "total_pv": total_pv,
        "total_uv": total_uv,
        "total_bookings": total_bookings,
        "avg_dwell": avg_dwell,
        "cancellation_rate": cancellation_rate,
        "avg_credit_score": avg_credit_score,
    }


# ── FUNCTION 6: get_booking_trends ───────────────────────────────────────────

def get_booking_trends(
    start_date: datetime = None,
    end_date: datetime = None,
) -> list[dict]:
    """
    Daily booking activity for the given range.

    Returns a list of dicts ordered by date ascending:
        date (MM/DD/YYYY), new_bookings, cancellations, no_shows,
        completed, waitlist_joins
    """
    # Fetch all reservations with created_at or updated_at in range
    res_query = Reservation.query
    if start_date:
        res_query = res_query.filter(
            db.or_(Reservation.created_at >= start_date, Reservation.updated_at >= start_date)
        )
    if end_date:
        res_query = res_query.filter(
            db.or_(Reservation.created_at <= end_date, Reservation.updated_at <= end_date)
        )
    reservations = res_query.all()

    # Waitlist joins
    wl_query = Waitlist.query
    wl_query = _apply_date_filter(wl_query, Waitlist.created_at, start_date, end_date)
    waitlist_joins = wl_query.all()

    # Build per-day buckets
    new_bookings: dict[str, int] = defaultdict(int)
    cancellations: dict[str, int] = defaultdict(int)
    no_shows: dict[str, int] = defaultdict(int)
    completed_map: dict[str, int] = defaultdict(int)

    for r in reservations:
        created_day = r.created_at.strftime("%m/%d/%Y") if r.created_at else None
        updated_day = r.updated_at.strftime("%m/%d/%Y") if r.updated_at else None

        if created_day:
            new_bookings[created_day] += 1

        if r.status == "canceled" and updated_day:
            cancellations[updated_day] += 1
        elif r.status == "no_show" and updated_day:
            no_shows[updated_day] += 1
        elif r.status == "completed" and updated_day:
            completed_map[updated_day] += 1

    wl_by_day: dict[str, int] = defaultdict(int)
    for w in waitlist_joins:
        day = w.created_at.strftime("%m/%d/%Y") if w.created_at else None
        if day:
            wl_by_day[day] += 1

    # Collect all days that appear
    all_days: set[str] = (
        set(new_bookings)
        | set(cancellations)
        | set(no_shows)
        | set(completed_map)
        | set(wl_by_day)
    )

    result = []
    for day in sorted(all_days, key=lambda d: datetime.strptime(d, "%m/%d/%Y")):
        result.append({
            "date": day,
            "new_bookings": new_bookings[day],
            "cancellations": cancellations[day],
            "no_shows": no_shows[day],
            "completed": completed_map[day],
            "waitlist_joins": wl_by_day[day],
        })
    return result


# ── FUNCTION 7: get_review_summary ───────────────────────────────────────────

def get_review_summary(
    start_date: datetime = None,
    end_date: datetime = None,
) -> dict:
    """
    Review statistics for the given date range.

    Returns:
        total_reviews, avg_rating, rating_distribution {1..5},
        pending_appeals_count
    """
    rq = Review.query.filter(Review.status != "removed")
    rq = _apply_date_filter(rq, Review.created_at, start_date, end_date)
    reviews = rq.all()

    total = len(reviews)
    avg_rating = round(sum(r.rating for r in reviews) / total, 2) if total else 0.0
    distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in reviews:
        if r.rating in distribution:
            distribution[r.rating] += 1

    pending_appeals = (
        db.session.query(func.count(Appeal.id))
        .filter(Appeal.status == "pending")
        .scalar()
    ) or 0

    return {
        "total_reviews": total,
        "avg_rating": avg_rating,
        "rating_distribution": distribution,
        "pending_appeals_count": pending_appeals,
    }


# ── FUNCTION 8: get_content_engagement ───────────────────────────────────────

def get_content_engagement(
    start_date: datetime = None,
    end_date: datetime = None,
    limit: int = 10,
) -> list[dict]:
    """
    Top content items by page views, with unique visitors, dwell, and avg rating.

    Uses heartbeat events whose `data` JSON includes a `content_id` field.
    """
    # Fetch all heartbeat events in range
    hb_query = AnalyticsEvent.query.filter(AnalyticsEvent.event_type == "heartbeat")
    hb_query = _apply_date_filter(hb_query, AnalyticsEvent.created_at, start_date, end_date)
    hb_events = hb_query.all()

    # Page view events in range
    pv_query = AnalyticsEvent.query.filter(AnalyticsEvent.event_type == "page_view")
    pv_query = _apply_date_filter(pv_query, AnalyticsEvent.created_at, start_date, end_date)
    pv_events = pv_query.all()

    # Extract content_id from heartbeat data JSON
    hb_by_content: dict[int, list] = defaultdict(list)
    for ev in hb_events:
        try:
            d = json.loads(ev.data or "{}")
            cid = d.get("content_id")
            if cid:
                hb_by_content[int(cid)].append(ev)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # PV and UV per page → map back to content id via page URL pattern
    # Pages for content look like /content/<id>
    pv_by_content: dict[int, int] = defaultdict(int)
    uv_by_content: dict[int, set] = defaultdict(set)
    for ev in pv_events:
        if not ev.page:
            continue
        parts = ev.page.rstrip("/").split("/")
        if len(parts) >= 3 and parts[-2] == "content":
            try:
                cid = int(parts[-1])
                pv_by_content[cid] += 1
                if ev.user_id:
                    uv_by_content[cid].add(ev.user_id)
            except (ValueError, IndexError):
                pass
        # Also count by heartbeat content_id association
    for cid in hb_by_content:
        if cid not in pv_by_content:
            pv_by_content[cid] = 0

    if not pv_by_content:
        return []

    # Sort by PV descending, take top N
    top_ids = sorted(pv_by_content, key=lambda c: pv_by_content[c], reverse=True)[:limit]

    # Fetch content objects
    content_map: dict[int, Content] = {
        c.id: c
        for c in Content.query.filter(Content.id.in_(top_ids)).all()
    }

    # Avg rating per content (via reservations → sessions → reviews is indirect;
    # content doesn't directly link to reviews, so use heartbeat page association)
    # We'll leave avg_rating as None unless we can derive it
    result = []
    for cid in top_ids:
        content = content_map.get(cid)
        dwell_list = _heartbeat_dwell_per_session(hb_by_content.get(cid, []))
        avg_dwell = round(sum(dwell_list) / len(dwell_list), 1) if dwell_list else 0.0

        result.append({
            "content_id": cid,
            "title": content.title if content else f"content#{cid}",
            "content_type": content.content_type if content else None,
            "page_views": pv_by_content[cid],
            "unique_visitors": len(uv_by_content.get(cid, set())),
            "avg_dwell_seconds": avg_dwell,
            "avg_rating": None,  # No direct reviews-to-content link in the schema
        })

    return result
