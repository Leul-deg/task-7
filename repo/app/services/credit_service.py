"""
Credit scoring service — recalculation, dashboard, history, distribution,
and CLI registration.

Event point values (defined by business rules):
  on_time        → +2
  late_cancel    → -1
  no_show        → -3
  dispute_upheld → -5
  (any other)    → as stored in CreditHistory.points

Thresholds:
  Normal     → score >= 70
  At Risk    → 40 <= score < 70
  Restricted → score < 40
"""
import logging
from datetime import datetime, timedelta

import click
from flask import Flask
from sqlalchemy import func

from app.extensions import db
from app.models.analytics import CreditHistory
from app.models.user import User

logger = logging.getLogger(__name__)

# Credit scoring constants
_BASE_SCORE = 100
_SCORE_FLOOR = 0
_SCORE_CAP = 200
_HISTORY_WINDOW_DAYS = 90

# Status thresholds
_THRESHOLD_NORMAL = 70
_THRESHOLD_AT_RISK = 40

# Tailwind color map for badge rendering
_SCORE_COLORS = {
    "Normal":     "bg-emerald-100 text-emerald-700",
    "At Risk":    "bg-amber-100 text-amber-700",
    "Restricted": "bg-red-100 text-red-700",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _status_label(score: int) -> str:
    if score >= _THRESHOLD_NORMAL:
        return "Normal"
    if score >= _THRESHOLD_AT_RISK:
        return "At Risk"
    return "Restricted"


def _fmt_datetime(dt: datetime | None) -> str | None:
    return dt.strftime("%m/%d/%Y %I:%M %p") if dt else None


# ── FUNCTION 1: recalculate_credit ───────────────────────────────────────────

def recalculate_credit(user_id: int) -> int:
    """
    Recompute a user's credit score from history.

    Formula: base(100) + sum(CreditHistory.points in last 90 days)
    Clamped to [0, 200].

    Persists the new score to user.credit_score and returns it.
    """
    cutoff = datetime.utcnow() - timedelta(days=_HISTORY_WINDOW_DAYS)

    total_adjustment = (
        db.session.query(func.sum(CreditHistory.points))
        .filter(
            CreditHistory.user_id == user_id,
            CreditHistory.created_at >= cutoff,
        )
        .scalar()
    ) or 0

    new_score = max(_SCORE_FLOOR, min(_SCORE_CAP, _BASE_SCORE + int(total_adjustment)))

    user = db.session.get(User, user_id)
    if user:
        user.credit_score = new_score
        db.session.commit()
        logger.debug("Credit recalculated: user=%d score=%d", user_id, new_score)

    return new_score


# ── FUNCTION 2: run_nightly_recalculation ────────────────────────────────────

def run_nightly_recalculation() -> dict:
    """
    Recalculate credit scores for every customer account.

    Returns:
        {
            "users_processed": int,
            "avg_score": float,
            "below_threshold": int  (score < _THRESHOLD_AT_RISK)
        }
    """
    customers = User.query.filter_by(role="customer").all()

    scores = []
    for user in customers:
        score = recalculate_credit(user.id)
        scores.append(score)

    users_processed = len(scores)
    avg_score = round(sum(scores) / users_processed, 1) if users_processed else 0.0
    below_threshold = sum(1 for s in scores if s < _THRESHOLD_AT_RISK)

    logger.info(
        "Nightly credit recalculation done: processed=%d avg=%.1f below_threshold=%d",
        users_processed, avg_score, below_threshold,
    )

    return {
        "users_processed": users_processed,
        "avg_score": avg_score,
        "below_threshold": below_threshold,
    }


# ── FUNCTION 3: get_credit_dashboard_data ────────────────────────────────────

def get_credit_dashboard_data(filter_status: str = "all") -> list[dict]:
    """
    Return all customer accounts enriched with credit metadata.

    filter_status: "all" | "Normal" | "At Risk" | "Restricted"

    Each item:
        username, score, color, last_activity (last credit event), status
    """
    customers = User.query.filter_by(role="customer").order_by(User.credit_score.asc()).all()

    # Last activity per user from CreditHistory
    last_activity_rows = (
        db.session.query(
            CreditHistory.user_id,
            func.max(CreditHistory.created_at).label("last_at"),
        )
        .group_by(CreditHistory.user_id)
        .all()
    )
    last_activity_map = {row.user_id: row.last_at for row in last_activity_rows}

    result = []
    for user in customers:
        status = _status_label(user.credit_score)
        if filter_status != "all" and status != filter_status:
            continue

        last_at = last_activity_map.get(user.id)
        result.append({
            "user_id": user.id,
            "username": user.username,
            "score": user.credit_score,
            "color": _SCORE_COLORS.get(status, "bg-stone-100 text-stone-500"),
            "last_activity": _fmt_datetime(last_at),
            "status": status,
        })

    return result


# ── FUNCTION 4: get_credit_history ───────────────────────────────────────────

def get_credit_history(user_id: int) -> list[dict]:
    """
    Return the full credit history for a user, most recent first.

    Each item: event_type, points, note, date (MM/DD/YYYY HH:MM AM/PM),
               reference_id, running_balance (approximate)
    """
    entries = (
        CreditHistory.query
        .filter_by(user_id=user_id)
        .order_by(CreditHistory.created_at.desc())
        .all()
    )

    result = []
    for entry in entries:
        result.append({
            "id": entry.id,
            "event_type": entry.event_type,
            "points": entry.points,
            "note": entry.note,
            "date": _fmt_datetime(entry.created_at),
            "reference_id": entry.reference_id,
        })
    return result


# ── FUNCTION 5: get_credit_distribution ──────────────────────────────────────

def get_credit_distribution() -> dict:
    """
    Count customers per score bracket.

    Brackets: "0-19", "20-49", "50-69", "70-99", "100+"
    """
    brackets = {"0-19": 0, "20-49": 0, "50-69": 0, "70-99": 0, "100+": 0}

    customers = User.query.filter_by(role="customer").all()
    for user in customers:
        s = user.credit_score
        if s <= 19:
            brackets["0-19"] += 1
        elif s <= 49:
            brackets["20-49"] += 1
        elif s <= 69:
            brackets["50-69"] += 1
        elif s <= 99:
            brackets["70-99"] += 1
        else:
            brackets["100+"] += 1

    return brackets


# ── CLI command ───────────────────────────────────────────────────────────────

def register_cli(app: Flask) -> None:
    """Register the `flask credit-recalc` CLI command on the given app."""

    @app.cli.command("credit-recalc")
    @click.option("--verbose", "-v", is_flag=True, help="Print per-user results.")
    def credit_recalc_cmd(verbose: bool):
        """Recalculate credit scores for all customer accounts."""
        click.echo("Running nightly credit recalculation…")

        if verbose:
            customers = User.query.filter_by(role="customer").all()
            for user in customers:
                score = recalculate_credit(user.id)
                status = _status_label(score)
                click.echo(f"  {user.username:<20} {score:>3}  [{status}]")
            result = {
                "users_processed": len(customers),
                "avg_score": round(
                    sum(u.credit_score for u in User.query.filter_by(role="customer").all())
                    / max(len(customers), 1),
                    1,
                ),
                "below_threshold": sum(
                    1 for u in User.query.filter_by(role="customer").all()
                    if u.credit_score < _THRESHOLD_AT_RISK
                ),
            }
        else:
            result = run_nightly_recalculation()

        click.echo(
            f"\nDone — processed={result['users_processed']} "
            f"avg={result['avg_score']} "
            f"below_threshold={result['below_threshold']}"
        )
