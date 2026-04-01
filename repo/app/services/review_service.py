"""
Review service — all review and appeal business logic.

Functions:
  check_review_eligibility  – pre-flight check before allowing a review
  create_review             – create a review with images, filtering, dedup
  get_session_reviews       – fetch active reviews for a session with stats
  file_appeal               – dispute a review (5 business-day deadline)
  resolve_appeal            – admin upholds or rejects a dispute
  get_pending_appeals       – admin queue of unresolved disputes
  get_user_reviews          – written, received, and filed appeals for a user
  update_review             – author edits their own review
  delete_review             – soft-delete (author or admin)
"""
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from app.models.analytics import CreditHistory
from app.models.review import Appeal, Review, ReviewImage
from app.models.studio import Reservation
from app.models.user import User
from app.services.content_filter_service import filter_content

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _add_business_days(start_date: datetime, days: int) -> datetime:
    """Return start_date + N business days (Mon–Fri only)."""
    current = start_date
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:   # 0=Mon … 4=Fri
            added += 1
    return current


def _format_date(dt: datetime | None) -> str | None:
    return dt.strftime("%m/%d/%Y") if dt else None


def _format_datetime(dt: datetime | None) -> str | None:
    return dt.strftime("%m/%d/%Y %I:%M %p") if dt else None


def _review_to_dict(review: Review) -> dict:
    """Serialise a Review ORM object to a plain dict."""
    images = [
        {"id": img.id, "file_path": img.file_path, "file_size": img.file_size}
        for img in review.images.all()
    ]
    author_name = review.user.username if review.user else f"user#{review.user_id}"
    return {
        "id": review.id,
        "reservation_id": review.reservation_id,
        "user_id": review.user_id,
        "author_name": author_name,
        "reviewer_role": review.reviewer_role,
        "rating": review.rating,
        "tags": _parse_tags(review.tags),
        "text": review.text,
        "status": review.status,
        "images": images,
        "created_at": _format_datetime(review.created_at),
        "updated_at": _format_datetime(review.updated_at),
    }


def _parse_tags(tags_json: str | None) -> list:
    if not tags_json:
        return []
    try:
        parsed = json.loads(tags_json)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ── FUNCTION 1: check_review_eligibility ─────────────────────────────────────

def check_review_eligibility(user_id: int, reservation_id: int) -> dict:
    """
    Check if a user is allowed to leave a review.

    Returns:
        {"eligible": True}
        OR {"eligible": False, "reason": str}
    """
    reservation = Reservation.query.get(reservation_id)
    if not reservation:
        return {"eligible": False, "reason": "Reservation not found."}

    status_blocks = {
        "canceled": "Reviews are not available for canceled sessions.",
        "no_show": "Reviews are not available for missed sessions.",
        "confirmed": "This session has not been completed yet. Reviews are available after check-in.",
        "pending_approval": "This booking has not been confirmed yet.",
    }
    if reservation.status in status_blocks:
        return {"eligible": False, "reason": status_blocks[reservation.status]}

    if reservation.status != "completed":
        return {"eligible": False, "reason": f"Unexpected reservation status: {reservation.status}."}

    session = reservation.session
    is_participant = (
        reservation.user_id == user_id
        or (session and session.instructor_id == user_id)
    )
    if not is_participant:
        return {"eligible": False, "reason": "You can only review sessions you participated in."}

    existing = Review.query.filter_by(
        reservation_id=reservation_id, user_id=user_id
    ).first()
    if existing:
        return {"eligible": False, "reason": "You have already reviewed this session."}

    return {"eligible": True}


# ── FUNCTION 2: create_review ─────────────────────────────────────────────────

def create_review(
    user_id: int,
    reservation_id: int,
    rating: int,
    tags: list[str] = None,
    text: str = None,
    images: list = None,
) -> dict:
    """
    Create a review with full validation.

    Returns:
        {"success": True, "review_id": int}
        OR {"success": False, "reason": str, "violations": list}
    """
    # Step 1: eligibility
    eligibility = check_review_eligibility(user_id, reservation_id)
    if not eligibility["eligible"]:
        return {"success": False, "reason": eligibility["reason"], "violations": []}

    # Step 2: rating
    if not isinstance(rating, int) or rating < 1 or rating > 5:
        return {"success": False, "reason": "Rating must be between 1 and 5.", "violations": []}

    # Step 3: text length
    if text and len(text) > 2000:
        return {
            "success": False,
            "reason": "Review text cannot exceed 2000 characters.",
            "violations": [],
        }

    # Step 4: content filter
    if text:
        filter_result = filter_content(text)
        if not filter_result["passed"]:
            return {
                "success": False,
                "reason": "Review contains prohibited content.",
                "violations": filter_result["violations"],
            }

    # Step 5: validate images
    images = images or []
    if len(images) > 3:
        return {"success": False, "reason": "Maximum 3 images allowed per review.", "violations": []}

    ALLOWED_IMAGE_EXTS = {"jpg", "jpeg", "png"}
    MAX_IMAGE_SIZE = 10 * 1024 * 1024
    seen_fingerprints: set[str] = set()
    validated_images = []  # (file_content, ext, fingerprint) tuples

    for img in images:
        if not img or not img.filename:
            continue
        ext = img.filename.rsplit(".", 1)[-1].lower() if "." in img.filename else ""
        if ext not in ALLOWED_IMAGE_EXTS:
            return {
                "success": False,
                "reason": "Only JPG and PNG images are allowed for reviews.",
                "violations": [],
            }
        content = img.read()
        img.seek(0)
        if len(content) > MAX_IMAGE_SIZE:
            return {"success": False, "reason": "Image exceeds 10 MB limit.", "violations": []}
        fingerprint = hashlib.sha256(content).hexdigest()
        if fingerprint in seen_fingerprints:
            return {"success": False, "reason": "Duplicate image detected.", "violations": []}
        seen_fingerprints.add(fingerprint)
        validated_images.append((content, ext, fingerprint))

    # Step 6: determine reviewer_role
    user = User.query.get(user_id)
    reviewer_role = user.role if user else "customer"

    # Step 7: create Review
    tags_json = json.dumps(tags or [])
    review = Review(
        reservation_id=reservation_id,
        user_id=user_id,
        rating=rating,
        tags=tags_json,
        text=text,
        status="active",
        reviewer_role=reviewer_role,
    )
    db.session.add(review)
    db.session.flush()  # need review.id for image paths

    # Step 8: save images
    if validated_images:
        upload_dir = os.path.join(
            current_app.config["UPLOAD_FOLDER"], "reviews", str(review.id)
        )
        os.makedirs(upload_dir, exist_ok=True)

        for file_content, ext, fingerprint in validated_images:
            safe_name = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(upload_dir, safe_name)
            with open(file_path, "wb") as f:
                f.write(file_content)
            img_record = ReviewImage(
                review_id=review.id,
                file_path=file_path,
                file_size=len(file_content),
                fingerprint=fingerprint,
            )
            db.session.add(img_record)

    # Step 9: commit
    db.session.commit()
    logger.info(
        "Review created: id=%d reservation=%d user=%d rating=%d",
        review.id, reservation_id, user_id, rating,
    )
    return {"success": True, "review_id": review.id}


# ── FUNCTION 3: get_session_reviews ──────────────────────────────────────────

def get_session_reviews(session_id: int, sort: str = "recent") -> dict:
    """
    Get all active reviews for a studio session with aggregate stats.

    Returns:
        {
            "reviews": [list of review dicts],
            "average_rating": float,
            "total_reviews": int,
            "rating_distribution": {1: count, …, 5: count}
        }
    """
    sort_map = {
        "recent": Review.created_at.desc(),
        "highest": Review.rating.desc(),
        "lowest": Review.rating.asc(),
    }
    order_clause = sort_map.get(sort, Review.created_at.desc())

    reviews = (
        Review.query
        .join(Review.reservation)
        .filter(
            Reservation.session_id == session_id,
            Review.status == "active",
        )
        .order_by(order_clause)
        .all()
    )

    distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in reviews:
        if r.rating in distribution:
            distribution[r.rating] += 1

    total = len(reviews)
    average = round(sum(r.rating for r in reviews) / total, 2) if total else 0.0

    return {
        "reviews": [_review_to_dict(r) for r in reviews],
        "average_rating": average,
        "total_reviews": total,
        "rating_distribution": distribution,
    }


# ── FUNCTION 4: file_appeal ───────────────────────────────────────────────────

def file_appeal(review_id: int, user_id: int, reason: str) -> dict:
    """
    File a dispute against a review.

    Returns:
        {"success": True, "appeal_id": int, "deadline": str (MM/DD/YYYY)}
        OR {"success": False, "reason": str}
    """
    review = Review.query.get(review_id)
    if not review:
        return {"success": False, "reason": "Review not found."}

    if review.user_id == user_id:
        return {"success": False, "reason": "You cannot dispute your own review."}

    existing = Appeal.query.filter_by(
        review_id=review_id, user_id=user_id, status="pending"
    ).first()
    if existing:
        return {
            "success": False,
            "reason": "You already have a pending dispute for this review.",
        }

    if not reason or len(reason.strip()) < 20:
        return {
            "success": False,
            "reason": "Reason must be at least 20 characters.",
        }
    if len(reason) > 2000:
        return {
            "success": False,
            "reason": "Reason cannot exceed 2000 characters.",
        }

    now = datetime.utcnow()
    deadline = _add_business_days(now, 5)

    appeal = Appeal(
        review_id=review_id,
        user_id=user_id,
        reason=reason.strip(),
        status="pending",
        deadline=deadline,
    )
    db.session.add(appeal)

    review.status = "disputed"
    db.session.commit()

    logger.info(
        "Appeal filed: id=%d review=%d user=%d deadline=%s",
        appeal.id, review_id, user_id, deadline.strftime("%m/%d/%Y"),
    )
    return {
        "success": True,
        "appeal_id": appeal.id,
        "deadline": deadline.strftime("%m/%d/%Y"),
    }


# ── FUNCTION 5: resolve_appeal ────────────────────────────────────────────────

def resolve_appeal(
    appeal_id: int, admin_id: int, decision: str, resolution_text: str
) -> dict:
    """
    Admin resolves an appeal.

    decision: "upheld" or "rejected"
    resolution_text: required, min 10 chars
    """
    appeal = Appeal.query.get(appeal_id)
    if not appeal:
        return {"success": False, "reason": "Appeal not found."}
    if appeal.status != "pending":
        return {"success": False, "reason": "This appeal has already been resolved."}

    if not resolution_text or len(resolution_text.strip()) < 10:
        return {
            "success": False,
            "reason": "Resolution text must be at least 10 characters.",
        }

    now = datetime.utcnow()
    review = appeal.review

    if decision == "upheld":
        appeal.status = "upheld"
        appeal.resolved_at = now
        appeal.admin_id = admin_id
        appeal.resolution_text = resolution_text.strip()

        review.status = "removed"

        credit_entry = CreditHistory(
            user_id=review.user_id,
            event_type="dispute_upheld",
            points=-5,
            reference_id=appeal.id,
            note=f"Review #{review.id} removed after successful dispute.",
        )
        db.session.add(credit_entry)

        # Deduct from user's credit_score
        author = User.query.get(review.user_id)
        if author:
            author.credit_score = max(0, author.credit_score - 5)

        message = "Appeal upheld. The review has been removed and the author penalised."

    elif decision == "rejected":
        appeal.status = "rejected"
        appeal.resolved_at = now
        appeal.admin_id = admin_id
        appeal.resolution_text = resolution_text.strip()

        review.status = "active"
        message = "Appeal rejected. The review has been restored to active."

    else:
        return {
            "success": False,
            "reason": f"Unknown decision '{decision}'. Must be 'upheld' or 'rejected'.",
        }

    db.session.commit()
    logger.info(
        "Appeal resolved: id=%d decision=%s admin=%d", appeal_id, decision, admin_id
    )
    return {"success": True, "message": message}


# ── FUNCTION 6: get_pending_appeals ──────────────────────────────────────────

def get_pending_appeals() -> list[dict]:
    """Get all pending appeals sorted by deadline (closest first)."""
    appeals = (
        Appeal.query
        .filter_by(status="pending")
        .order_by(Appeal.deadline.asc())
        .all()
    )

    now = datetime.utcnow()
    result = []
    for appeal in appeals:
        review = appeal.review
        days_remaining = (appeal.deadline - now).days

        filer_name = appeal.filer.username if appeal.filer else f"user#{appeal.user_id}"

        review_dict = _review_to_dict(review) if review else {}

        # Resolve session title via the reservation → session chain
        session_title = ""
        if review and review.reservation and review.reservation.session:
            session_title = review.reservation.session.title

        result.append({
            "appeal_id": appeal.id,
            "review": review_dict,
            # Flat keys used directly by appeals_dashboard.html
            "review_rating": review_dict.get("rating", 0),
            "review_text": review_dict.get("text", ""),
            "reviewer_name": review_dict.get("author_name", ""),
            "session_title": session_title,
            "reason": appeal.reason,
            "filer_name": filer_name,
            "filed_at": _format_datetime(appeal.created_at),
            "deadline": _format_date(appeal.deadline),
            "days_remaining": max(days_remaining, 0),
            "is_overdue": days_remaining < 0,
        })

    return result


# ── FUNCTION 7: get_user_reviews ──────────────────────────────────────────────

def get_user_reviews(user_id: int) -> dict:
    """
    Return reviews written by the user, reviews received about sessions the
    user attended, and appeals filed by the user.

    Returns:
        {
            "written":  [review dicts the user authored],
            "received": [review dicts for sessions the user attended as instructor],
            "appeals":  [appeal dicts filed by the user]
        }
    """
    # Reviews the user wrote
    written_reviews = (
        Review.query
        .filter_by(user_id=user_id)
        .order_by(Review.created_at.desc())
        .all()
    )

    # Reviews about sessions where this user was the instructor
    received_reviews = (
        Review.query
        .join(Review.reservation)
        .join(Reservation.session)
        .filter(
            Review.status == "active",
            db.text(f"studio_sessions.instructor_id = {user_id}"),
        )
        .order_by(Review.created_at.desc())
        .all()
    )

    # Appeals filed by the user
    appeals = (
        Appeal.query
        .filter_by(user_id=user_id)
        .order_by(Appeal.created_at.desc())
        .all()
    )

    now = datetime.utcnow()
    appeals_list = []
    for a in appeals:
        appeals_list.append({
            "appeal_id": a.id,
            "review_id": a.review_id,
            "status": a.status,
            "reason": a.reason,
            "resolution_text": a.resolution_text,
            "filed_at": _format_datetime(a.created_at),
            "deadline": _format_date(a.deadline),
            "days_remaining": max((a.deadline - now).days, 0) if a.status == "pending" else None,
            "is_overdue": (a.deadline < now) if a.status == "pending" else False,
        })

    return {
        "written": [_review_to_dict(r) for r in written_reviews],
        "received": [_review_to_dict(r) for r in received_reviews],
        "appeals": appeals_list,
    }


# ── FUNCTION 8: update_review ─────────────────────────────────────────────────

def update_review(
    review_id: int,
    user_id: int,
    rating: int = None,
    tags: list[str] = None,
    text: str = None,
) -> dict:
    """Edit an existing review. Only the original author can edit."""
    review = Review.query.get(review_id)
    if not review:
        return {"success": False, "reason": "Review not found."}

    if review.user_id != user_id:
        return {"success": False, "reason": "You can only edit your own reviews."}

    if review.status == "removed":
        return {"success": False, "reason": "This review has been removed and cannot be edited."}

    if rating is not None:
        if not isinstance(rating, int) or rating < 1 or rating > 5:
            return {"success": False, "reason": "Rating must be between 1 and 5."}
        review.rating = rating

    if text is not None:
        if len(text) > 2000:
            return {
                "success": False,
                "reason": "Review text cannot exceed 2000 characters.",
            }
        if text:
            filter_result = filter_content(text)
            if not filter_result["passed"]:
                return {
                    "success": False,
                    "reason": "Review contains prohibited content.",
                    "violations": filter_result["violations"],
                }
        review.text = text

    if tags is not None:
        review.tags = json.dumps(tags)

    review.updated_at = datetime.utcnow()
    db.session.commit()

    logger.info("Review updated: id=%d by user=%d", review_id, user_id)
    return {"success": True, "review_id": review.id}


# ── FUNCTION 9: delete_review ─────────────────────────────────────────────────

def delete_review(review_id: int, user_id: int) -> dict:
    """
    Soft-delete a review. Only the original author or an admin may do this.
    Sets status to 'removed'.
    """
    review = Review.query.get(review_id)
    if not review:
        return {"success": False, "reason": "Review not found."}

    user = User.query.get(user_id)
    if not user:
        return {"success": False, "reason": "User not found."}

    is_author = review.user_id == user_id
    is_admin = user.role == "admin"

    if not is_author and not is_admin:
        return {
            "success": False,
            "reason": "You do not have permission to delete this review.",
        }

    if review.status == "removed":
        return {"success": False, "reason": "This review has already been removed."}

    review.status = "removed"
    db.session.commit()

    logger.info(
        "Review soft-deleted: id=%d by user=%d (admin=%s)",
        review_id, user_id, is_admin,
    )
    return {"success": True, "message": "Review has been removed."}
