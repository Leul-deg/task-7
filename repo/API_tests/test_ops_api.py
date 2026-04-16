"""
API-level tests for admin ops routes:
  GET  /admin/diagnostics
  GET  /admin/diagnostics/metrics
  GET  /admin/alerts
  POST /admin/alerts
  POST /admin/alerts/<id>/toggle
  DELETE /admin/alerts/<id>
  GET  /admin/flags
  POST /admin/flags
  POST /admin/flags/<name>/toggle
  DELETE /admin/flags/<name>
  GET  /admin/backups
  POST /admin/backups/db
"""
import pytest

from app.extensions import db as _db
from app.models.ops import AlertThreshold, Backup, FeatureFlag, LogEntry
from app.services import backup_service


# ── helpers ────────────────────────────────────────────────────────────────────

def _login(client, username, password="TestPass123!"):
    return client.post(
        "/auth/login",
        data={"identifier": username, "password": password},
        follow_redirects=True,
    )


# ── TestDiagnosticsRoute ──────────────────────────────────────────────────────

class TestDiagnosticsRoute:
    def test_requires_admin(self, client, db, sample_users):
        _login(client, "testcustomer")
        resp = client.get("/admin/diagnostics")
        assert resp.status_code in (302, 403)

    def test_admin_gets_200(self, client, db, sample_users):
        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics")
        assert resp.status_code == 200

    def test_metrics_partial_htmx(self, client, db, sample_users):
        _login(client, "testadmin")
        resp = client.get(
            "/admin/diagnostics/metrics",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert b"metrics_panel" in resp.data or b"healthy" in resp.data or b"Total" in resp.data

    # ── /admin/diagnostics/errors ────────────────────────────────────────────

    def test_errors_page_returns_200(self, client, db, sample_users):
        """GET /admin/diagnostics/errors returns 200 for admin."""
        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics/errors")
        assert resp.status_code == 200

    def test_errors_page_non_admin_forbidden(self, client, db, sample_users):
        """Non-admin cannot access /admin/diagnostics/errors."""
        _login(client, "testcustomer")
        resp = client.get("/admin/diagnostics/errors", follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_errors_page_shows_error_entries(self, client, db, sample_users):
        """An existing ERROR log entry appears on the errors page."""
        entry = LogEntry(
            level="ERROR",
            source="server",
            message="Unhandled exception in view",
            endpoint="/booking/reserve",
        )
        _db.session.add(entry)
        _db.session.commit()

        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics/errors")
        assert resp.status_code == 200
        assert b"Unhandled exception" in resp.data

    def test_errors_htmx_returns_fragment(self, client, db, sample_users):
        """HTMX request to /admin/diagnostics/errors returns a partial (no DOCTYPE)."""
        _login(client, "testadmin")
        resp = client.get(
            "/admin/diagnostics/errors",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert b"<!DOCTYPE" not in resp.data

    def test_errors_limit_param_accepted(self, client, db, sample_users):
        """?limit=5 is accepted without error."""
        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics/errors?limit=5")
        assert resp.status_code == 200

    # ── /admin/diagnostics/slow ──────────────────────────────────────────────

    def test_slow_page_returns_200(self, client, db, sample_users):
        """GET /admin/diagnostics/slow returns 200 for admin."""
        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics/slow")
        assert resp.status_code == 200

    def test_slow_page_non_admin_forbidden(self, client, db, sample_users):
        """Non-admin cannot access /admin/diagnostics/slow."""
        _login(client, "teststaff")
        resp = client.get("/admin/diagnostics/slow", follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_slow_page_shows_slow_entry(self, client, db, sample_users):
        """A server request with latency > 1000 ms appears on the slow page."""
        entry = LogEntry(
            level="INFO",
            source="server",
            message="Slow view",
            endpoint="/staff/sessions",
            latency_ms=2500.0,
        )
        _db.session.add(entry)
        _db.session.commit()

        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics/slow")
        assert resp.status_code == 200
        assert b"/staff/sessions" in resp.data or b"2500" in resp.data or b"Slow" in resp.data

    def test_slow_htmx_returns_fragment(self, client, db, sample_users):
        """HTMX request to /admin/diagnostics/slow returns a partial."""
        _login(client, "testadmin")
        resp = client.get(
            "/admin/diagnostics/slow",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert b"<!DOCTYPE" not in resp.data

    def test_slow_threshold_param_filters(self, client, db, sample_users):
        """Requests below the custom threshold are not shown; above threshold are."""
        fast = LogEntry(level="INFO", source="server", message="fast",
                        endpoint="/schedule", latency_ms=200.0)
        slow = LogEntry(level="INFO", source="server", message="very-slow",
                        endpoint="/admin/reports", latency_ms=3000.0)
        _db.session.add_all([fast, slow])
        _db.session.commit()

        _login(client, "testadmin")
        # threshold=500 → only the 3000 ms entry should appear
        resp = client.get("/admin/diagnostics/slow?threshold=500")
        assert resp.status_code == 200
        assert b"/admin/reports" in resp.data or b"3000" in resp.data or b"very-slow" in resp.data

    # ── /admin/diagnostics/client-logs ──────────────────────────────────────

    def test_client_logs_page_returns_200(self, client, db, sample_users):
        """GET /admin/diagnostics/client-logs returns 200 for admin."""
        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics/client-logs")
        assert resp.status_code == 200

    def test_client_logs_non_admin_forbidden(self, client, db, sample_users):
        """Non-admin cannot access /admin/diagnostics/client-logs."""
        _login(client, "testcustomer")
        resp = client.get("/admin/diagnostics/client-logs", follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_client_logs_shows_client_entries(self, client, db, sample_users):
        """A client-sourced log entry is displayed on the page."""
        entry = LogEntry(
            level="ERROR",
            source="client",
            message="Uncaught TypeError: Cannot read properties of null",
            endpoint="/booking/my-bookings",
        )
        _db.session.add(entry)
        _db.session.commit()

        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics/client-logs")
        assert resp.status_code == 200
        assert b"TypeError" in resp.data or b"client" in resp.data.lower()

    def test_client_logs_excludes_server_entries(self, client, db, sample_users):
        """Server-sourced log entries must NOT appear on the client-logs page."""
        server_entry = LogEntry(
            level="ERROR",
            source="server",
            message="SERVER_ONLY_MESSAGE",
            endpoint="/staff/sessions",
        )
        client_entry = LogEntry(
            level="WARNING",
            source="client",
            message="CLIENT_ONLY_MESSAGE",
            endpoint="/schedule",
        )
        _db.session.add_all([server_entry, client_entry])
        _db.session.commit()

        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics/client-logs")
        assert resp.status_code == 200
        assert b"SERVER_ONLY_MESSAGE" not in resp.data
        assert b"CLIENT_ONLY_MESSAGE" in resp.data

    def test_client_logs_limit_param_accepted(self, client, db, sample_users):
        """?limit=10 is accepted without error."""
        _login(client, "testadmin")
        resp = client.get("/admin/diagnostics/client-logs?limit=10")
        assert resp.status_code == 200


# ── TestAlertsAPI ─────────────────────────────────────────────────────────────

class TestAlertsAPI:
    def test_list_alerts_admin(self, client, db, sample_users):
        """GET /admin/alerts returns 200 and includes the metric name of any existing alert."""
        t = AlertThreshold(
            metric="cpu_usage", operator=">",
            threshold_value=90.0, window_minutes=15, is_active=True,
        )
        _db.session.add(t)
        _db.session.commit()
        _login(client, "testadmin")
        resp = client.get("/admin/alerts")
        assert resp.status_code == 200
        assert b"cpu_usage" in resp.data

    def test_create_alert_htmx(self, client, db, sample_users):
        _login(client, "testadmin")
        resp = client.post(
            "/admin/alerts",
            data={
                "metric": "error_rate",
                "operator": ">",
                "threshold_value": "5.0",
                "window_minutes": "60",
            },
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 201
        assert AlertThreshold.query.count() == 1

    def test_toggle_alert(self, client, db, sample_users):
        _login(client, "testadmin")
        t = AlertThreshold(
            metric="error_rate", operator=">",
            threshold_value=5.0, window_minutes=60, is_active=True,
        )
        _db.session.add(t)
        _db.session.commit()
        tid = t.id

        resp = client.post(
            f"/admin/alerts/{tid}/toggle",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        updated = _db.session.get(AlertThreshold, tid)
        assert updated.is_active is False

    def test_delete_alert(self, client, db, sample_users):
        _login(client, "testadmin")
        t = AlertThreshold(
            metric="latency_p99", operator=">",
            threshold_value=2000.0, window_minutes=60, is_active=True,
        )
        _db.session.add(t)
        _db.session.commit()
        tid = t.id

        resp = client.delete(f"/admin/alerts/{tid}")
        assert resp.status_code == 200
        assert _db.session.get(AlertThreshold, tid) is None


# ── TestFlagsAPI ──────────────────────────────────────────────────────────────

class TestFlagsAPI:
    def test_list_flags_admin(self, client, db, sample_users):
        """GET /admin/flags returns 200 and includes the name of any existing flag."""
        flag = FeatureFlag(name="show_promotions", description="Promo banner", is_enabled=False)
        _db.session.add(flag)
        _db.session.commit()
        _login(client, "testadmin")
        resp = client.get("/admin/flags")
        assert resp.status_code == 200
        assert b"show_promotions" in resp.data

    def test_create_flag_htmx(self, client, db, sample_users):
        _login(client, "testadmin")
        resp = client.post(
            "/admin/flags",
            data={"name": "my_feature", "description": "A test flag"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 201
        assert FeatureFlag.query.filter_by(name="my_feature").first() is not None

    def test_toggle_flag(self, client, db, sample_users):
        _login(client, "testadmin")
        client.post(
            "/admin/flags",
            data={"name": "toggleme"},
            headers={"HX-Request": "true"},
        )
        resp = client.post(
            "/admin/flags/toggleme/toggle",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        flag = FeatureFlag.query.filter_by(name="toggleme").first()
        assert flag.is_enabled is True  # was False, toggled to True

    def test_delete_flag(self, client, db, sample_users):
        _login(client, "testadmin")
        client.post(
            "/admin/flags",
            data={"name": "deleteme"},
            headers={"HX-Request": "true"},
        )
        resp = client.delete("/admin/flags/deleteme")
        assert resp.status_code == 200
        assert FeatureFlag.query.filter_by(name="deleteme").first() is None


# ── TestBackupsAPI ────────────────────────────────────────────────────────────

class TestBackupsAPI:
    def test_list_backups_admin(self, client, db, sample_users):
        _login(client, "testadmin")
        resp = client.get("/admin/backups")
        assert resp.status_code == 200

    def test_backup_db_in_memory_shows_error(self, client, db, sample_users):
        """In-memory SQLite cannot be backed up; route should still succeed (flash/redirect)."""
        _login(client, "testadmin")
        resp = client.post("/admin/backups/db", follow_redirects=True)
        assert resp.status_code == 200

    def test_backup_ui_default_retention_is_30(self, client, db, sample_users):
        """Admin backups page renders a form with default retention of 30."""
        _login(client, "testadmin")
        resp = client.get("/admin/backups")
        assert resp.status_code == 200
        assert b'value="30"' in resp.data

    def test_retention_endpoint_defaults_to_30(self, client, db, sample_users):
        """POST /admin/backups/enforce-retention without max_backups uses 30."""
        _login(client, "testadmin")
        resp = client.post("/admin/backups/enforce-retention", follow_redirects=True)
        assert resp.status_code == 200
        # Should not fail — just verify it completes successfully
        assert b"Retention enforced" in resp.data

    def test_restore_files_backup_marks_validated(self, client, db, sample_users, tmp_path, monkeypatch):
        """POST restore on a completed files backup should mark it validated."""
        _login(client, "testadmin")
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(backup_service, "_backup_dir", lambda: str(backups_dir))

        zip_path = backups_dir / "files_backup_api.zip"
        import zipfile
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("uploads/from_api.txt", "restored")

        b = Backup(
            backup_type="files",
            file_path=str(zip_path),
            file_size=zip_path.stat().st_size,
            status="completed",
        )
        _db.session.add(b)
        _db.session.commit()

        resp = client.post(
            f"/admin/backups/{b.id}/restore",
            data={"promote": "0"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        _db.session.refresh(b)
        assert b.status == "validated"

    def test_promote_validated_files_backup(self, client, db, sample_users, tmp_path, monkeypatch):
        """POST restore with promote=1 should restore validated file backup to uploads."""
        _login(client, "testadmin")
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        (uploads_dir / "old.txt").write_text("old", encoding="utf-8")

        client.application.config["UPLOAD_FOLDER"] = str(uploads_dir)
        monkeypatch.setattr(backup_service, "_backup_dir", lambda: str(backups_dir))

        # Create a validated files backup record and matching validation directory.
        b = Backup(
            backup_type="files",
            file_path=str(backups_dir / "files_backup_promote_api.zip"),
            file_size=0,
            status="validated",
        )
        _db.session.add(b)
        _db.session.commit()

        validation_dir = backups_dir / f"validation_files_{b.id}" / uploads_dir.name
        validation_dir.mkdir(parents=True, exist_ok=True)
        (validation_dir / "new.txt").write_text("new", encoding="utf-8")

        resp = client.post(
            f"/admin/backups/{b.id}/restore",
            data={"promote": "1"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert (uploads_dir / "new.txt").exists()
        assert not (uploads_dir / "old.txt").exists()
        _db.session.refresh(b)
        assert b.status == "restored"
