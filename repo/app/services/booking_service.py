"""
Booking business logic layer for StudioOps.

All route handlers should call these functions rather than touching the ORM
directly. Every function validates its inputs, raises descriptive errors where
appropriate, and returns a structured result dict so the caller can act on the
outcome without inspecting exceptions for control flow.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, or_

from app.extensions import db
from app.models.studio import StudioSession, Reservation, Waitlist, CheckIn
from app.models.analytics import CreditHistory
from app.models.user import User

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt_time(dt: datetime) -> str:
    """Format a datetime to 12-hour time string, e.g. '10:00 AM'."""
    return dt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"


def _fmt_date(dt: datetime) -> str:
    """Format a datetime to MM/DD/YYYY string."""
    return dt.strftime("%m/%d/%Y")


def _fmt_datetime(dt: datetime) -> str:
    """Format a datetime to 'MM/DD/YYYY HH:MM AM/PM'."""
    return dt.strftime("%m/%d/%Y %I:%M %p")


def _reservation_dict(reservation: Reservation) -> dict:
    """
    Convert a Reservation ORM object to the standard booking dict used by
    get_user_bookings().
    """
    session = reservation.session
    instructor = session.instructor
    room = session.room
    now = datetime.utcnow()

    hours_until = (session.start_time - now).total_seconds() / 3600
    can_act = reservation.status == "confirmed" and hours_until > 12

    # Determine whether a review already exists for this reservation
    from app.models.review import Review
    existing_review = Review.query.filter_by(
        reservation_id=reservation.id,
        user_id=reservation.user_id,
    ).first()
    has_review = existing_review is not None
    can_review = reservation.status == "completed" and not has_review

    return {
        "reservation_id": reservation.id,
        "session_id": session.id,
        "session_title": session.title,
        "session_date": _fmt_date(session.start_time),
        "session_start": _fmt_time(session.start_time),
        "session_end": _fmt_time(session.end_time),
        "instructor_name": instructor.username if instructor else "—",
        "room_name": room.name if room else "—",
        "status": reservation.status,
        "breach_flag": reservation.breach_flag,
        "booked_at": _fmt_datetime(reservation.created_at),
        "can_cancel": can_act,
        "can_reschedule": can_act,
        "can_review": can_review,
        "has_review": has_review,
    }


def reservation_to_dict(reservation: Reservation) -> dict:
    """Public wrapper so route handlers can convert an ORM Reservation to the
    standard booking dict used by ``booking_card.html``."""
    return _reservation_dict(reservation)


# ── Function 1 ────────────────────────────────────────────────────────────────

def get_sessions_for_date(date_str: str, instructor_id: int = None) -> list[dict]:
    """
    Return all active studio sessions for a given date.

    Parameters
    ----------
    date_str : str
        Date in MM/DD/YYYY format (e.g., "03/31/2026").
    instructor_id : int, optional
        When supplied, restrict results to sessions taught by this instructor.

    Returns
    -------
    list[dict]
        Each element contains:
        id, title, description, instructor_name, room_name,
        start_time (12-hr), end_time (12-hr), date (MM/DD/YYYY),
        capacity, booked_count, spots_remaining, is_full.

    Raises
    ------
    ValueError
        If date_str is not a valid MM/DD/YYYY date.
    """
    try:
        target_date = datetime.strptime(date_str, "%m/%d/%Y").date()
    except ValueError:
        raise ValueError("Invalid date format. Use MM/DD/YYYY.")

    logger.debug("get_sessions_for_date: date=%s instructor_id=%s", date_str, instructor_id)

    query = StudioSession.query.filter(
        StudioSession.is_active == True,  # noqa: E712
        db.func.date(StudioSession.start_time) == target_date,
    )

    if instructor_id is not None:
        query = query.filter(StudioSession.instructor_id == instructor_id)

    sessions = query.order_by(StudioSession.start_time.asc()).all()

    result = []
    for s in sessions:
        booked_count = Reservation.query.filter_by(
            session_id=s.id, status="confirmed"
        ).count()
        spots_remaining = max(0, s.capacity - booked_count)

        result.append({
            "id": s.id,
            "title": s.title,
            "description": s.description or "",
            "instructor_name": s.instructor.username if s.instructor else "—",
            "room_name": s.room.name if s.room else "—",
            "start_time": _fmt_time(s.start_time),
            "end_time": _fmt_time(s.end_time),
            "date": _fmt_date(s.start_time),
            "capacity": s.capacity,
            "booked_count": booked_count,
            "spots_remaining": spots_remaining,
            "is_full": spots_remaining == 0,
        })

    logger.info(
        "get_sessions_for_date: returned %d sessions for %s", len(result), date_str
    )
    return result


# ── Function 2 ────────────────────────────────────────────────────────────────

def check_booking_conflicts(user_id: int, session_id: int) -> dict | None:
    """
    Detect whether booking *session_id* would overlap with an existing confirmed
    reservation held by *user_id*.

    Parameters
    ----------
    user_id : int
    session_id : int

    Returns
    -------
    None
        No conflict exists.
    dict
        ``{"conflict": True, "conflicting_session": {"id", "title",
        "start_time", "end_time"}}``

    Raises
    ------
    ValueError
        If *session_id* is not found.
    """
    target = StudioSession.query.get(session_id)
    if target is None:
        raise ValueError("Session not found.")

    confirmed = Reservation.query.filter_by(
        user_id=user_id, status="confirmed"
    ).all()

    for res in confirmed:
        existing = res.session
        if existing.id == session_id:
            continue  # same session handled separately as duplicate check
        # Overlap: A starts before B ends AND B starts before A ends
        if existing.start_time < target.end_time and target.start_time < existing.end_time:
            logger.debug(
                "check_booking_conflicts: user %d conflicts session %d with %d",
                user_id, session_id, existing.id,
            )
            return {
                "conflict": True,
                "conflicting_session": {
                    "id": existing.id,
                    "title": existing.title,
                    "start_time": _fmt_time(existing.start_time),
                    "end_time": _fmt_time(existing.end_time),
                },
            }

    return None


# ── Function 3 ────────────────────────────────────────────────────────────────

def create_reservation(user_id: int, session_id: int) -> dict:
    """
    Attempt to book a spot in a studio session for a user.

    Checks are executed in order:
    1. Session exists and is active.
    2. User does not already hold a confirmed reservation for this session.
    3. No time conflict with existing reservations.
    4. Capacity not exceeded (otherwise suggest waitlist).
    5. Credit score gates (blocked < 20, approval required < 50).
    6. Create confirmed reservation.

    Returns
    -------
    dict
        On success: ``{"success": True, "reservation_id": int, "message": str}``
        On failure: ``{"success": False, "reason": str, "action": str}``
        ``action`` values: ``"none"`` | ``"waitlist"`` | ``"approval_required"``
        | ``"blocked"`` | ``"conflict"``
    """
    logger.info("create_reservation: user_id=%d session_id=%d", user_id, session_id)

    # Step 1 — session exists and is active
    session = StudioSession.query.get(session_id)
    if session is None or not session.is_active:
        return {
            "success": False,
            "reason": "Session not found or no longer available.",
            "action": "none",
        }

    # Step 2 — duplicate check
    existing = Reservation.query.filter_by(
        user_id=user_id, session_id=session_id, status="confirmed"
    ).first()
    if existing:
        return {
            "success": False,
            "reason": "You already have a reservation for this session.",
            "action": "none",
        }

    # Step 3 — time conflict
    conflict = check_booking_conflicts(user_id, session_id)
    if conflict:
        cs = conflict["conflicting_session"]
        return {
            "success": False,
            "reason": (
                f"Time conflict with '{cs['title']}' at {cs['start_time']}."
            ),
            "action": "conflict",
        }

    # Step 4 — capacity
    booked_count = Reservation.query.filter_by(
        session_id=session_id, status="confirmed"
    ).count()
    if booked_count >= session.capacity:
        return {
            "success": False,
            "reason": (
                f"This session is full ({booked_count}/{session.capacity} spots taken)."
            ),
            "action": "waitlist",
        }

    # Step 5 — credit score gates
    user = User.query.get(user_id)
    if user.credit_score < 20:
        logger.warning(
            "create_reservation: user %d blocked (credit_score=%d)",
            user_id, user.credit_score,
        )
        return {
            "success": False,
            "reason": (
                "Your account is restricted due to low credit score. "
                "Please contact staff."
            ),
            "action": "blocked",
        }

    if user.credit_score < 50:
        reservation = Reservation(
            user_id=user_id,
            session_id=session_id,
            status="pending_approval",
        )
        db.session.add(reservation)
        db.session.commit()
        logger.info(
            "create_reservation: pending_approval reservation %d created "
            "(user credit=%d)", reservation.id, user.credit_score,
        )
        return {
            "success": True,
            "reservation_id": reservation.id,
            "message": (
                "Your booking requires staff approval due to account standing. "
                "You will be notified once reviewed."
            ),
        }

    # Step 6 — confirmed reservation
    reservation = Reservation(
        user_id=user_id,
        session_id=session_id,
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()
    logger.info("create_reservation: confirmed reservation %d created", reservation.id)
    return {
        "success": True,
        "reservation_id": reservation.id,
        "message": "Booking confirmed! You're all set.",
    }


# ── Function 4 ────────────────────────────────────────────────────────────────

def cancel_reservation(reservation_id: int, user_id: int) -> dict:
    """
    Cancel a reservation, applying a late-cancellation breach when the session
    starts within 12 hours. Promotes the #1 waitlist entry if one exists.

    Parameters
    ----------
    reservation_id : int
    user_id : int
        The requesting user. Admins may cancel any reservation; others can only
        cancel their own.

    Returns
    -------
    dict
        ``{"success": True, "message": str, "breach": bool}``
        ``{"success": False, "reason": str}``
    """
    logger.info(
        "cancel_reservation: reservation_id=%d requested_by=%d",
        reservation_id, user_id,
    )

    # Step 1 — load reservation
    reservation = Reservation.query.get(reservation_id)
    if reservation is None:
        return {"success": False, "reason": "Reservation not found."}

    # Step 2 — ownership / admin override
    if reservation.user_id != user_id:
        requesting_user = User.query.get(user_id)
        if requesting_user is None or requesting_user.role != "admin":
            return {
                "success": False,
                "reason": "You can only cancel your own reservations.",
            }

    # Step 3 — status guard
    if reservation.status not in ("confirmed", "pending_approval"):
        return {
            "success": False,
            "reason": (
                f"Cannot cancel a reservation with status '{reservation.status}'."
            ),
        }

    # Step 4 — session-start boundary: block cancellations once session has begun
    session = StudioSession.query.get(reservation.session_id)
    now = datetime.utcnow()
    if now >= session.start_time:
        return {
            "success": False,
            "reason": "Cannot cancel after the session has started.",
        }

    # Step 5 — breach detection (< 12 h before start → late-cancel penalty)
    hours_until_start = (session.start_time - now).total_seconds() / 3600
    breach = hours_until_start < 12

    # Step 6 — update reservation
    reservation.status = "canceled"
    reservation.breach_flag = breach
    reservation.updated_at = datetime.utcnow()

    # Step 7 — record credit penalty for breach
    if breach:
        credit_entry = CreditHistory(
            user_id=reservation.user_id,
            event_type="late_cancel",
            points=-1,
            reference_id=reservation.id,
            note=(
                f"Late cancellation for session '{session.title}' "
                f"({hours_until_start:.1f} hours before start)"
            ),
        )
        db.session.add(credit_entry)
        logger.warning(
            "cancel_reservation: breach recorded for user %d reservation %d "
            "(%.1fh before start)",
            reservation.user_id, reservation_id, hours_until_start,
        )

    # Step 8 — promote waitlist
    promote_waitlist(reservation.session_id)

    db.session.commit()

    if breach:
        return {
            "success": True,
            "message": (
                "Reservation canceled. Warning: This is a late cancellation "
                "(less than 12 hours before start). A breach has been recorded "
                "and your credit score has been affected."
            ),
            "breach": True,
        }
    return {"success": True, "message": "Reservation canceled successfully.", "breach": False}


# ── Function 5 ────────────────────────────────────────────────────────────────

def reschedule_reservation(
    reservation_id: int, new_session_id: int, user_id: int
) -> dict:
    """
    Cancel an existing reservation and book a new session in one transaction.

    The old reservation is marked ``"rescheduled"``; the new one is
    ``"confirmed"`` and carries ``original_reservation_id`` pointing back to the
    old one.

    Parameters
    ----------
    reservation_id : int
        The reservation being rescheduled.
    new_session_id : int
        The target session to move to.
    user_id : int

    Returns
    -------
    dict
        ``{"success": True, "new_reservation_id": int, "message": str, "breach": bool}``
        ``{"success": False, "reason": str}``
    """
    logger.info(
        "reschedule_reservation: reservation_id=%d new_session_id=%d user_id=%d",
        reservation_id, new_session_id, user_id,
    )

    # Step 1 — load old reservation and verify ownership
    old_res = Reservation.query.get(reservation_id)
    if old_res is None:
        return {"success": False, "reason": "Reservation not found."}

    if old_res.user_id != user_id:
        requesting_user = User.query.get(user_id)
        if requesting_user is None or requesting_user.role != "admin":
            return {
                "success": False,
                "reason": "You can only reschedule your own reservations.",
            }

    if old_res.status not in ("confirmed", "pending_approval"):
        return {
            "success": False,
            "reason": (
                f"Cannot reschedule a reservation with status '{old_res.status}'."
            ),
        }

    # Step 2 — validate new session capacity
    new_session = StudioSession.query.get(new_session_id)
    if new_session is None or not new_session.is_active:
        return {
            "success": False,
            "reason": "Target session not found or no longer available.",
        }

    new_booked = Reservation.query.filter_by(
        session_id=new_session_id, status="confirmed"
    ).count()
    if new_booked >= new_session.capacity:
        return {
            "success": False,
            "reason": (
                "The target session is full. "
                "Choose another session or join its waitlist."
            ),
        }

    # Step 3 — conflict check (excluding the reservation being rescheduled)
    target = new_session
    confirmed_other = (
        Reservation.query
        .filter(
            Reservation.user_id == user_id,
            Reservation.status == "confirmed",
            Reservation.id != reservation_id,
        )
        .all()
    )
    for res in confirmed_other:
        existing = res.session
        if existing.start_time < target.end_time and target.start_time < existing.end_time:
            return {
                "success": False,
                "reason": (
                    f"Time conflict with '{existing.title}' at "
                    f"{_fmt_time(existing.start_time)}."
                ),
            }

    # Step 4 — session-start boundary: block reschedules once original session has begun
    old_session = StudioSession.query.get(old_res.session_id)
    now = datetime.utcnow()
    if now >= old_session.start_time:
        return {
            "success": False,
            "reason": "Cannot reschedule after the original session has started.",
        }

    # Step 5 — breach detection (< 12 h before start → late-cancel penalty)
    hours_until_start = (old_session.start_time - now).total_seconds() / 3600
    breach = hours_until_start < 12

    # Step 6 — mark old reservation as rescheduled
    old_res.status = "rescheduled"
    old_res.breach_flag = breach
    old_res.updated_at = datetime.utcnow()

    if breach:
        credit_entry = CreditHistory(
            user_id=old_res.user_id,
            event_type="late_cancel",
            points=-1,
            reference_id=old_res.id,
            note=(
                f"Late reschedule for session '{old_session.title}' "
                f"({hours_until_start:.1f} hours before start)"
            ),
        )
        db.session.add(credit_entry)
        logger.warning(
            "reschedule_reservation: breach recorded for user %d old_reservation %d",
            old_res.user_id, reservation_id,
        )

    # Step 7 — create new confirmed reservation
    new_res = Reservation(
        user_id=old_res.user_id,
        session_id=new_session_id,
        status="confirmed",
        original_reservation_id=old_res.id,
    )
    db.session.add(new_res)

    # Step 8 — promote waitlist on old session
    promote_waitlist(old_res.session_id)

    db.session.commit()

    logger.info(
        "reschedule_reservation: new reservation %d created from old %d",
        new_res.id, reservation_id,
    )

    base_msg = f"Rescheduled to '{new_session.title}' on {_fmt_date(new_session.start_time)}."
    if breach:
        base_msg += (
            " Warning: Your original cancellation was within 12 hours of the "
            "session start — a breach has been recorded."
        )

    return {
        "success": True,
        "new_reservation_id": new_res.id,
        "message": base_msg,
        "breach": breach,
    }


# ── Function 6 ────────────────────────────────────────────────────────────────

def join_waitlist(user_id: int, session_id: int) -> dict:
    """
    Add a user to the waitlist for a full session.

    Parameters
    ----------
    user_id : int
    session_id : int

    Returns
    -------
    dict
        ``{"success": True, "position": int, "message": str}``
        ``{"success": False, "reason": str}``
    """
    logger.info("join_waitlist: user_id=%d session_id=%d", user_id, session_id)

    session = StudioSession.query.get(session_id)
    if session is None or not session.is_active:
        return {"success": False, "reason": "Session not found or no longer available."}

    booked_count = Reservation.query.filter_by(
        session_id=session_id, status="confirmed"
    ).count()
    if booked_count < session.capacity:
        return {
            "success": False,
            "reason": "This session still has available spots. Please book directly instead of joining the waitlist.",
        }

    existing = Waitlist.query.filter_by(
        user_id=user_id, session_id=session_id, is_active=True
    ).first()
    if existing:
        return {
            "success": False,
            "reason": "You are already on the waitlist for this session.",
        }

    position = (
        Waitlist.query.filter_by(session_id=session_id, is_active=True).count() + 1
    )

    entry = Waitlist(
        user_id=user_id,
        session_id=session_id,
        position=position,
        is_active=True,
    )
    db.session.add(entry)
    db.session.commit()

    logger.info(
        "join_waitlist: user %d joined waitlist for session %d at position %d",
        user_id, session_id, position,
    )
    return {
        "success": True,
        "position": position,
        "message": (
            f"You are #{position} on the waitlist. "
            "We'll notify you if a spot opens up."
        ),
    }


# ── Function 7 ────────────────────────────────────────────────────────────────

def promote_waitlist(session_id: int) -> dict | None:
    """
    Promote the top waitlist entry to a confirmed reservation when a spot opens.

    This function is called internally by cancel_reservation and
    reschedule_reservation before the parent ``db.session.commit()``, so it
    does **not** commit itself — the caller owns the transaction.

    Parameters
    ----------
    session_id : int

    Returns
    -------
    dict
        ``{"promoted_user_id": int, "reservation_id": int}``
    None
        Waitlist is empty.
    """
    entry = (
        Waitlist.query
        .filter_by(session_id=session_id, is_active=True)
        .order_by(Waitlist.position.asc())
        .first()
    )
    if entry is None:
        return None

    promoted_position = entry.position
    entry.is_active = False

    new_res = Reservation(
        user_id=entry.user_id,
        session_id=session_id,
        status="confirmed",
    )
    db.session.add(new_res)

    # Reorder remaining waitlist entries: shift everyone above the promoted slot down by 1
    remaining = (
        Waitlist.query
        .filter(
            Waitlist.session_id == session_id,
            Waitlist.is_active == True,  # noqa: E712
            Waitlist.position > promoted_position,
        )
        .all()
    )
    for w in remaining:
        w.position -= 1

    logger.info(
        "promote_waitlist: user %d promoted from waitlist for session %d",
        entry.user_id, session_id,
    )
    return {"promoted_user_id": entry.user_id, "reservation_id": new_res.id}


# ── Function 8 ────────────────────────────────────────────────────────────────

def get_user_bookings(user_id: int) -> dict:
    """
    Retrieve all bookings for a user, grouped by lifecycle status.

    Parameters
    ----------
    user_id : int

    Returns
    -------
    dict
        Keys: ``upcoming``, ``pending``, ``past``, ``canceled``,
        ``no_shows``, ``waitlist``.

        Each reservation list entry is built by :func:`_reservation_dict`.
        Each waitlist entry contains:
        ``{"waitlist_id", "session_id", "session_title", "session_date",
        "session_start", "session_end", "instructor_name", "position",
        "joined_at"}``.
    """
    logger.debug("get_user_bookings: user_id=%d", user_id)

    now = datetime.utcnow()

    all_reservations = (
        Reservation.query
        .filter_by(user_id=user_id)
        .join(StudioSession, Reservation.session_id == StudioSession.id)
        .all()
    )

    upcoming, pending, past, canceled, no_shows = [], [], [], [], []

    for res in all_reservations:
        d = _reservation_dict(res)
        if res.status == "confirmed" and res.session.start_time > now:
            upcoming.append(d)
        elif res.status == "pending_approval":
            pending.append(d)
        elif res.status == "completed":
            past.append(d)
        elif res.status in ("canceled", "rescheduled"):
            canceled.append(d)
        elif res.status == "no_show":
            no_shows.append(d)

    # Sort lists
    upcoming.sort(key=lambda x: x["session_date"] + x["session_start"])
    past.sort(key=lambda x: x["session_date"], reverse=True)
    canceled.sort(key=lambda x: x["session_date"], reverse=True)
    no_shows.sort(key=lambda x: x["session_date"], reverse=True)

    # Waitlist entries
    active_waitlist = (
        Waitlist.query
        .filter_by(user_id=user_id, is_active=True)
        .order_by(Waitlist.position.asc())
        .all()
    )

    waitlist_items = []
    for w in active_waitlist:
        s = w.session
        waitlist_items.append({
            "waitlist_id": w.id,
            "session_id": s.id,
            "session_title": s.title,
            "session_date": _fmt_date(s.start_time),
            "session_start": _fmt_time(s.start_time),
            "session_end": _fmt_time(s.end_time),
            "instructor_name": s.instructor.username if s.instructor else "—",
            "position": w.position,
            "joined_at": _fmt_datetime(w.created_at),
        })

    return {
        "upcoming": upcoming,
        "pending": pending,
        "past": past,
        "canceled": canceled,
        "no_shows": no_shows,
        "waitlist": waitlist_items,
    }


# ── Function 9 ────────────────────────────────────────────────────────────────

def leave_waitlist(waitlist_id: int, user_id: int) -> dict:
    """
    Remove a user from the waitlist and compact the remaining positions.

    Parameters
    ----------
    waitlist_id : int
    user_id : int

    Returns
    -------
    dict
        ``{"success": True, "message": str}``
        ``{"success": False, "reason": str}``
    """
    logger.info("leave_waitlist: waitlist_id=%d user_id=%d", waitlist_id, user_id)

    entry = Waitlist.query.get(waitlist_id)
    if entry is None:
        return {"success": False, "reason": "Waitlist entry not found."}

    if entry.user_id != user_id:
        requesting_user = User.query.get(user_id)
        if requesting_user is None or requesting_user.role != "admin":
            return {
                "success": False,
                "reason": "You can only remove yourself from the waitlist.",
            }

    if not entry.is_active:
        return {
            "success": False,
            "reason": "This waitlist entry is no longer active.",
        }

    departed_position = entry.position
    session_id = entry.session_id
    entry.is_active = False

    # Compact: shift all entries with a higher position down by 1
    remaining = (
        Waitlist.query
        .filter(
            Waitlist.session_id == session_id,
            Waitlist.is_active == True,  # noqa: E712
            Waitlist.position > departed_position,
        )
        .all()
    )
    for w in remaining:
        w.position -= 1

    db.session.commit()

    logger.info(
        "leave_waitlist: user %d removed from waitlist entry %d for session %d",
        user_id, waitlist_id, session_id,
    )
    return {"success": True, "message": "You have been removed from the waitlist."}
