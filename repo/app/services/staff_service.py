"""
Staff business logic layer for StudioOps.

Covers: schedule queries, session rosters, check-ins, no-shows,
resource conflict detection, session CRUD, and pending-approval management.

All functions return structured result dicts; exceptions are reserved for
truly unexpected errors, not control-flow failures.
"""
import json
import logging
from datetime import datetime, timedelta

from app.extensions import db
from app.models.analytics import CreditHistory
from app.models.studio import CheckIn, Reservation, Resource, StudioSession
from app.models.user import User

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt_time(dt: datetime) -> str:
    """12-hour clock string, e.g. '9:00 AM'."""
    return dt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"


def _fmt_date(dt: datetime) -> str:
    """MM/DD/YYYY string."""
    return dt.strftime("%m/%d/%Y")


def _fmt_datetime(dt: datetime) -> str:
    """MM/DD/YYYY HH:MM AM/PM string."""
    return dt.strftime("%m/%d/%Y %I:%M %p")


def _parse_date(date_str: str) -> datetime:
    """Parse MM/DD/YYYY; raise ValueError on bad input."""
    try:
        return datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError:
        raise ValueError(f"Invalid date format '{date_str}'. Use MM/DD/YYYY.")


def _credit_color(score: int) -> str:
    if score >= 70:
        return "green"
    if score >= 50:
        return "yellow"
    return "red"


# ── Function 1 ────────────────────────────────────────────────────────────────

def get_staff_schedule(staff_id: int, start_date: str, end_date: str) -> list[dict]:
    """
    Get all studio sessions assigned to a staff member within a date range.

    Parameters
    ----------
    staff_id : int
        User ID (must have role "staff").
    start_date : str
        Inclusive start in MM/DD/YYYY format.
    end_date : str
        Inclusive end in MM/DD/YYYY format.

    Returns
    -------
    list[dict]
        Each dict: session_id, title, date (MM/DD/YYYY), start_time (12-hr),
        end_time (12-hr), room_name, booked_count, capacity,
        has_resource_warning, is_tight_schedule.
        Sorted by start_time ascending.

    Raises
    ------
    ValueError
        If either date string is not MM/DD/YYYY.
    """
    start_dt = _parse_date(start_date)
    # Include the entire end day by pushing to the start of the following day
    end_dt = _parse_date(end_date).replace(hour=23, minute=59, second=59)

    logger.debug(
        "get_staff_schedule: staff_id=%d %s → %s", staff_id, start_date, end_date
    )

    sessions = (
        StudioSession.query
        .filter(
            StudioSession.instructor_id == staff_id,
            StudioSession.start_time >= start_dt,
            StudioSession.start_time <= end_dt,
            StudioSession.is_active == True,  # noqa: E712
        )
        .order_by(StudioSession.start_time.asc())
        .all()
    )

    rows = []
    for s in sessions:
        booked_count = Reservation.query.filter_by(
            session_id=s.id, status="confirmed"
        ).count()
        availability = check_resource_availability(s.id)
        rows.append({
            "_start_time_dt": s.start_time,
            "_end_time_dt": s.end_time,
            "session_id": s.id,
            "title": s.title,
            "date": _fmt_date(s.start_time),
            "start_time": _fmt_time(s.start_time),
            "end_time": _fmt_time(s.end_time),
            "room_name": s.room.name if s.room else "—",
            "booked_count": booked_count,
            "capacity": s.capacity,
            "has_resource_warning": availability["has_issues"],
            "is_tight_schedule": False,  # filled in the next pass
        })

    # Mark tight schedule: < 15-minute gap between consecutive sessions
    for i in range(len(rows)):
        if i > 0:
            gap = (
                rows[i]["_start_time_dt"] - rows[i - 1]["_end_time_dt"]
            ).total_seconds() / 60
            if gap < 15:
                rows[i]["is_tight_schedule"] = True
                rows[i - 1]["is_tight_schedule"] = True

    # Strip internal datetime keys before returning
    for row in rows:
        row.pop("_start_time_dt")
        row.pop("_end_time_dt")

    logger.info(
        "get_staff_schedule: returned %d sessions for staff %d", len(rows), staff_id
    )
    return rows


# ── Function 2 ────────────────────────────────────────────────────────────────

def get_session_roster(session_id: int) -> dict:
    """
    Get the roster of all confirmed/completed/no-show reservations for a session,
    including check-in status for each attendee.

    Parameters
    ----------
    session_id : int

    Returns
    -------
    dict
        Keys: ``session`` (detail dict), ``roster`` (list of attendee dicts),
        ``summary`` (aggregate counts).

    Raises
    ------
    ValueError
        If session_id is not found.
    """
    session = StudioSession.query.get(session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found.")

    logger.debug("get_session_roster: session_id=%d", session_id)

    reservations = (
        Reservation.query
        .filter(
            Reservation.session_id == session_id,
            Reservation.status.in_(["confirmed", "completed", "no_show"]),
        )
        .order_by(Reservation.created_at.asc())
        .all()
    )

    roster = []
    for res in reservations:
        customer = res.user
        checkin = res.check_in  # one-to-one relationship, may be None

        is_checked_in = checkin is not None
        is_no_show = res.status == "no_show"

        roster.append({
            "reservation_id": res.id,
            "customer_name": customer.username if customer else "—",
            "customer_id": res.user_id,
            "credit_score": customer.credit_score if customer else 0,
            "credit_color": _credit_color(customer.credit_score if customer else 0),
            "booked_at": _fmt_datetime(res.created_at),
            "checked_in": is_checked_in,
            "checked_in_at": _fmt_time(checkin.checked_in_at) if checkin else None,
            "checked_in_by": (
                checkin.staff.username
                if checkin and checkin.staff
                else None
            ),
            "is_no_show": is_no_show,
        })

    total = len(roster)
    checked_in_count = sum(1 for r in roster if r["checked_in"])
    no_show_count = sum(1 for r in roster if r["is_no_show"])
    pending_count = total - checked_in_count - no_show_count

    return {
        "session": {
            "session_id": session.id,
            "title": session.title,
            "date": _fmt_date(session.start_time),
            "start_time": _fmt_time(session.start_time),
            "end_time": _fmt_time(session.end_time),
            "room_name": session.room.name if session.room else "—",
            "instructor_name": (
                session.instructor.username if session.instructor else "—"
            ),
            "capacity": session.capacity,
        },
        "roster": roster,
        "summary": {
            "total": total,
            "checked_in": checked_in_count,
            "no_shows": no_show_count,
            "pending": pending_count,
            "all_resolved": (checked_in_count + no_show_count) == total,
        },
    }


# ── Function 3 ────────────────────────────────────────────────────────────────

def perform_checkin(reservation_id: int, staff_id: int) -> dict:
    """
    Check in a customer for their reservation.

    Steps: verify reservation is confirmed → session has started → not already
    checked in → create CheckIn record → mark reservation completed → award
    credit.

    Parameters
    ----------
    reservation_id : int
    staff_id : int
        The staff member performing the check-in.

    Returns
    -------
    dict
        ``{"success": True, "message": str, "checked_in_at": str}``
        ``{"success": False, "reason": str}``
    """
    logger.info(
        "perform_checkin: reservation_id=%d staff_id=%d", reservation_id, staff_id
    )

    # Step 1 — load reservation
    reservation = Reservation.query.get(reservation_id)
    if reservation is None:
        return {"success": False, "reason": "Reservation not found."}

    # Step 1b — authorization: acting staff must be the session instructor or admin
    acting_user = User.query.get(staff_id)
    if acting_user is None:
        return {"success": False, "reason": "Acting user not found."}
    if acting_user.role != "admin":
        session_check = StudioSession.query.get(reservation.session_id)
        if session_check is None or session_check.instructor_id != staff_id:
            return {
                "success": False,
                "reason": "You are not authorized to check in attendees for this session.",
            }

    # Step 2 — check for existing check-in first (most specific guard)
    existing_checkin = CheckIn.query.filter_by(reservation_id=reservation_id).first()
    if existing_checkin:
        return {"success": False, "reason": "Customer is already checked in."}

    # Step 3 — status guard
    if reservation.status != "confirmed":
        return {
            "success": False,
            "reason": (
                f"Cannot check in a reservation with status '{reservation.status}'."
            ),
        }

    # Step 4 — session must have started
    session = StudioSession.query.get(reservation.session_id)
    if datetime.utcnow() < session.start_time:
        return {
            "success": False,
            "reason": "Cannot check in before the session has started.",
        }

    # Step 5 — create CheckIn record
    checkin = CheckIn(
        reservation_id=reservation_id,
        staff_id=staff_id,
        checked_in_at=datetime.utcnow(),
    )
    db.session.add(checkin)

    # Step 6 — mark reservation completed
    reservation.status = "completed"

    # Step 7/8 — award credit
    credit_entry = CreditHistory(
        user_id=reservation.user_id,
        event_type="on_time",
        points=2,
        reference_id=reservation_id,
        note=f"Checked in for '{session.title}'",
    )
    db.session.add(credit_entry)

    # Step 9 — persist
    db.session.commit()

    logger.info(
        "perform_checkin: reservation %d checked in by staff %d at %s",
        reservation_id, staff_id, checkin.checked_in_at,
    )

    # Step 10 — return
    return {
        "success": True,
        "message": "Customer checked in successfully.",
        "checked_in_at": checkin.checked_in_at.strftime("%I:%M %p").lstrip("0"),
    }


# ── Function 4 ────────────────────────────────────────────────────────────────

def mark_no_show(reservation_id: int, staff_id: int) -> dict:
    """
    Mark a customer as a no-show after the session has ended.

    Parameters
    ----------
    reservation_id : int
    staff_id : int
        The staff member performing the action (used for audit logging).

    Returns
    -------
    dict
        ``{"success": True, "message": str}``
        ``{"success": False, "reason": str}``
    """
    logger.info(
        "mark_no_show: reservation_id=%d staff_id=%d", reservation_id, staff_id
    )

    # Step 1 — load reservation and status guard
    reservation = Reservation.query.get(reservation_id)
    if reservation is None:
        return {"success": False, "reason": "Reservation not found."}

    # Step 1b — authorization: acting staff must be the session instructor or admin
    acting_user = User.query.get(staff_id)
    if acting_user is None:
        return {"success": False, "reason": "Acting user not found."}
    if acting_user.role != "admin":
        session_check = StudioSession.query.get(reservation.session_id)
        if session_check is None or session_check.instructor_id != staff_id:
            return {
                "success": False,
                "reason": "You are not authorized to mark no-shows for this session.",
            }

    if reservation.status != "confirmed":
        return {
            "success": False,
            "reason": (
                f"Cannot mark no-show for a reservation with status "
                f"'{reservation.status}'."
            ),
        }

    # Step 2 — session must have ended
    session = StudioSession.query.get(reservation.session_id)
    if datetime.utcnow() < session.end_time:
        return {
            "success": False,
            "reason": "Cannot mark no-show until the session has ended.",
        }

    # Step 3 — must not be already checked in
    existing_checkin = CheckIn.query.filter_by(reservation_id=reservation_id).first()
    if existing_checkin:
        return {"success": False, "reason": "Customer was already checked in."}

    # Step 4 — update status
    reservation.status = "no_show"

    # Step 5 — record credit penalty
    credit_entry = CreditHistory(
        user_id=reservation.user_id,
        event_type="no_show",
        points=-3,
        reference_id=reservation_id,
        note=f"No-show for '{session.title}'",
    )
    db.session.add(credit_entry)

    # Step 6 — persist
    db.session.commit()

    logger.warning(
        "mark_no_show: reservation %d (user %d) marked no-show by staff %d",
        reservation_id, reservation.user_id, staff_id,
    )

    # Step 7 — return
    return {
        "success": True,
        "message": "Customer marked as no-show. Credit score adjusted.",
    }


# ── Function 5 ────────────────────────────────────────────────────────────────

def check_resource_availability(session_id: int) -> dict:
    """
    Check all resources for a session for overbooking or scheduling conflicts.

    Checks performed:
    - Room: total concurrent bookings vs room capacity.
    - Instructor: other sessions at the same time.
    - Equipment: each piece used across overlapping sessions vs its capacity.

    Parameters
    ----------
    session_id : int

    Returns
    -------
    dict
        ``{"warnings": list, "conflicts": list, "has_issues": bool}``
        Each warning: resource_name, resource_type, current_usage, capacity, severity.
        Each conflict: type, instructor_name, conflicting_session, conflicting_time.
    """
    session = StudioSession.query.get(session_id)
    if session is None:
        return {"warnings": [], "conflicts": [], "has_issues": False}

    warnings = []
    conflicts = []

    # ── Room check ────────────────────────────────────────────────────────────
    room = session.room
    if room:
        # Count confirmed reservations for every session using this room
        # that overlaps with our session's time window.
        overlapping_room_sessions = (
            StudioSession.query
            .filter(
                StudioSession.room_id == room.id,
                StudioSession.is_active == True,  # noqa: E712
                StudioSession.start_time < session.end_time,
                StudioSession.end_time > session.start_time,
            )
            .all()
        )
        total_room_bookings = sum(
            Reservation.query.filter_by(session_id=s.id, status="confirmed").count()
            for s in overlapping_room_sessions
        )

        if total_room_bookings > room.capacity:
            severity = "overbooked"
        elif total_room_bookings == room.capacity:
            severity = "at_capacity"
        else:
            severity = "ok"

        warnings.append({
            "resource_name": room.name,
            "resource_type": "room",
            "current_usage": total_room_bookings,
            "capacity": room.capacity,
            "severity": severity,
        })

    # ── Instructor check ──────────────────────────────────────────────────────
    if session.instructor_id:
        instructor = session.instructor
        conflicting_sessions = (
            StudioSession.query
            .filter(
                StudioSession.instructor_id == session.instructor_id,
                StudioSession.id != session_id,
                StudioSession.is_active == True,  # noqa: E712
                StudioSession.start_time < session.end_time,
                StudioSession.end_time > session.start_time,
            )
            .all()
        )
        for cs in conflicting_sessions:
            conflicts.append({
                "type": "instructor_double_booked",
                "instructor_name": instructor.username if instructor else "—",
                "conflicting_session": cs.title,
                "conflicting_time": (
                    f"{_fmt_time(cs.start_time)} – {_fmt_time(cs.end_time)}"
                    f" on {_fmt_date(cs.start_time)}"
                ),
            })

    # ── Equipment check ───────────────────────────────────────────────────────
    try:
        equipment_ids = json.loads(session.equipment_ids or "[]")
    except (ValueError, TypeError):
        equipment_ids = []

    for eq_id in equipment_ids:
        equipment = Resource.query.get(eq_id)
        if equipment is None:
            continue

        # Find all sessions that overlap AND include this equipment piece
        overlapping_sessions = (
            StudioSession.query
            .filter(
                StudioSession.is_active == True,  # noqa: E712
                StudioSession.start_time < session.end_time,
                StudioSession.end_time > session.start_time,
            )
            .all()
        )

        usage = 0
        for s in overlapping_sessions:
            try:
                s_equipment_ids = json.loads(s.equipment_ids or "[]")
            except (ValueError, TypeError):
                s_equipment_ids = []
            if eq_id in s_equipment_ids:
                usage += 1

        if usage > equipment.capacity:
            severity = "overbooked"
        elif usage == equipment.capacity:
            severity = "at_capacity"
        else:
            severity = "ok"

        warnings.append({
            "resource_name": equipment.name,
            "resource_type": "equipment",
            "current_usage": usage,
            "capacity": equipment.capacity,
            "severity": severity,
        })

    has_issues = bool(conflicts) or any(
        w["severity"] != "ok" for w in warnings
    )

    return {"warnings": warnings, "conflicts": conflicts, "has_issues": has_issues}


# ── Function 6 ────────────────────────────────────────────────────────────────

def get_all_resource_warnings() -> list[dict]:
    """
    Return all resource warnings and conflicts for active sessions in the next
    7 days, sorted by severity (overbooked first) then date.

    Returns
    -------
    list[dict]
        Flat list of warning/conflict dicts enriched with session_title,
        session_date (MM/DD/YYYY), session_time (12-hr).
    """
    now = datetime.utcnow()
    lookahead = now + timedelta(days=7)

    upcoming = (
        StudioSession.query
        .filter(
            StudioSession.is_active == True,  # noqa: E712
            StudioSession.start_time >= now,
            StudioSession.start_time <= lookahead,
        )
        .order_by(StudioSession.start_time.asc())
        .all()
    )

    logger.debug(
        "get_all_resource_warnings: checking %d upcoming sessions", len(upcoming)
    )

    flat = []
    for s in upcoming:
        result = check_resource_availability(s.id)
        session_meta = {
            "session_id": s.id,
            "session_title": s.title,
            "session_date": _fmt_date(s.start_time),
            "session_time": (
                f"{_fmt_time(s.start_time)} – {_fmt_time(s.end_time)}"
            ),
        }

        for warning in result["warnings"]:
            if warning["severity"] != "ok":
                flat.append({**warning, **session_meta})

        for conflict in result["conflicts"]:
            flat.append({**conflict, **session_meta, "severity": "conflict"})

    # Sort: overbooked first, then conflict, then at_capacity; within each bucket by date
    _severity_order = {"overbooked": 0, "conflict": 1, "at_capacity": 2}

    flat.sort(
        key=lambda x: (
            _severity_order.get(x.get("severity", "at_capacity"), 3),
            x.get("session_date", ""),
        )
    )

    return flat


# ── Function 7 ────────────────────────────────────────────────────────────────

def create_studio_session(
    title: str,
    description: str,
    instructor_id: int,
    room_id: int,
    start_time: datetime,
    end_time: datetime,
    capacity: int,
    equipment_ids: list[int] = None,
) -> dict:
    """
    Create a new studio session with full validation.

    Parameters
    ----------
    title : str
    description : str
    instructor_id : int
    room_id : int
    start_time : datetime
    end_time : datetime
    capacity : int
    equipment_ids : list[int], optional

    Returns
    -------
    dict
        ``{"success": True, "session_id": int, "warnings": list}``
        ``{"success": False, "reason": str}``
    """
    logger.info(
        "create_studio_session: title='%s' instructor=%d room=%d",
        title, instructor_id, room_id,
    )

    # ── Validation ────────────────────────────────────────────────────────────
    if not title or not title.strip():
        return {"success": False, "reason": "Title is required."}

    if len(title) > 200:
        return {"success": False, "reason": "Title cannot exceed 200 characters."}

    if end_time <= start_time:
        return {"success": False, "reason": "End time must be after start time."}

    if capacity < 1:
        return {"success": False, "reason": "Capacity must be at least 1."}

    instructor = User.query.get(instructor_id)
    if instructor is None or instructor.role != "staff":
        return {"success": False, "reason": "Instructor must be a staff member."}

    room = Resource.query.get(room_id)
    if room is None or not room.is_active or room.type != "room":
        return {"success": False, "reason": "Room not found or inactive."}

    # ── Create record ─────────────────────────────────────────────────────────
    session = StudioSession(
        title=title.strip(),
        description=description or "",
        instructor_id=instructor_id,
        room_id=room_id,
        start_time=start_time,
        end_time=end_time,
        capacity=capacity,
        equipment_ids=json.dumps(equipment_ids or []),
        is_active=True,
    )
    db.session.add(session)
    db.session.flush()  # obtain session.id before commit for the availability check

    # ── Post-creation resource check (non-blocking) ───────────────────────────
    availability = check_resource_availability(session.id)
    warnings = availability["warnings"] + [
        {"type": c["type"], "detail": c}
        for c in availability["conflicts"]
    ]

    db.session.commit()

    logger.info(
        "create_studio_session: created session %d '%s' (warnings=%d)",
        session.id, session.title, len(warnings),
    )

    return {"success": True, "session_id": session.id, "warnings": warnings}


# ── Function 8 ────────────────────────────────────────────────────────────────

def get_pending_approvals() -> list[dict]:
    """
    Return all reservations currently awaiting staff approval, oldest first.

    Returns
    -------
    list[dict]
        Each dict: reservation_id, customer_name, customer_id, credit_score,
        credit_color, session_title, session_date (MM/DD/YYYY),
        session_time (12-hr start–end), booked_at.
    """
    logger.debug("get_pending_approvals: querying pending reservations")

    pending = (
        Reservation.query
        .filter_by(status="pending_approval")
        .order_by(Reservation.created_at.asc())
        .all()
    )

    result = []
    for res in pending:
        customer = res.user
        session = res.session

        result.append({
            "reservation_id": res.id,
            "customer_name": customer.username if customer else "—",
            "customer_id": res.user_id,
            "credit_score": customer.credit_score if customer else 0,
            "credit_color": _credit_color(customer.credit_score if customer else 0),
            "session_title": session.title if session else "—",
            "session_date": _fmt_date(session.start_time) if session else "—",
            "session_time": (
                f"{_fmt_time(session.start_time)} – {_fmt_time(session.end_time)}"
                if session
                else "—"
            ),
            "booked_at": _fmt_datetime(res.created_at),
        })

    logger.info("get_pending_approvals: %d reservations pending", len(result))
    return result


# ── Function 9 ────────────────────────────────────────────────────────────────

def resolve_approval(reservation_id: int, approved: bool, staff_id: int) -> dict:
    """
    Approve or deny a pending_approval reservation.

    Parameters
    ----------
    reservation_id : int
    approved : bool
        True to confirm the booking; False to cancel it.
    staff_id : int
        The staff member making the decision (for audit logging).

    Returns
    -------
    dict
        ``{"success": True, "message": str}``
        ``{"success": False, "reason": str}``
    """
    logger.info(
        "resolve_approval: reservation_id=%d approved=%s staff_id=%d",
        reservation_id, approved, staff_id,
    )

    reservation = Reservation.query.get(reservation_id)
    if reservation is None:
        return {"success": False, "reason": "Reservation not found."}

    if reservation.status != "pending_approval":
        return {
            "success": False,
            "reason": "This reservation is not pending approval.",
        }

    user = reservation.user

    if approved:
        reservation.status = "confirmed"
        message = f"Booking approved for {user.username if user else 'user'}."
        logger.info(
            "resolve_approval: reservation %d APPROVED by staff %d",
            reservation_id, staff_id,
        )
    else:
        reservation.status = "canceled"
        message = f"Booking denied for {user.username if user else 'user'}."
        logger.info(
            "resolve_approval: reservation %d DENIED by staff %d",
            reservation_id, staff_id,
        )

    db.session.commit()
    return {"success": True, "message": message}
