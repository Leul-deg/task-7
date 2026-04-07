from datetime import datetime
from ..extensions import db


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(db.Integer, db.ForeignKey("reservations.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1–5
    tags = db.Column(db.Text, default="[]")  # JSON list
    text = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")
    # "active", "disputed", "resolved", "removed"
    reviewer_role = db.Column(db.String(20), nullable=False)  # "customer" or "staff"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reservation = db.relationship("Reservation", back_populates="reviews")
    user = db.relationship("User", back_populates="reviews", foreign_keys=[user_id])
    images = db.relationship("ReviewImage", back_populates="review", lazy="dynamic")
    appeals = db.relationship("Appeal", back_populates="review", lazy="dynamic")

    def __repr__(self):
        return f"<Review reservation={self.reservation_id} rating={self.rating}>"

    __table_args__ = (
        db.UniqueConstraint("reservation_id", "user_id", name="uq_review_reservation_user"),
    )


class ReviewImage(db.Model):
    __tablename__ = "review_images"

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("reviews.id"), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)  # SHA-256
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    review = db.relationship("Review", back_populates="images")

    def __repr__(self):
        return f"<ReviewImage review={self.review_id}>"


class Appeal(db.Model):
    __tablename__ = "appeals"

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("reviews.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    # "pending", "upheld", "rejected"
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    resolution_text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    deadline = db.Column(db.DateTime, nullable=False)  # Set to created_at + 5 business days at insert

    review = db.relationship("Review", back_populates="appeals")
    filer = db.relationship("User", back_populates="filed_appeals", foreign_keys=[user_id])
    admin = db.relationship("User", back_populates="resolved_appeals", foreign_keys=[admin_id])

    def __repr__(self):
        return f"<Appeal review={self.review_id} [{self.status}]>"
