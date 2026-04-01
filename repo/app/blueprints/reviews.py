"""
Reviews blueprint — review submission, session reviews, appeals.

URL layout (blueprint registered at /reviews):
  GET  /reviews/new/<reservation_id>      – review form
  POST /reviews                           – submit review
  GET  /reviews/session/<session_id>      – session reviews (public)
  GET  /reviews/my-reviews                – user's review history
  PUT  /reviews/<review_id>               – edit review
  DELETE /reviews/<review_id>             – soft-delete review
  POST /reviews/<review_id>/appeal        – file dispute

Admin routes (registered on admin_bp at /admin):
  GET  /admin/appeals                     – appeal dashboard
  POST /admin/appeals/<appeal_id>/resolve – resolve appeal
"""
import logging

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, abort, make_response,
)
from flask_login import current_user

from app.extensions import db
from app.models.review import Review, Appeal
from app.models.studio import Reservation, StudioSession
from app.services import review_service
from app.utils.decorators import login_required, role_required

logger = logging.getLogger(__name__)

reviews_bp = Blueprint("reviews", __name__)


def _is_htmx() -> bool:
    return bool(request.headers.get("HX-Request"))


def _error_frag(message: str, code: int = 400):
    return render_template(
        "partials/error_fragment.html", code=code, message=message
    ), code


# ── index (preserved for nav link back-compat) ────────────────────────────────

@reviews_bp.route("/")
@login_required
def index():
    """Redirect to user's reviews dashboard."""
    return redirect(url_for("reviews.my_reviews"))


# ── Route 1: GET /reviews/new/<reservation_id> ────────────────────────────────

@reviews_bp.route("/new/<int:reservation_id>")
@login_required
def review_form(reservation_id: int):
    """Show the review form if the user is eligible."""
    eligibility = review_service.check_review_eligibility(
        current_user.id, reservation_id
    )
    if not eligibility["eligible"]:
        return render_template(
            "reviews/ineligible.html", reason=eligibility["reason"]
        ), 403

    reservation = Reservation.query.get_or_404(reservation_id)
    session = reservation.session
    return render_template(
        "reviews/review_form.html",
        reservation=reservation,
        session=session,
    )


# ── Route 2: POST /reviews ────────────────────────────────────────────────────

@reviews_bp.route("", methods=["POST"])
@login_required
def submit_review():
    """Submit a new review."""
    reservation_id = request.form.get("reservation_id", type=int)
    rating_raw = request.form.get("rating", "0")
    try:
        rating = int(rating_raw)
    except (ValueError, TypeError):
        rating = 0

    tags = request.form.getlist("tags")
    text = request.form.get("text", "").strip() or None
    images = [f for f in request.files.getlist("images") if f and f.filename]

    result = review_service.create_review(
        user_id=current_user.id,
        reservation_id=reservation_id,
        rating=rating,
        tags=tags or None,
        text=text,
        images=images or None,
    )

    if result["success"]:
        logger.info("Review submitted: review_id=%d user=%d", result["review_id"], current_user.id)
        return render_template(
            "partials/reviews/review_submitted.html",
            review_id=result["review_id"],
        ), 201

    violations = result.get("violations", [])
    return render_template(
        "partials/reviews/review_error.html",
        reason=result["reason"],
        violations=violations,
    ), 400


# ── Route 3: GET /reviews/session/<session_id> ────────────────────────────────

@reviews_bp.route("/session/<int:session_id>")
def session_reviews(session_id: int):
    """Public session reviews page with sort support."""
    sort = request.args.get("sort", "recent")
    data = review_service.get_session_reviews(session_id, sort=sort)

    # Mark which reviews belong to the current user
    for r in data["reviews"]:
        r["is_own"] = (
            current_user.is_authenticated and r["user_id"] == current_user.id
        )

    session = StudioSession.query.get_or_404(session_id)

    if _is_htmx():
        return render_template(
            "partials/reviews/review_list.html",
            reviews=data["reviews"],
            session_id=session_id,
        )

    return render_template(
        "reviews/session_reviews.html",
        session=session,
        reviews=data["reviews"],
        average_rating=data["average_rating"],
        total_reviews=data["total_reviews"],
        rating_distribution=data["rating_distribution"],
        sort=sort,
        session_id=session_id,
    )


# ── Route 4: GET /reviews/my-reviews ─────────────────────────────────────────

@reviews_bp.route("/my-reviews")
@login_required
def my_reviews():
    """User's personal review history."""
    data = review_service.get_user_reviews(current_user.id)
    return render_template("reviews/my_reviews.html", **data)


# ── Route 5: PUT /reviews/<review_id> ────────────────────────────────────────

@reviews_bp.route("/<int:review_id>", methods=["PUT"])
@login_required
def edit_review(review_id: int):
    """Edit an existing review (author only)."""
    rating_raw = request.form.get("rating")
    try:
        rating = int(rating_raw) if rating_raw else None
    except (ValueError, TypeError):
        rating = None

    tags_raw = request.form.getlist("tags")
    tags = tags_raw if tags_raw else None
    text = request.form.get("text", "").strip() or None

    result = review_service.update_review(
        review_id=review_id,
        user_id=current_user.id,
        rating=rating,
        tags=tags,
        text=text,
    )

    if result["success"]:
        review = Review.query.get(review_id)
        review_dict = review_service._review_to_dict(review)
        review_dict["is_own"] = True
        return render_template(
            "partials/reviews/review_card.html", review=review_dict
        ), 200

    return _error_frag(result["reason"], 400)


# ── Route 6: DELETE /reviews/<review_id> ─────────────────────────────────────

@reviews_bp.route("/<int:review_id>", methods=["DELETE"])
@login_required
def delete_review(review_id: int):
    """Soft-delete a review (author or admin)."""
    result = review_service.delete_review(review_id, current_user.id)
    if result["success"]:
        return "", 200
    return _error_frag(result["reason"], 400)


# ── Route 7: POST /reviews/<review_id>/appeal ─────────────────────────────────

@reviews_bp.route("/<int:review_id>/appeal", methods=["POST"])
@login_required
def file_appeal(review_id: int):
    """File a dispute against a review."""
    reason = request.form.get("reason", "").strip()
    result = review_service.file_appeal(review_id, current_user.id, reason)

    if result["success"]:
        return render_template(
            "partials/reviews/appeal_submitted.html",
            deadline=result["deadline"],
            appeal_id=result["appeal_id"],
        ), 201

    return _error_frag(result["reason"], 400)
