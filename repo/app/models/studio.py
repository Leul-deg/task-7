from datetime import datetime
from ..extensions import db


class Resource(db.Model):
    __tablename__ = "resources"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)  # "room", "instructor", "equipment"
    name = db.Column(db.String(100), nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sessions_as_room = db.relationship("StudioSession", back_populates="room", foreign_keys="StudioSession.room_id", lazy="dynamic")

    def __repr__(self):
        return f"<Resource {self.name} [{self.type}]>"


class StudioSession(db.Model):
    __tablename__ = "studio_sessions"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    equipment_ids = db.Column(db.Text, default="[]")  # JSON list of Resource IDs
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    instructor = db.relationship("User", foreign_keys=[instructor_id])
    room = db.relationship("Resource", back_populates="sessions_as_room", foreign_keys=[room_id])
    reservations = db.relationship("Reservation", back_populates="session", lazy="dynamic")
    waitlist = db.relationship("Waitlist", back_populates="session", lazy="dynamic")

    def __repr__(self):
        return f"<StudioSession '{self.title}' @ {self.start_time}>"


class Reservation(db.Model):
    __tablename__ = "reservations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("studio_sessions.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="confirmed")
    # "confirmed", "canceled", "rescheduled", "no_show", "completed"
    breach_flag = db.Column(db.Boolean, default=False)
    original_reservation_id = db.Column(db.Integer, db.ForeignKey("reservations.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="reservations", foreign_keys=[user_id])
    session = db.relationship("StudioSession", back_populates="reservations")
    original_reservation = db.relationship("Reservation", remote_side=[id])
    check_in = db.relationship("CheckIn", back_populates="reservation", uselist=False)
    review = db.relationship("Review", back_populates="reservation", uselist=False)

    # Partial unique constraint: only one confirmed reservation per (user, session)
    __table_args__ = (
        db.Index(
            "uq_user_session_confirmed",
            "user_id",
            "session_id",
            unique=True,
            sqlite_where=db.text("status = 'confirmed'"),
        ),
    )

    def __repr__(self):
        return f"<Reservation user={self.user_id} session={self.session_id} [{self.status}]>"


class Waitlist(db.Model):
    __tablename__ = "waitlist"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("studio_sessions.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="waitlist_entries")
    session = db.relationship("StudioSession", back_populates="waitlist")

    def __repr__(self):
        return f"<Waitlist user={self.user_id} session={self.session_id} pos={self.position}>"


class CheckIn(db.Model):
    __tablename__ = "check_ins"

    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(db.Integer, db.ForeignKey("reservations.id"), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    checked_in_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)

    reservation = db.relationship("Reservation", back_populates="check_in")
    staff = db.relationship("User", back_populates="check_ins_performed", foreign_keys=[staff_id])

    def __repr__(self):
        return f"<CheckIn reservation={self.reservation_id} by staff={self.staff_id}>"
