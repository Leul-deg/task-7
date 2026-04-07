"""
Unit tests for app/services/review_service.py

Covers:
  - create_review (eligibility, rating bounds, text length, content filter, dedup)
  - get_session_reviews (stats, sort)
  - file_appeal (reason length, duplicate guard, business-day deadline)
  - resolve_appeal (credit deduction on uphold, review restoration on reject)
  - update_review (author-only, content filtering)
  - delete_review (soft-delete, admin override)
  - get_user_reviews (written / received / appeals split)
  - Business-day helper (_add_business_days skips weekends)
"""
import pytest
from datetime import datetime, timedelta

from app.services.review_service import (
    check_review_eligibility,
    create_review,
    file_appeal,
    get_session_reviews,
    get_user_reviews,
    resolve_appeal,
    update_review,
    delete_review,
    _add_business_days,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_review(db, reservation_id, user_id, rating=5, text="Great session!"):
    from app.models.review import Review
    r = Review(
        reservation_id=reservation_id,
        user_id=user_id,
        rating=rating,
        tags="[]",
        text=text,
        status="active",
        reviewer_role="customer",
    )
    db.session.add(r)
    db.session.commit()
    return r


# ── TestCheckEligibility ──────────────────────────────────────────────────────

class TestCheckEligibility:
    def test_eligible(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        result = check_review_eligibility(sample_users["customer"].id, res.id)
        assert result["eligible"] is True

    def test_confirmed_not_eligible(self, db, sample_users, sample_session):
        from app.models.studio import Reservation
        res = Reservation(
            user_id=sample_users["customer"].id,
            session_id=sample_session.id,
            status="confirmed",
        )
        db.session.add(res)
        db.session.commit()
        result = check_review_eligibility(sample_users["customer"].id, res.id)
        assert result["eligible"] is False
        assert "completed" in result["reason"].lower() or "has not been completed" in result["reason"].lower()

    def test_nonexistent_reservation(self, db, sample_users):
        result = check_review_eligibility(sample_users["customer"].id, 999999)
        assert result["eligible"] is False

    def test_already_reviewed(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        _make_review(db, res.id, sample_users["customer"].id)
        result = check_review_eligibility(sample_users["customer"].id, res.id)
        assert result["eligible"] is False
        assert "already" in result["reason"].lower()


# ── TestCreateReview ───────────────────────────────────────────────────────────

class TestCreateReview:
    def test_create_basic(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        result = create_review(
            user_id=sample_users["customer"].id,
            reservation_id=res.id,
            rating=4,
            text="Very good class.",
        )
        assert result["success"] is True
        assert "review_id" in result

    def test_rating_too_low(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        result = create_review(
            user_id=sample_users["customer"].id,
            reservation_id=res.id,
            rating=0,
        )
        assert result["success"] is False
        assert "rating" in result["reason"].lower()

    def test_rating_too_high(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        result = create_review(
            user_id=sample_users["customer"].id,
            reservation_id=res.id,
            rating=6,
        )
        assert result["success"] is False

    def test_text_too_long(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        result = create_review(
            user_id=sample_users["customer"].id,
            reservation_id=res.id,
            rating=3,
            text="x" * 2001,
        )
        assert result["success"] is False
        assert "2000" in result["reason"]

    def test_content_filter_blocks(self, db, completed_reservation, sample_users, sample_filter):
        res = completed_reservation["reservation"]
        result = create_review(
            user_id=sample_users["customer"].id,
            reservation_id=res.id,
            rating=3,
            text="This class was badword terrible.",
        )
        assert result["success"] is False
        assert result["violations"]

    def test_too_many_images(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]

        class FakeImg:
            def __init__(self, name, content=b"x" * 100):
                self.filename = name
                self._content = content
            def read(self):
                return self._content
            def seek(self, _):
                pass

        imgs = [FakeImg(f"img{i}.jpg") for i in range(4)]
        result = create_review(
            user_id=sample_users["customer"].id,
            reservation_id=res.id,
            rating=3,
            images=imgs,
        )
        assert result["success"] is False
        assert "3" in result["reason"]

    def test_customer_and_instructor_can_both_review_same_reservation(self, db, completed_reservation, sample_users):
        """A completed reservation accepts one review per user (customer + instructor)."""
        res = completed_reservation["reservation"]

        customer_result = create_review(
            user_id=sample_users["customer"].id,
            reservation_id=res.id,
            rating=5,
            text="Great class.",
        )
        assert customer_result["success"] is True

        staff_result = create_review(
            user_id=sample_users["staff"].id,
            reservation_id=res.id,
            rating=4,
            text="Customer was engaged.",
        )
        assert staff_result["success"] is True


# ── TestGetSessionReviews ──────────────────────────────────────────────────────

class TestGetSessionReviews:
    def test_empty_session(self, db, sample_session):
        result = get_session_reviews(sample_session.id)
        assert result["total_reviews"] == 0
        assert result["average_rating"] == 0.0
        assert result["reviews"] == []

    def test_stats_computed(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        session = completed_reservation["session"]
        _make_review(db, res.id, sample_users["customer"].id, rating=4)
        result = get_session_reviews(session.id)
        assert result["total_reviews"] == 1
        assert result["average_rating"] == 4.0
        assert result["rating_distribution"][4] == 1

    def test_sort_highest(self, db, completed_reservation, sample_users, sample_room):
        """Two reservations for same session, different users → sorted highest first."""
        from app.models.studio import Reservation
        session = completed_reservation["session"]
        res1 = completed_reservation["reservation"]

        # Second user (staff) completes the same session
        res2 = Reservation(
            user_id=sample_users["staff"].id,
            session_id=session.id,
            status="completed",
        )
        db.session.add(res2)
        db.session.commit()

        _make_review(db, res1.id, sample_users["customer"].id, rating=2)
        _make_review(db, res2.id, sample_users["staff"].id, rating=5)

        result = get_session_reviews(session.id, sort="highest")
        ratings = [r["rating"] for r in result["reviews"]]
        assert ratings == sorted(ratings, reverse=True)


# ── TestFileAppeal ─────────────────────────────────────────────────────────────

class TestFileAppeal:
    def test_file_appeal_success(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = file_appeal(
            review_id=review.id,
            user_id=sample_users["staff"].id,
            reason="This review contains false statements that are defamatory.",
        )
        assert result["success"] is True
        assert "appeal_id" in result
        assert "deadline" in result

    def test_short_reason_rejected(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = file_appeal(
            review_id=review.id,
            user_id=sample_users["staff"].id,
            reason="Too short.",
        )
        assert result["success"] is False
        assert "20" in result["reason"] or "characters" in result["reason"].lower()

    def test_cannot_dispute_own_review(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = file_appeal(
            review_id=review.id,
            user_id=sample_users["customer"].id,
            reason="I want to remove my own review via dispute mechanism here.",
        )
        assert result["success"] is False

    def test_duplicate_appeal_blocked(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        long_reason = "This review contains false statements that are defamatory."
        file_appeal(review_id=review.id, user_id=sample_users["staff"].id, reason=long_reason)
        result = file_appeal(review_id=review.id, user_id=sample_users["staff"].id, reason=long_reason)
        assert result["success"] is False
        assert "pending" in result["reason"].lower()

    def test_deadline_skips_weekend(self, db, completed_reservation, sample_users):
        """Business day deadline should be >= 5 calendar days but skip weekends."""
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = file_appeal(
            review_id=review.id,
            user_id=sample_users["staff"].id,
            reason="This review contains false statements that are defamatory.",
        )
        assert result["success"] is True
        # Deadline format MM/DD/YYYY
        deadline_str = result["deadline"]
        deadline = datetime.strptime(deadline_str, "%m/%d/%Y")
        now = datetime.utcnow()
        assert (deadline - now).days >= 4  # at least 5 cal days


# ── TestResolveAppeal ─────────────────────────────────────────────────────────

class TestResolveAppeal:
    def _setup_appeal(self, db, completed_reservation, sample_users):
        from app.models.review import Appeal
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        now = datetime.utcnow()
        appeal = Appeal(
            review_id=review.id,
            user_id=sample_users["staff"].id,
            reason="Reason that has enough characters to be valid.",
            status="pending",
            deadline=now + timedelta(days=5),
        )
        db.session.add(appeal)
        db.session.commit()
        return review, appeal

    def test_uphold_removes_review(self, db, completed_reservation, sample_users):
        review, appeal = self._setup_appeal(db, completed_reservation, sample_users)
        result = resolve_appeal(
            appeal_id=appeal.id,
            admin_id=sample_users["admin"].id,
            decision="upheld",
            resolution_text="Review violates community guidelines.",
        )
        assert result["success"] is True
        db.session.refresh(review)
        assert review.status == "removed"

    def test_uphold_deducts_credit(self, db, completed_reservation, sample_users):
        review, appeal = self._setup_appeal(db, completed_reservation, sample_users)
        customer = sample_users["customer"]
        original_score = customer.credit_score
        resolve_appeal(
            appeal_id=appeal.id,
            admin_id=sample_users["admin"].id,
            decision="upheld",
            resolution_text="Review violates community guidelines.",
        )
        db.session.refresh(customer)
        assert customer.credit_score == original_score - 5

    def test_reject_restores_review(self, db, completed_reservation, sample_users):
        review, appeal = self._setup_appeal(db, completed_reservation, sample_users)
        review.status = "disputed"
        db.session.commit()
        result = resolve_appeal(
            appeal_id=appeal.id,
            admin_id=sample_users["admin"].id,
            decision="rejected",
            resolution_text="Review does not violate our guidelines.",
        )
        assert result["success"] is True
        db.session.refresh(review)
        assert review.status == "active"

    def test_already_resolved_fails(self, db, completed_reservation, sample_users):
        review, appeal = self._setup_appeal(db, completed_reservation, sample_users)
        resolve_appeal(
            appeal_id=appeal.id,
            admin_id=sample_users["admin"].id,
            decision="rejected",
            resolution_text="Review does not violate our guidelines.",
        )
        result = resolve_appeal(
            appeal_id=appeal.id,
            admin_id=sample_users["admin"].id,
            decision="upheld",
            resolution_text="Changed my mind now after further review.",
        )
        assert result["success"] is False

    def test_short_resolution_text_fails(self, db, completed_reservation, sample_users):
        review, appeal = self._setup_appeal(db, completed_reservation, sample_users)
        result = resolve_appeal(
            appeal_id=appeal.id,
            admin_id=sample_users["admin"].id,
            decision="upheld",
            resolution_text="OK",
        )
        assert result["success"] is False

    def test_overdue_appeal_cannot_be_resolved(self, db, completed_reservation, sample_users):
        review, appeal = self._setup_appeal(db, completed_reservation, sample_users)
        appeal.deadline = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

        result = resolve_appeal(
            appeal_id=appeal.id,
            admin_id=sample_users["admin"].id,
            decision="upheld",
            resolution_text="Valid resolution text for overdue appeal.",
        )
        assert result["success"] is False
        assert "5-business-day" in result["reason"]


# ── TestUpdateReview ───────────────────────────────────────────────────────────

class TestUpdateReview:
    def test_author_can_update(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = update_review(
            review_id=review.id,
            user_id=sample_users["customer"].id,
            rating=3,
            text="Updated text.",
        )
        assert result["success"] is True
        db.session.refresh(review)
        assert review.rating == 3

    def test_non_author_blocked(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = update_review(
            review_id=review.id,
            user_id=sample_users["staff"].id,
            rating=1,
        )
        assert result["success"] is False

    def test_filtered_text_rejected(self, db, completed_reservation, sample_users, sample_filter):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = update_review(
            review_id=review.id,
            user_id=sample_users["customer"].id,
            text="This was a badword experience.",
        )
        assert result["success"] is False


# ── TestDeleteReview ───────────────────────────────────────────────────────────

class TestDeleteReview:
    def test_author_soft_deletes(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = delete_review(review_id=review.id, user_id=sample_users["customer"].id)
        assert result["success"] is True
        db.session.refresh(review)
        assert review.status == "removed"

    def test_admin_can_delete(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = delete_review(review_id=review.id, user_id=sample_users["admin"].id)
        assert result["success"] is True

    def test_third_party_blocked(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        result = delete_review(review_id=review.id, user_id=sample_users["staff"].id)
        assert result["success"] is False


# ── TestGetUserReviews ─────────────────────────────────────────────────────────

class TestGetUserReviews:
    def test_written_included(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        _make_review(db, res.id, sample_users["customer"].id)
        data = get_user_reviews(sample_users["customer"].id)
        assert len(data["written"]) == 1

    def test_received_for_instructor(self, db, completed_reservation, sample_users):
        res = completed_reservation["reservation"]
        _make_review(db, res.id, sample_users["customer"].id)
        # staff is the instructor of the session
        data = get_user_reviews(sample_users["staff"].id)
        assert len(data["received"]) >= 1

    def test_appeals_included(self, db, completed_reservation, sample_users):
        from app.models.review import Appeal
        res = completed_reservation["reservation"]
        review = _make_review(db, res.id, sample_users["customer"].id)
        now = datetime.utcnow()
        appeal = Appeal(
            review_id=review.id,
            user_id=sample_users["staff"].id,
            reason="Reason that has enough characters to pass validation check.",
            status="pending",
            deadline=now + timedelta(days=5),
        )
        db.session.add(appeal)
        db.session.commit()
        data = get_user_reviews(sample_users["staff"].id)
        assert len(data["appeals"]) >= 1


# ── TestBusinessDayHelper ─────────────────────────────────────────────────────

class TestBusinessDayHelper:
    def test_weekday_start(self):
        # Monday + 5 business days = next Monday
        monday = datetime(2026, 3, 2)  # A known Monday
        result = _add_business_days(monday, 5)
        assert result.weekday() == 0  # Monday

    def test_friday_start(self):
        # Friday + 1 business day = next Monday
        friday = datetime(2026, 3, 6)  # A known Friday
        result = _add_business_days(friday, 1)
        assert result.weekday() == 0  # Monday

    def test_no_weekend_in_range(self):
        # Any result should never land on Saturday or Sunday
        for day_offset in range(7):
            start = datetime(2026, 3, 2) + timedelta(days=day_offset)
            result = _add_business_days(start, 5)
            assert result.weekday() < 5, f"Landed on weekend starting from {start}"
