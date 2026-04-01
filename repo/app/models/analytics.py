from datetime import datetime
from ..extensions import db


class AnalyticsEvent(db.Model):
    __tablename__ = "analytics_events"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), nullable=False)
    # "page_view", "heartbeat", "booking_start", "booking_complete", "custom"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    session_id = db.Column(db.String(100), nullable=True)  # browser session token
    page = db.Column(db.String(500), nullable=True)
    data = db.Column(db.Text, default="{}")  # JSON
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="analytics_events")

    def __repr__(self):
        return f"<AnalyticsEvent {self.event_type} @ {self.created_at}>"


class CreditHistory(db.Model):
    __tablename__ = "credit_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_type = db.Column(db.String(30), nullable=False)
    # "on_time", "late_cancel", "no_show", "dispute_upheld"
    points = db.Column(db.Integer, nullable=False)  # positive or negative
    reference_id = db.Column(db.Integer, nullable=True)  # reservation or appeal ID
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="credit_history")

    def __repr__(self):
        sign = "+" if self.points >= 0 else ""
        return f"<CreditHistory user={self.user_id} {sign}{self.points} [{self.event_type}]>"


class MonthlyAnalyticsSummary(db.Model):
    """Pre-aggregated monthly rollup produced by the data-cleanup CLI."""
    __tablename__ = "monthly_analytics_summaries"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)   # 1-12
    total_page_views = db.Column(db.Integer, default=0)
    unique_visitors = db.Column(db.Integer, default=0)
    total_bookings = db.Column(db.Integer, default=0)
    cancellations = db.Column(db.Integer, default=0)
    no_shows = db.Column(db.Integer, default=0)
    avg_dwell_seconds = db.Column(db.Float, default=0.0)
    total_reviews = db.Column(db.Integer, default=0)
    avg_rating = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("year", "month", name="uq_monthly_summary_ym"),
    )

    def __repr__(self):
        return f"<MonthlyAnalyticsSummary {self.year}-{self.month:02d}>"
