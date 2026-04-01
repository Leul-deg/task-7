"""
Observability service — request metrics, error logs, slow requests,
system health snapshot, and alert threshold checking.
"""
import logging
import os
import shutil
import statistics
from datetime import datetime, timedelta

from sqlalchemy import func

from app.extensions import db
from app.models.ops import AlertThreshold, LogEntry

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt(dt: datetime | None) -> str | None:
    return dt.strftime("%m/%d/%Y %I:%M %p") if dt else None


def _entry_to_dict(e: LogEntry) -> dict:
    return {
        "id": e.id,
        "level": e.level,
        "source": e.source,
        "message": e.message,
        "endpoint": e.endpoint,
        "method": e.method,
        "status_code": e.status_code,
        "latency_ms": e.latency_ms,
        "user_id": e.user_id,
        "request_id": e.request_id,
        "date": _fmt(e.created_at),
    }


def _latency_list(entries: list[LogEntry]) -> list[float]:
    return [e.latency_ms for e in entries if e.latency_ms is not None]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = max(0, int(len(sorted_values) * pct / 100) - 1)
    return round(sorted_values[idx], 2)


# ── FUNCTION 1: get_request_metrics ──────────────────────────────────────────

def get_request_metrics(hours: int = 24) -> dict:
    """
    Aggregate request statistics from server-side LogEntry rows.

    Returns:
        total_requests, error_count, error_rate, avg_latency_ms,
        p95_latency_ms, p99_latency_ms, window_hours,
        status_distribution {2xx, 3xx, 4xx, 5xx}
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    entries = (
        LogEntry.query
        .filter(LogEntry.source == "server", LogEntry.created_at >= cutoff)
        .all()
    )

    total = len(entries)
    error_count = sum(1 for e in entries if e.status_code and e.status_code >= 500)
    latencies = sorted(_latency_list(entries))

    avg_lat = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)

    status_dist = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    for e in entries:
        if e.status_code is not None:
            bucket = f"{e.status_code // 100}xx"
            if bucket in status_dist:
                status_dist[bucket] += 1

    return {
        "total_requests": total,
        "error_count": error_count,
        "error_rate": round(error_count / total * 100, 2) if total else 0.0,
        "avg_latency_ms": avg_lat,
        "p95_latency_ms": p95,
        "p99_latency_ms": p99,
        "window_hours": hours,
        "status_distribution": status_dist,
    }


# ── FUNCTION 2: get_recent_errors ─────────────────────────────────────────────

def get_recent_errors(limit: int = 50) -> list[dict]:
    """
    Return the most recent ERROR and CRITICAL log entries (server + client).

    Sorted newest-first.
    """
    entries = (
        LogEntry.query
        .filter(LogEntry.level.in_(["ERROR", "CRITICAL"]))
        .order_by(LogEntry.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_entry_to_dict(e) for e in entries]


# ── FUNCTION 3: get_slow_requests ─────────────────────────────────────────────

def get_slow_requests(threshold_ms: float = 1000.0, limit: int = 20) -> list[dict]:
    """
    Return server-side requests whose latency exceeds threshold_ms.

    Sorted by latency descending.
    """
    entries = (
        LogEntry.query
        .filter(
            LogEntry.source == "server",
            LogEntry.latency_ms >= threshold_ms,
        )
        .order_by(LogEntry.latency_ms.desc())
        .limit(limit)
        .all()
    )
    return [_entry_to_dict(e) for e in entries]


# ── FUNCTION 4: get_system_health ────────────────────────────────────────────

def get_system_health() -> dict:
    """
    Return a point-in-time health snapshot.

    Checks:
      - database: can we execute a trivial query?
      - disk_usage: used / total / free bytes for the filesystem the app lives on
      - recent_error_rate: % of 5xx in last 15 minutes
      - avg_latency_ms: mean latency over last 15 minutes
      - overall status: "healthy" | "degraded" | "unhealthy"
    """
    # DB check
    db_status = "connected"
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {exc}"

    # Disk usage (best-effort)
    disk_info = {}
    try:
        from flask import current_app
        root = current_app.root_path
        usage = shutil.disk_usage(root)
        disk_info = {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_pct": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        }
    except Exception:
        disk_info = {"error": "unavailable"}

    # Recent request metrics (15-minute window)
    window_cutoff = datetime.utcnow() - timedelta(minutes=15)
    recent = (
        LogEntry.query
        .filter(LogEntry.source == "server", LogEntry.created_at >= window_cutoff)
        .all()
    )
    recent_total = len(recent)
    recent_errors = sum(1 for e in recent if e.status_code and e.status_code >= 500)
    recent_error_rate = round(recent_errors / recent_total * 100, 2) if recent_total else 0.0
    latencies = _latency_list(recent)
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

    # Determine overall status
    disk_pct = disk_info.get("used_pct", 0.0)
    if db_status != "connected" or recent_error_rate > 10:
        overall = "unhealthy"
    elif recent_error_rate > 2 or avg_latency > 2000 or disk_pct > 90:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "timestamp": datetime.utcnow().strftime("%m/%d/%Y %I:%M %p"),
        "database": db_status,
        "disk": disk_info,
        "recent_error_rate_pct": recent_error_rate,
        "avg_latency_ms": avg_latency,
        "requests_last_15m": recent_total,
    }


# ── FUNCTION 5: check_alerts ─────────────────────────────────────────────────

def check_alerts() -> list[dict]:
    """
    Evaluate all active AlertThreshold records against live metrics.

    Supported metrics:
      "error_rate"   — compare against get_request_metrics().error_rate
      "latency_p99"  — compare against get_request_metrics().p99_latency_ms
      "disk_usage"   — compare against get_system_health().disk.used_pct

    Returns a list of triggered alert dicts.
    """
    thresholds = AlertThreshold.query.filter_by(is_active=True).all()
    if not thresholds:
        return []

    # Lazily compute metrics only once
    _metrics_cache: dict = {}

    def _get(key: str):
        if key not in _metrics_cache:
            if key in ("error_rate", "latency_p99"):
                m = get_request_metrics(hours=1)
                _metrics_cache["error_rate"] = m["error_rate"]
                _metrics_cache["latency_p99"] = m["p99_latency_ms"]
            elif key == "disk_usage":
                h = get_system_health()
                _metrics_cache["disk_usage"] = h.get("disk", {}).get("used_pct", 0.0)
        return _metrics_cache.get(key, 0.0)

    _ops = {
        ">":  lambda a, b: a > b,
        "<":  lambda a, b: a < b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
    }

    triggered = []
    now = datetime.utcnow()

    for t in thresholds:
        metric_name = t.metric
        if metric_name not in ("error_rate", "latency_p99", "disk_usage"):
            continue

        current_val = _get(metric_name)
        op_fn = _ops.get(t.operator)
        if op_fn is None:
            continue

        if op_fn(current_val, t.threshold_value):
            # Update last_triggered
            t.last_triggered = now
            triggered.append({
                "threshold_id": t.id,
                "metric": metric_name,
                "operator": t.operator,
                "threshold_value": t.threshold_value,
                "current_value": current_val,
                "triggered_at": _fmt(now),
            })

    if triggered:
        try:
            db.session.commit()
        except Exception as exc:
            logger.warning("check_alerts: failed to update last_triggered: %s", exc)
            db.session.rollback()

    return triggered
