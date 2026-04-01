from datetime import datetime
from flask_login import UserMixin
from ..extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")
    credit_score = db.Column(db.Integer, default=100)
    is_active = db.Column(db.Boolean, default=True)
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    login_attempts = db.relationship("LoginAttempt", back_populates="user", lazy="dynamic")
    reservations = db.relationship("Reservation", back_populates="user", foreign_keys="Reservation.user_id", lazy="dynamic")
    waitlist_entries = db.relationship("Waitlist", back_populates="user", lazy="dynamic")
    check_ins_performed = db.relationship("CheckIn", back_populates="staff", foreign_keys="CheckIn.staff_id", lazy="dynamic")
    authored_content = db.relationship("Content", back_populates="author", foreign_keys="Content.author_id", lazy="dynamic")
    content_versions = db.relationship("ContentVersion", back_populates="created_by_user", foreign_keys="ContentVersion.created_by", lazy="dynamic")
    reviews = db.relationship("Review", back_populates="user", foreign_keys="Review.user_id", lazy="dynamic")
    filed_appeals = db.relationship("Appeal", back_populates="filer", foreign_keys="Appeal.user_id", lazy="dynamic")
    resolved_appeals = db.relationship("Appeal", back_populates="admin", foreign_keys="Appeal.admin_id", lazy="dynamic")
    analytics_events = db.relationship("AnalyticsEvent", back_populates="user", lazy="dynamic")
    credit_history = db.relationship("CreditHistory", back_populates="user", lazy="dynamic")

    VALID_ROLES = ("customer", "staff", "editor", "admin")

    def __repr__(self):
        return f"<User {self.username} [{self.role}]>"

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    # Flask-Login requires is_active as property; already a column, so override getter
    def get_id(self) -> str:
        return str(self.id)


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    success = db.Column(db.Boolean, nullable=False)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="login_attempts")

    def __repr__(self):
        result = "OK" if self.success else "FAIL"
        return f"<LoginAttempt user={self.user_id} {result} @ {self.attempted_at}>"
