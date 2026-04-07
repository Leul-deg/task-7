from datetime import datetime
from ..extensions import db


class FeatureFlag(db.Model):
    __tablename__ = "feature_flags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_enabled = db.Column(db.Boolean, default=False)
    canary_staff_ids = db.Column(db.Text, default="[]")  # JSON list of User IDs
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        state = "ON" if self.is_enabled else "OFF"
        return f"<FeatureFlag {self.name} [{state}]>"


class Backup(db.Model):
    __tablename__ = "backups"

    id = db.Column(db.Integer, primary_key=True)
    backup_type = db.Column(db.String(20), nullable=False)  # "database", "files"
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="completed")
    # "completed", "failed", "validated", "restored"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Backup {self.backup_type} [{self.status}] @ {self.created_at}>"


class LogEntry(db.Model):
    __tablename__ = "log_entries"

    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), nullable=False)
    # "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    source = db.Column(db.String(50), nullable=False)  # "client", "server"
    message = db.Column(db.Text, nullable=False)
    request_id = db.Column(db.String(36), nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    endpoint = db.Column(db.String(200), nullable=True)
    method = db.Column(db.String(10), nullable=True)
    status_code = db.Column(db.Integer, nullable=True)
    latency_ms = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<LogEntry [{self.level}] {self.message[:60]}>"


class AlertThreshold(db.Model):
    __tablename__ = "alert_thresholds"

    id = db.Column(db.Integer, primary_key=True)
    metric = db.Column(db.String(50), nullable=False)
    # "error_rate", "latency_p99", "disk_usage"
    operator = db.Column(db.String(5), nullable=False)  # ">", "<", ">=", "<="
    threshold_value = db.Column(db.Float, nullable=False)
    window_minutes = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    last_triggered = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AlertThreshold {self.metric} {self.operator} {self.threshold_value}>"
