import logging

from flask import Blueprint, render_template, request
from flask_login import current_user

from app.services import analytics_service
from app.utils.decorators import login_required, role_required

logger = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/")
@login_required
@role_required("staff", "admin")
def index():
    return render_template("analytics/index.html")


# ── ROUTE 1: POST /analytics/event ───────────────────────────────────────────

@analytics_bp.route("/event", methods=["POST"])
def track():
    """Public event tracking endpoint. Returns 204 always (fire-and-forget)."""
    event_type = request.form.get("event_type") or request.json.get("event_type", "") if request.is_json else request.form.get("event_type", "")
    page = request.form.get("page") or (request.json.get("page") if request.is_json else None)
    data_raw = request.form.get("data") or (request.json.get("data") if request.is_json else None)

    import json as _json
    extra_data = None
    if data_raw:
        try:
            extra_data = _json.loads(data_raw) if isinstance(data_raw, str) else data_raw
        except (_json.JSONDecodeError, TypeError):
            extra_data = None

    session_cookie = request.cookies.get("session", "")
    user_id = current_user.id if current_user.is_authenticated else None

    analytics_service.track_event(
        event_type=event_type,
        page=page,
        user_id=user_id,
        session_id=session_cookie[:100] if session_cookie else None,
        data=extra_data,
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string[:500] if request.user_agent else None,
    )
    return "", 204


# ── Heartbeat endpoint ────────────────────────────────────────────────────────

@analytics_bp.route("/heartbeat", methods=["POST"])
def heartbeat():
    """POST /analytics/heartbeat — records a 15-second read heartbeat."""
    content_id = request.form.get("content_id", type=int)
    page = request.form.get("page", "")
    session_cookie = request.cookies.get("session", "")

    user_id = current_user.id if current_user.is_authenticated else None

    analytics_service.track_event(
        event_type="heartbeat",
        page=page,
        user_id=user_id,
        session_id=session_cookie[:100] if session_cookie else None,
        data={"content_id": content_id} if content_id else {},
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string[:500] if request.user_agent else None,
    )
    return "", 204
