import json
import logging
from datetime import datetime, timedelta

from flask import Blueprint, abort, redirect, render_template, request, url_for, make_response
from flask_login import current_user

from ..extensions import db
from ..models.studio import Resource, StudioSession
from ..models.user import User
from ..services import staff_service, credit_service
from ..utils.decorators import login_required, role_required

logger = logging.getLogger(__name__)

staff_bp = Blueprint("staff", __name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _error_fragment(message: str, status: int = 400):
    return render_template(
        "partials/error_fragment.html", code=status, message=message
    ), status


def _monday_of_week(dt: datetime) -> datetime:
    """Return midnight on the Monday of the week containing dt."""
    return (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _parse_week_start(raw: str | None) -> datetime:
    """Parse MM/DD/YYYY week_start; default to current Monday."""
    if raw:
        try:
            return datetime.strptime(raw, "%m/%d/%Y")
        except ValueError:
            pass
    return _monday_of_week(datetime.utcnow())


# ── Route 0 — staff root (redirects to schedule) ─────────────────────────────

@staff_bp.route("/")
@login_required
@role_required("staff", "admin")
def index():
    """GET /staff/ — redirect to staff schedule."""
    return redirect(url_for("staff.schedule"))


# ── Route 1 — staff schedule ──────────────────────────────────────────────────

@staff_bp.route("/schedule")
@login_required
@role_required("staff", "admin")
def schedule():
    """GET /staff/schedule — weekly schedule for the logged-in staff member."""
    week_start = _parse_week_start(request.args.get("week_start"))
    week_end = week_start + timedelta(days=6)

    week_start_str = week_start.strftime("%m/%d/%Y")
    week_end_str = week_end.strftime("%m/%d/%Y")
    prev_week = (week_start - timedelta(days=7)).strftime("%m/%d/%Y")
    next_week = (week_start + timedelta(days=7)).strftime("%m/%d/%Y")

    sessions = staff_service.get_staff_schedule(
        current_user.id, week_start_str, week_end_str
    )

    # Group sessions by date string for easy rendering
    days: dict[str, list] = {}
    for i in range(7):
        day_str = (week_start + timedelta(days=i)).strftime("%m/%d/%Y")
        days[day_str] = []
    for s in sessions:
        if s["date"] in days:
            days[s["date"]].append(s)

    ctx = dict(
        sessions=sessions,
        days=days,
        week_start=week_start_str,
        week_end=week_end_str,
        prev_week=prev_week,
        next_week=next_week,
        week_label=(
            f"{week_start.strftime('%b %d, %Y')} – {week_end.strftime('%b %d, %Y')}"
        ),
    )

    if request.headers.get("HX-Request"):
        return render_template("partials/staff/schedule_list.html", **ctx)
    return render_template("staff/schedule.html", **ctx)


# ── Route 2 — session roster ──────────────────────────────────────────────────

@staff_bp.route("/session/<int:session_id>/roster")
@login_required
@role_required("staff", "admin")
def roster(session_id: int):
    """GET /staff/session/<id>/roster — attendee list with check-in status."""
    try:
        roster_data = staff_service.get_session_roster(session_id)
    except ValueError as exc:
        abort(404, str(exc))

    # Ownership check: must be the instructor or an admin
    if (
        current_user.role != "admin"
        and roster_data["session"].get("instructor_name") != current_user.username
    ):
        # Double-check via ORM to be safe
        session_obj = StudioSession.query.get(session_id)
        if session_obj and session_obj.instructor_id != current_user.id:
            abort(403)

    now = datetime.utcnow()
    session_info = roster_data["session"]
    # Parse back to datetime for comparison (we stored as formatted strings)
    session_obj = StudioSession.query.get(session_id)
    session_started = now >= session_obj.start_time if session_obj else False
    session_ended = now >= session_obj.end_time if session_obj else False

    return render_template(
        "staff/roster.html",
        roster_data=roster_data,
        session_started=session_started,
        session_ended=session_ended,
    )


# ── Route 3 — check-in ────────────────────────────────────────────────────────

@staff_bp.route("/checkin/<int:reservation_id>", methods=["POST"])
@login_required
@role_required("staff", "admin")
def checkin(reservation_id: int):
    """POST /staff/checkin/<id> — check in a customer."""
    result = staff_service.perform_checkin(reservation_id, current_user.id)
    if not result["success"]:
        return _error_fragment(result["reason"])

    # Return updated roster row for HTMX outerHTML swap
    from ..models.studio import Reservation, CheckIn
    reservation = Reservation.query.get(reservation_id)
    session_obj = StudioSession.query.get(reservation.session_id)
    now = datetime.utcnow()

    checkin_obj = CheckIn.query.filter_by(reservation_id=reservation_id).first()
    row = _build_roster_row(reservation, checkin_obj, session_obj, now)
    return render_template("partials/staff/roster_row.html", row=row,
                           session_started=True, session_ended=now >= session_obj.end_time)


# ── Route 4 — no-show ────────────────────────────────────────────────────────

@staff_bp.route("/no-show/<int:reservation_id>", methods=["POST"])
@login_required
@role_required("staff", "admin")
def no_show(reservation_id: int):
    """POST /staff/no-show/<id> — mark a customer as no-show."""
    result = staff_service.mark_no_show(reservation_id, current_user.id)
    if not result["success"]:
        return _error_fragment(result["reason"])

    from ..models.studio import Reservation, CheckIn
    reservation = Reservation.query.get(reservation_id)
    session_obj = StudioSession.query.get(reservation.session_id)
    now = datetime.utcnow()

    checkin_obj = CheckIn.query.filter_by(reservation_id=reservation_id).first()
    row = _build_roster_row(reservation, checkin_obj, session_obj, now)
    return render_template("partials/staff/roster_row.html", row=row,
                           session_started=now >= session_obj.start_time,
                           session_ended=True)


def _build_roster_row(reservation, checkin_obj, session_obj, now) -> dict:
    """Build a roster row dict from ORM objects for the roster_row partial."""
    customer = reservation.user
    is_checked_in = checkin_obj is not None
    is_no_show = reservation.status == "no_show"

    def _fmt_time(dt):
        return dt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"

    def _fmt_datetime(dt):
        return dt.strftime("%m/%d/%Y %I:%M %p")

    def _credit_color(score):
        if score >= 70:
            return "green"
        if score >= 50:
            return "yellow"
        return "red"

    return {
        "reservation_id": reservation.id,
        "customer_name": customer.username if customer else "—",
        "customer_id": reservation.user_id,
        "credit_score": customer.credit_score if customer else 0,
        "credit_color": _credit_color(customer.credit_score if customer else 0),
        "booked_at": _fmt_datetime(reservation.created_at),
        "checked_in": is_checked_in,
        "checked_in_at": _fmt_time(checkin_obj.checked_in_at) if checkin_obj else None,
        "checked_in_by": (
            checkin_obj.staff.username if checkin_obj and checkin_obj.staff else None
        ),
        "is_no_show": is_no_show,
    }


# ── Route 5 — resource warnings ───────────────────────────────────────────────

@staff_bp.route("/resource-warnings")
@login_required
@role_required("staff", "admin")
def resource_warnings():
    """GET /staff/resource-warnings — upcoming resource conflicts."""
    warnings = staff_service.get_all_resource_warnings()
    return render_template("staff/resource_warnings.html", warnings=warnings)


# ── Route 6 — list sessions (admin) ──────────────────────────────────────────

@staff_bp.route("/sessions")
@login_required
@role_required("admin")
def sessions():
    """GET /staff/sessions — paginated session list for admins."""
    page = request.args.get("page", 1, type=int)
    pagination = (
        StudioSession.query
        .order_by(StudioSession.start_time.desc())
        .paginate(page=page, per_page=20, error_out=False)
    )
    staff_users = User.query.filter_by(role="staff").all()
    rooms = Resource.query.filter_by(type="room", is_active=True).all()
    equipment = Resource.query.filter_by(type="equipment", is_active=True).all()
    return render_template(
        "staff/sessions.html",
        pagination=pagination,
        staff_users=staff_users,
        rooms=rooms,
        equipment=equipment,
    )


# ── Route 7 — create session (admin) ─────────────────────────────────────────

@staff_bp.route("/sessions", methods=["POST"])
@login_required
@role_required("admin")
def create_session():
    """POST /staff/sessions — create a new studio session."""
    try:
        date_str = request.form.get("date", "").strip()
        start_raw = request.form.get("start_time", "").strip()
        end_raw = request.form.get("end_time", "").strip()
        start_time = datetime.strptime(f"{date_str} {start_raw}", "%m/%d/%Y %H:%M")
        end_time = datetime.strptime(f"{date_str} {end_raw}", "%m/%d/%Y %H:%M")
    except ValueError:
        return _error_fragment("Invalid date or time format.", 400)

    eq_ids = [int(x) for x in request.form.getlist("equipment_ids") if x.isdigit()]

    result = staff_service.create_studio_session(
        title=request.form.get("title", "").strip(),
        description=request.form.get("description", "").strip(),
        instructor_id=request.form.get("instructor_id", type=int) or 0,
        room_id=request.form.get("room_id", type=int) or 0,
        start_time=start_time,
        end_time=end_time,
        capacity=request.form.get("capacity", type=int) or 0,
        equipment_ids=eq_ids,
    )
    if not result["success"]:
        return _error_fragment(result["reason"], 400)

    session_obj = StudioSession.query.get(result["session_id"])
    return render_template(
        "partials/staff/session_row.html",
        session=session_obj,
        warnings=result.get("warnings", []),
    ), 201


# ── Route 8 — update session (admin) ─────────────────────────────────────────

@staff_bp.route("/sessions/<int:session_id>", methods=["PUT", "POST"])
@login_required
@role_required("admin")
def update_session(session_id: int):
    """PUT /staff/sessions/<id> — update session fields."""
    session_obj = StudioSession.query.get_or_404(session_id)

    try:
        date_str = request.form.get("date", "").strip()
        start_raw = request.form.get("start_time", "").strip()
        end_raw = request.form.get("end_time", "").strip()
        if date_str and start_raw and end_raw:
            session_obj.start_time = datetime.strptime(
                f"{date_str} {start_raw}", "%m/%d/%Y %H:%M"
            )
            session_obj.end_time = datetime.strptime(
                f"{date_str} {end_raw}", "%m/%d/%Y %H:%M"
            )
    except ValueError:
        return _error_fragment("Invalid date or time format.", 400)

    title = request.form.get("title", "").strip()
    if title:
        session_obj.title = title
    desc = request.form.get("description")
    if desc is not None:
        session_obj.description = desc
    instructor_id = request.form.get("instructor_id", type=int)
    if instructor_id:
        session_obj.instructor_id = instructor_id
    room_id = request.form.get("room_id", type=int)
    if room_id:
        session_obj.room_id = room_id
    capacity = request.form.get("capacity", type=int)
    if capacity and capacity > 0:
        session_obj.capacity = capacity
    eq_ids = request.form.getlist("equipment_ids")
    if eq_ids is not None:
        session_obj.equipment_ids = json.dumps(
            [int(x) for x in eq_ids if x.isdigit()]
        )

    db.session.commit()
    logger.info("update_session: session %d updated by admin %d", session_id, current_user.id)
    return render_template("partials/staff/session_row.html", session=session_obj, warnings=[])


# ── Route 9 — delete session (admin) ─────────────────────────────────────────

@staff_bp.route("/sessions/<int:session_id>/delete", methods=["POST", "DELETE"])
@login_required
@role_required("admin")
def delete_session(session_id: int):
    """DELETE /staff/sessions/<id> — soft-delete (deactivate) a session."""
    session_obj = StudioSession.query.get_or_404(session_id)
    session_obj.is_active = False
    db.session.commit()
    logger.info("delete_session: session %d deactivated by admin %d", session_id, current_user.id)
    return "", 200


# ── Route 10 — list resources (admin) ────────────────────────────────────────

@staff_bp.route("/resources")
@login_required
@role_required("admin")
def resources():
    """GET /staff/resources — resource management page."""
    all_resources = Resource.query.order_by(Resource.type, Resource.name).all()
    return render_template("staff/resources.html", resources=all_resources)


# ── Route 11 — create resource (admin) ───────────────────────────────────────

@staff_bp.route("/resources", methods=["POST"])
@login_required
@role_required("admin")
def create_resource():
    """POST /staff/resources — create a new resource."""
    name = request.form.get("name", "").strip()
    rtype = request.form.get("type", "").strip()
    capacity = request.form.get("capacity", type=int) or 1
    description = request.form.get("description", "").strip()

    if not name:
        return _error_fragment("Resource name is required.", 400)
    if rtype not in ("room", "instructor", "equipment"):
        return _error_fragment("Type must be room, instructor, or equipment.", 400)

    resource = Resource(
        name=name, type=rtype, capacity=capacity, description=description, is_active=True
    )
    db.session.add(resource)
    db.session.commit()
    logger.info("create_resource: '%s' created by admin %d", name, current_user.id)
    return render_template("partials/staff/resource_row.html", resource=resource), 201


# ── Route 11b — toggle resource active (admin) ───────────────────────────────

@staff_bp.route("/resources/<int:resource_id>/toggle", methods=["POST"])
@login_required
@role_required("admin")
def toggle_resource(resource_id: int):
    """POST /staff/resources/<id>/toggle — flip is_active."""
    resource = Resource.query.get_or_404(resource_id)
    resource.is_active = not resource.is_active
    db.session.commit()
    return render_template("partials/staff/resource_row.html", resource=resource)


# ── Route 12 — pending approvals ─────────────────────────────────────────────

@staff_bp.route("/pending-approvals")
@login_required
@role_required("staff", "admin")
def pending_approvals():
    """GET /staff/pending-approvals — reservations awaiting approval."""
    approvals = staff_service.get_pending_approvals()
    return render_template("staff/pending_approvals.html", approvals=approvals)


# ── Route 13 — approve reservation ───────────────────────────────────────────

@staff_bp.route("/approve/<int:reservation_id>", methods=["POST"])
@login_required
@role_required("staff", "admin")
def approve(reservation_id: int):
    """POST /staff/approve/<id> — approve a pending reservation."""
    result = staff_service.resolve_approval(reservation_id, approved=True,
                                            staff_id=current_user.id)
    if not result["success"]:
        return _error_fragment(result["reason"], 400)
    return render_template(
        "partials/staff/approval_resolved.html",
        message=result["message"],
        approved=True,
    )


# ── Route 14 — deny reservation ──────────────────────────────────────────────

@staff_bp.route("/deny/<int:reservation_id>", methods=["POST"])
@login_required
@role_required("staff", "admin")
def deny(reservation_id: int):
    """POST /staff/deny/<id> — deny a pending reservation."""
    result = staff_service.resolve_approval(reservation_id, approved=False,
                                            staff_id=current_user.id)
    if not result["success"]:
        return _error_fragment(result["reason"], 400)
    return render_template(
        "partials/staff/approval_resolved.html",
        message=result["message"],
        approved=False,
    )


# ── ROUTE 5: GET /staff/credit-dashboard ─────────────────────────────────────

@staff_bp.route("/credit-dashboard")
@login_required
@role_required("staff", "admin")
def credit_dashboard():
    """Credit score overview for all customers."""
    filter_status = request.args.get("filter", "all")
    customers = credit_service.get_credit_dashboard_data(filter_status=filter_status)
    distribution = credit_service.get_credit_distribution()
    return render_template(
        "admin/credit_dashboard.html",
        customers=customers,
        distribution=distribution,
        filter_status=filter_status,
    )


# ── ROUTE 6: GET /staff/credit-dashboard/<user_id> ───────────────────────────

@staff_bp.route("/credit-dashboard/<int:user_id>")
@login_required
@role_required("staff", "admin")
def credit_history(user_id: int):
    """Full credit history for a single customer."""
    from ..models.user import User as _User
    user = _User.query.get_or_404(user_id)
    history = credit_service.get_credit_history(user_id)
    return render_template(
        "admin/credit_history.html",
        user=user,
        history=history,
    )
