"""
Booking blueprint — all booking-related HTTP endpoints.

URL layout (blueprint registered with no prefix so /schedule lives at root):
  GET  /schedule                                  – public schedule browser
  GET  /schedule/sessions/<id>                    – session detail
  GET  /booking/                                  – alias → my-bookings (backward compat)
  GET  /booking/my-bookings                       – user's booking dashboard
  GET  /booking/available-sessions                – HTMX: sessions for reschedule modal
  POST /booking/reserve                           – create reservation
  POST /booking/waitlist                          – join waitlist
  POST /booking/<reservation_id>/cancel           – cancel reservation
  POST /booking/<reservation_id>/reschedule       – reschedule reservation
  POST /booking/waitlist/<waitlist_id>/leave      – leave waitlist

Business logic lives entirely in app/services/booking_service.py.
"""
import json
import logging
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, abort, make_response,
)
from flask_login import current_user

from app.extensions import db
from app.models.studio import StudioSession, Reservation, Resource
from app.models.user import User
from app.services import booking_service, analytics_service
from app.utils.decorators import login_required, role_required

logger = logging.getLogger(__name__)

# No url_prefix — routes carry their full paths explicitly so /schedule lives
# at root while /booking/* routes live under /booking.
booking_bp = Blueprint("booking", __name__)


# ── helpers ────────────────────────────────────────────────────────────────────

def _is_htmx() -> bool:
    return bool(request.headers.get("HX-Request"))


def _track(event_type: str, page: str, data: dict = None) -> None:
    """Fire-and-forget analytics event; never raises."""
    try:
        session_cookie = request.cookies.get("session", "")
        analytics_service.track_event(
            event_type=event_type,
            page=page,
            user_id=current_user.id if current_user.is_authenticated else None,
            session_id=session_cookie[:100] if session_cookie else None,
            data=data or {},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string[:500] if request.user_agent else None,
        )
    except Exception:
        logger.debug("_track: failed to record %s event", event_type, exc_info=True)


def _to_iso(date_mm_dd_yyyy: str) -> str:
    """Convert MM/DD/YYYY → YYYY-MM-DD (ISO) for HTML date input values."""
    try:
        return datetime.strptime(date_mm_dd_yyyy, "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _normalise_date(value: str) -> str | None:
    """Accept either MM/DD/YYYY or YYYY-MM-DD (from HTML date input) and return
    MM/DD/YYYY.  Returns None if the value cannot be parsed."""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return None


def _error_fragment(message: str, code: int = 409):
    """Return a minimal inline error fragment for HTMX targets."""
    return render_template(
        "partials/booking/booking_error.html", message=message
    ), code


# ── Route 1 — schedule ─────────────────────────────────────────────────────────

@booking_bp.route("/schedule")
@login_required
def schedule():
    """
    GET /schedule

    Renders the class schedule for a given date.  Supports HTMX partial
    refresh: when the request carries an HX-Request header only the session
    list fragment is returned so the page does not reload on date navigation.
    """
    today = datetime.utcnow().strftime("%m/%d/%Y")
    raw_date = request.args.get("date", today)

    # Accept both ISO (YYYY-MM-DD from HTML date input) and MM/DD/YYYY formats
    date_str = _normalise_date(raw_date) or today

    instructor_id = request.args.get("instructor_id", type=int, default=None)

    sessions = []
    try:
        sessions = booking_service.get_sessions_for_date(date_str, instructor_id)
    except ValueError as exc:
        logger.warning("schedule: bad date param '%s': %s", date_str, exc)
        flash(str(exc), "error")
        date_str = today
        sessions = booking_service.get_sessions_for_date(date_str)

    # ISO version for the <input type="date"> value attribute
    selected_date_iso = _to_iso(date_str)

    if _is_htmx():
        return render_template(
            "partials/booking/session_list.html",
            sessions=sessions,
            selected_date=date_str,
        )

    _track("view_schedule", "/schedule", {"date": date_str})

    instructors = User.query.filter_by(role="staff", is_active=True).order_by(
        User.username.asc()
    ).all()

    return render_template(
        "booking/schedule.html",
        sessions=sessions,
        selected_date=date_str,
        selected_date_iso=selected_date_iso,
        instructors=instructors,
        selected_instructor_id=instructor_id,
    )


# ── Route 2 — session detail ───────────────────────────────────────────────────

@booking_bp.route("/schedule/sessions/<int:session_id>")
@login_required
def session_detail(session_id: int):
    """
    GET /schedule/sessions/<session_id>

    Full detail view for a single studio session.  Staff and admins also see
    the list of confirmed attendees.
    """
    session = StudioSession.query.get_or_404(session_id)

    instructor = User.query.get(session.instructor_id) if session.instructor_id else None
    room = Resource.query.get(session.room_id) if session.room_id else None

    # Deserialise equipment IDs and resolve to Resource objects
    try:
        equipment_ids = json.loads(session.equipment_ids or "[]")
    except (ValueError, TypeError):
        equipment_ids = []
    equipment = Resource.query.filter(Resource.id.in_(equipment_ids)).all() if equipment_ids else []

    booked_count = Reservation.query.filter_by(
        session_id=session_id, status="confirmed"
    ).count()

    # Check whether the current user already holds a reservation
    user_reservation = Reservation.query.filter_by(
        user_id=current_user.id, session_id=session_id, status="confirmed"
    ).first()

    attendees = None
    if current_user.role in ("staff", "admin"):
        confirmed_reservations = Reservation.query.filter_by(
            session_id=session_id, status="confirmed"
        ).all()
        attendees = [r.user for r in confirmed_reservations if r.user]

    logger.debug("session_detail: session_id=%d viewed by user=%d", session_id, current_user.id)

    if current_user.role == "customer":
        _track("booking_start", f"/schedule/sessions/{session_id}",
               {"session_id": session_id})

    return render_template(
        "booking/session_detail.html",
        session=session,
        instructor=instructor,
        room=room,
        equipment=equipment,
        booked_count=booked_count,
        spots_remaining=max(0, session.capacity - booked_count),
        is_full=(booked_count >= session.capacity),
        user_reservation=user_reservation,
        attendees=attendees,
    )


# ── Route 3 — reserve ──────────────────────────────────────────────────────────

@booking_bp.route("/booking/reserve", methods=["POST"])
@login_required
def reserve():
    """
    POST /booking/reserve

    Creates a reservation for the current user.  Always returns an HTMX
    fragment — the form in the schedule/detail page uses hx-post.
    """
    session_id = request.form.get("session_id", type=int)
    if session_id is None:
        return _error_fragment("Missing session ID.", 400)

    logger.info("reserve: user=%d session=%d", current_user.id, session_id)
    result = booking_service.create_reservation(current_user.id, session_id)

    if result["success"]:
        _track("booking_complete", "/booking/reserve",
               {"session_id": session_id, "reservation_id": result["reservation_id"]})
        return render_template(
            "partials/booking/booking_confirm.html", result=result
        ), 201

    action = result.get("action", "none")

    if action == "waitlist":
        return render_template(
            "partials/booking/waitlist_offer.html",
            session_id=session_id,
            message=result["reason"],
        ), 409

    status_code = 403 if action == "blocked" else 409
    return _error_fragment(result["reason"], status_code)


# ── Route 4 — join waitlist ────────────────────────────────────────────────────

@booking_bp.route("/booking/waitlist", methods=["POST"])
@login_required
def join_waitlist():
    """
    POST /booking/waitlist

    Adds the current user to the waitlist for a full session.
    """
    session_id = request.form.get("session_id", type=int)
    if session_id is None:
        return _error_fragment("Missing session ID.", 400)

    logger.info("join_waitlist: user=%d session=%d", current_user.id, session_id)
    result = booking_service.join_waitlist(current_user.id, session_id)

    if result["success"]:
        return render_template(
            "partials/booking/waitlist_confirm.html",
            position=result["position"],
            message=result["message"],
        ), 201

    return _error_fragment(result["reason"], 409)


# ── Route 5 — cancel ───────────────────────────────────────────────────────────

@booking_bp.route("/booking/<int:reservation_id>/cancel", methods=["POST"])
@login_required
def cancel(reservation_id: int):
    """
    POST /booking/<reservation_id>/cancel

    Cancels a reservation.  Returns an updated booking card fragment so HTMX
    can swap the card in place.
    """
    logger.info("cancel: reservation=%d user=%d", reservation_id, current_user.id)
    result = booking_service.cancel_reservation(reservation_id, current_user.id)

    if result["success"]:
        reservation = Reservation.query.get(reservation_id)
        booking = booking_service.reservation_to_dict(reservation)
        return render_template(
            "partials/booking/booking_card.html",
            booking=booking,
            flash_message=result["message"],
        ), 200

    status_code = 403 if "only cancel your own" in result["reason"] else 400
    return _error_fragment(result["reason"], status_code)


# ── Route 6 — reschedule ───────────────────────────────────────────────────────

@booking_bp.route("/booking/<int:reservation_id>/reschedule", methods=["POST"])
@login_required
def reschedule(reservation_id: int):
    """
    POST /booking/<reservation_id>/reschedule

    Cancels the old reservation and books a new session in one operation.
    """
    new_session_id = request.form.get("new_session_id", type=int)
    if new_session_id is None:
        return _error_fragment("Missing new session ID.", 400)

    logger.info(
        "reschedule: reservation=%d new_session=%d user=%d",
        reservation_id, new_session_id, current_user.id,
    )
    result = booking_service.reschedule_reservation(
        reservation_id, new_session_id, current_user.id
    )

    if result["success"]:
        new_reservation = Reservation.query.get(result["new_reservation_id"])
        new_booking = booking_service.reservation_to_dict(new_reservation)
        resp = make_response(
            render_template(
                "partials/booking/booking_card.html",
                booking=new_booking,
                flash_message=result["message"],
            ),
            200,
        )
        # Tell HTMX to close the reschedule modal after swap
        resp.headers["HX-Trigger"] = "closeRescheduleModal"
        return resp

    status_code = 403 if "only reschedule your own" in result["reason"] else 400
    return _error_fragment(result["reason"], status_code)


# ── Route 7 — my bookings (+ backward-compat alias) ───────────────────────────

@booking_bp.route("/booking/")
@booking_bp.route("/booking/my-bookings")
@login_required
def my_bookings():
    """
    GET /booking/my-bookings   (also aliased at /booking/ for compatibility)

    Renders the user's full booking dashboard grouped by lifecycle state.
    """
    all_bookings = booking_service.get_user_bookings(current_user.id)
    logger.debug("my_bookings: user=%d", current_user.id)

    tab = request.args.get("tab", "upcoming")
    tab_map = {
        "upcoming": all_bookings["upcoming"] + all_bookings["pending"],
        "past": all_bookings["past"] + all_bookings["no_shows"],
        "cancelled": all_bookings["canceled"],
        "waitlisted": all_bookings["waitlist"],
    }
    bookings = tab_map.get(tab, tab_map["upcoming"])

    template = (
        "partials/booking/bookings_tab.html"
        if request.headers.get("HX-Request")
        else "booking/my_bookings.html"
    )
    return render_template(
        template,
        bookings=bookings,
        active_tab=tab,
        upcoming_count=len(all_bookings["upcoming"] + all_bookings["pending"]),
        waitlisted_count=len(all_bookings["waitlist"]),
    )


# ── Route 8 — leave waitlist ───────────────────────────────────────────────────

@booking_bp.route("/booking/waitlist/<int:waitlist_id>/leave", methods=["POST"])
@login_required
def leave_waitlist(waitlist_id: int):
    """
    POST /booking/waitlist/<waitlist_id>/leave

    Removes the current user from the waitlist entry.
    """
    logger.info("leave_waitlist: waitlist_id=%d user=%d", waitlist_id, current_user.id)
    result = booking_service.leave_waitlist(waitlist_id, current_user.id)

    if result["success"]:
        return render_template(
            "partials/booking/waitlist_removed.html",
            message=result["message"],
        ), 200

    status_code = 403 if "only remove yourself" in result["reason"] else 400
    return _error_fragment(result["reason"], status_code)


# ── Route 9 — available sessions (reschedule modal) ───────────────────────────

@booking_bp.route("/booking/available-sessions")
@login_required
def available_sessions():
    """
    GET /booking/available-sessions?date=MM/DD/YYYY&exclude_session_id=<id>

    Returns a fragment listing non-full sessions for a given date, excluding
    the session currently being rescheduled from.  Used by the reschedule modal.
    """
    today = datetime.utcnow().strftime("%m/%d/%Y")
    raw_date = request.args.get("date", today)
    date_str = _normalise_date(raw_date) or today

    # Booking card sends the reservation_id so we can look up which session to exclude
    reservation_id = request.args.get("reservation_id", type=int, default=None)
    exclude_session_id = None
    if reservation_id:
        res = Reservation.query.get(reservation_id)
        if res:
            exclude_session_id = res.session_id

    available_sessions = []
    try:
        all_sessions = booking_service.get_sessions_for_date(date_str)
        available_sessions = [
            s for s in all_sessions
            if not s["is_full"] and s["id"] != exclude_session_id
        ]
    except ValueError as exc:
        logger.warning("available_sessions: bad date '%s': %s", date_str, exc)

    return render_template(
        "partials/booking/available_sessions.html",
        available_sessions=available_sessions,
        selected_date=date_str,
        reservation_id=reservation_id,
    )
