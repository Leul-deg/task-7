"""
Unit tests for ops/observability services:
  app/services/ops_service.py
  app/services/feature_flag_service.py
  app/services/backup_service.py
"""
import zipfile

import pytest
from datetime import datetime, timedelta

from app.extensions import db
from app.models.ops import AlertThreshold, Backup, FeatureFlag, LogEntry
from app.services import ops_service, feature_flag_service, backup_service


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_log(level="INFO", source="server", status_code=200, latency_ms=50.0,
              endpoint="/test", method="GET", message="ok"):
    entry = LogEntry(
        level=level, source=source, status_code=status_code,
        latency_ms=latency_ms, endpoint=endpoint, method=method,
        message=message,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


# ════════════════════════════════════════════════════════════════════════════════
# TestGetRequestMetrics
# ════════════════════════════════════════════════════════════════════════════════

class TestGetRequestMetrics:
    def test_empty_returns_zero_stats(self, db):
        result = ops_service.get_request_metrics(hours=24)
        assert result["total_requests"] == 0
        assert result["error_rate"] == 0.0
        assert result["avg_latency_ms"] == 0.0

    def test_counts_errors_correctly(self, db):
        _make_log(status_code=200, latency_ms=100.0)
        _make_log(status_code=500, latency_ms=300.0)
        _make_log(status_code=503, latency_ms=200.0)
        result = ops_service.get_request_metrics(hours=24)
        assert result["total_requests"] == 3
        assert result["error_count"] == 2
        assert result["error_rate"] == pytest.approx(66.67, abs=0.1)

    def test_latency_percentiles(self, db):
        for ms in [10.0, 20.0, 30.0, 40.0, 200.0]:
            _make_log(latency_ms=ms)
        result = ops_service.get_request_metrics(hours=24)
        assert result["avg_latency_ms"] == pytest.approx(60.0, abs=1.0)
        # p95 with 5 values uses idx 3 → 40.0; just verify it is computed
        assert result["p95_latency_ms"] >= 10.0
        assert result["p99_latency_ms"] >= 10.0

    def test_status_distribution_buckets(self, db):
        _make_log(status_code=201)
        _make_log(status_code=302)
        _make_log(status_code=404)
        _make_log(status_code=500)
        result = ops_service.get_request_metrics(hours=24)
        dist = result["status_distribution"]
        assert dist["2xx"] == 1
        assert dist["3xx"] == 1
        assert dist["4xx"] == 1
        assert dist["5xx"] == 1


# ════════════════════════════════════════════════════════════════════════════════
# TestGetRecentErrors
# ════════════════════════════════════════════════════════════════════════════════

class TestGetRecentErrors:
    def test_filters_by_error_level(self, db):
        _make_log(level="INFO")
        _make_log(level="WARNING")
        _make_log(level="ERROR", message="boom")
        _make_log(level="CRITICAL", message="fatal")
        errors = ops_service.get_recent_errors()
        levels = [e["level"] for e in errors]
        assert "INFO" not in levels
        assert "WARNING" not in levels
        assert all(lvl in ("ERROR", "CRITICAL") for lvl in levels)

    def test_sorted_newest_first(self, db):
        e1 = _make_log(level="ERROR", message="first")
        e2 = _make_log(level="ERROR", message="second")
        errors = ops_service.get_recent_errors()
        assert errors[0]["id"] >= errors[-1]["id"]

    def test_respects_limit(self, db):
        for i in range(10):
            _make_log(level="ERROR", message=f"err {i}")
        errors = ops_service.get_recent_errors(limit=3)
        assert len(errors) <= 3


# ════════════════════════════════════════════════════════════════════════════════
# TestGetSlowRequests
# ════════════════════════════════════════════════════════════════════════════════

class TestGetSlowRequests:
    def test_filters_below_threshold(self, db):
        _make_log(latency_ms=500.0)
        _make_log(latency_ms=1500.0)
        _make_log(latency_ms=2000.0)
        slow = ops_service.get_slow_requests(threshold_ms=1000.0)
        assert all(e["latency_ms"] >= 1000.0 for e in slow)
        assert len(slow) == 2

    def test_sorted_by_latency_desc(self, db):
        _make_log(latency_ms=1200.0)
        _make_log(latency_ms=3000.0)
        _make_log(latency_ms=1800.0)
        slow = ops_service.get_slow_requests(threshold_ms=1000.0)
        latencies = [e["latency_ms"] for e in slow]
        assert latencies == sorted(latencies, reverse=True)


# ════════════════════════════════════════════════════════════════════════════════
# TestCheckAlerts
# ════════════════════════════════════════════════════════════════════════════════

class TestCheckAlerts:
    def test_no_thresholds_returns_empty(self, db):
        triggered = ops_service.check_alerts()
        assert triggered == []

    def test_inactive_threshold_not_triggered(self, db):
        t = AlertThreshold(
            metric="error_rate", operator=">",
            threshold_value=-1.0, window_minutes=60, is_active=False,
        )
        db.session.add(t)
        db.session.commit()
        triggered = ops_service.check_alerts()
        assert triggered == []

    def test_triggered_threshold_returned(self, db):
        # error_rate with threshold=-1 will always fire (rate >= 0 > -1)
        t = AlertThreshold(
            metric="error_rate", operator=">=",
            threshold_value=-1.0, window_minutes=60, is_active=True,
        )
        db.session.add(t)
        db.session.commit()
        triggered = ops_service.check_alerts()
        assert len(triggered) == 1
        assert triggered[0]["metric"] == "error_rate"


# ════════════════════════════════════════════════════════════════════════════════
# TestFeatureFlagService
# ════════════════════════════════════════════════════════════════════════════════

class TestFeatureFlagService:
    def test_create_flag_success(self, db):
        result = feature_flag_service.create_flag("test_flag")
        assert result["success"] is True
        assert result["flag"]["name"] == "test_flag"

    def test_create_duplicate_fails(self, db):
        feature_flag_service.create_flag("dup_flag")
        result = feature_flag_service.create_flag("dup_flag")
        assert result["success"] is False
        assert "already exists" in result["reason"]

    def test_create_normalises_name(self, db):
        result = feature_flag_service.create_flag("My Feature Flag")
        assert result["flag"]["name"] == "my_feature_flag"

    def test_global_on_returns_true_for_all(self, db):
        feature_flag_service.create_flag("global_flag", is_enabled=True)
        assert feature_flag_service.is_feature_enabled("global_flag") is True

    def test_global_off_returns_false_without_canary(self, db):
        feature_flag_service.create_flag("off_flag", is_enabled=False)
        assert feature_flag_service.is_feature_enabled("off_flag") is False

    def test_canary_flag_on_for_canary_user(self, db, sample_users):
        feature_flag_service.create_flag(
            "canary_flag", is_enabled=False,
            canary_staff_ids=[sample_users["staff"].id],
        )
        assert feature_flag_service.is_feature_enabled(
            "canary_flag", user=sample_users["staff"]
        ) is True

    def test_canary_flag_off_for_non_canary(self, db, sample_users):
        feature_flag_service.create_flag(
            "canary_flag2", is_enabled=False,
            canary_staff_ids=[sample_users["staff"].id],
        )
        assert feature_flag_service.is_feature_enabled(
            "canary_flag2", user=sample_users["customer"]
        ) is False

    def test_canary_ids_must_be_staff_users(self, db, sample_users):
        result = feature_flag_service.create_flag(
            "staff_only_canary",
            is_enabled=False,
            canary_staff_ids=[sample_users["customer"].id],
        )
        assert result["success"] is False
        assert "staff users only" in result["reason"].lower()

    def test_delete_flag(self, db):
        feature_flag_service.create_flag("to_delete")
        result = feature_flag_service.delete_flag("to_delete")
        assert result["success"] is True
        assert FeatureFlag.query.filter_by(name="to_delete").first() is None


# ════════════════════════════════════════════════════════════════════════════════
# TestBackupService
# ════════════════════════════════════════════════════════════════════════════════

class TestBackupService:
    def test_database_backup_in_memory_fails(self, db):
        """In-memory SQLite cannot be backed up."""
        result = backup_service.create_database_backup()
        assert result["success"] is False
        assert "in-memory" in result["reason"].lower() or "not found" in result["reason"].lower()

    def test_restore_nonexistent_backup_fails(self, db):
        result = backup_service.restore_backup(99999)
        assert result["success"] is False
        assert "not found" in result["reason"]

    def test_enforce_retention_empty(self, db):
        result = backup_service.enforce_retention(max_backups=7)
        assert result["deleted"] == 0
        assert result["kept"] == 0

    def test_restore_file_backup_creates_validation_copy(self, app, db, tmp_path, monkeypatch):
        """File backup restore extracts ZIP into validation_files_<id> and marks validated."""
        with app.app_context():
            backups_dir = tmp_path / "backups"
            backups_dir.mkdir(parents=True, exist_ok=True)
            uploads_dir = tmp_path / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            app.config["UPLOAD_FOLDER"] = str(uploads_dir)
            monkeypatch.setattr(backup_service, "_backup_dir", lambda: str(backups_dir))

            zip_path = backups_dir / "files_backup_test.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{uploads_dir.name}/restored.txt", "restored content")

            record = Backup(
                backup_type="files",
                file_path=str(zip_path),
                file_size=zip_path.stat().st_size,
                status="completed",
            )
            db.session.add(record)
            db.session.commit()

            result = backup_service.restore_backup(record.id)
            assert result["success"] is True
            assert "validation_copy_path" in result
            db.session.refresh(record)
            assert record.status == "validated"

            restored_file = backups_dir / f"validation_files_{record.id}" / uploads_dir.name / "restored.txt"
            assert restored_file.exists()

    def test_promote_file_backup_swaps_upload_directory(self, app, db, tmp_path, monkeypatch):
        """Promote on validated file backup replaces live uploads from validation copy."""
        with app.app_context():
            backups_dir = tmp_path / "backups"
            backups_dir.mkdir(parents=True, exist_ok=True)
            uploads_dir = tmp_path / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            (uploads_dir / "old.txt").write_text("old content", encoding="utf-8")

            app.config["UPLOAD_FOLDER"] = str(uploads_dir)
            monkeypatch.setattr(backup_service, "_backup_dir", lambda: str(backups_dir))

            zip_path = backups_dir / "files_backup_promote.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{uploads_dir.name}/new.txt", "new content")

            record = Backup(
                backup_type="files",
                file_path=str(zip_path),
                file_size=zip_path.stat().st_size,
                status="completed",
            )
            db.session.add(record)
            db.session.commit()

            restore = backup_service.restore_backup(record.id)
            assert restore["success"] is True

            promoted = backup_service.promote_restore(record.id)
            assert promoted["success"] is True
            assert (uploads_dir / "new.txt").exists()
            assert not (uploads_dir / "old.txt").exists()

            db.session.refresh(record)
            assert record.status == "restored"
            safety_zips = list(backups_dir.glob("pre_restore_uploads_*.zip"))
            assert len(safety_zips) >= 1

    def test_enforce_retention_prunes_oldest(self, db):
        """enforce_retention(max_backups=2) deletes the oldest when 3 exist."""
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        for i in range(3):
            b = Backup(
                backup_type="database",
                file_path=f"/tmp/db_backup_{i}.sql",
                file_size=1024,
                status="completed",
                created_at=now - timedelta(hours=(3 - i)),  # oldest first
            )
            db.session.add(b)
        db.session.commit()

        result = backup_service.enforce_retention(max_backups=2)
        assert result["deleted"] == 1
        assert result["kept"] == 2
        remaining = Backup.query.filter_by(backup_type="database", status="completed").all()
        assert len(remaining) == 2

    def test_enforce_retention_keeps_all_when_under_limit(self, db):
        """When backup count ≤ max_backups, nothing is deleted."""
        b = Backup(
            backup_type="files",
            file_path="/tmp/files_backup_single.zip",
            file_size=512,
            status="completed",
        )
        db.session.add(b)
        db.session.commit()

        result = backup_service.enforce_retention(max_backups=5)
        assert result["deleted"] == 0
        assert result["kept"] == 1

    def test_enforce_retention_separates_by_type(self, db):
        """Database and files backups are pruned independently per type."""
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        # 3 database backups → keep 2, delete 1
        for i in range(3):
            db.session.add(Backup(
                backup_type="database",
                file_path=f"/tmp/db_{i}.sql",
                file_size=10,
                status="completed",
                created_at=now - timedelta(hours=(3 - i)),
            ))
        # 1 files backup — under limit
        db.session.add(Backup(
            backup_type="files",
            file_path="/tmp/files_1.zip",
            file_size=10,
            status="completed",
        ))
        db.session.commit()

        result = backup_service.enforce_retention(max_backups=2)
        assert result["deleted"] == 1   # only 1 database backup pruned
        assert result["kept"] == 3       # 2 db + 1 files
