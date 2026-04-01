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
from app.models.ops import AlertThreshold, FeatureFlag


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


# ── TestAlertsAPI ─────────────────────────────────────────────────────────────

class TestAlertsAPI:
    def test_list_alerts_admin(self, client, db, sample_users):
        _login(client, "testadmin")
        resp = client.get("/admin/alerts")
        assert resp.status_code == 200

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
        _login(client, "testadmin")
        resp = client.get("/admin/flags")
        assert resp.status_code == 200

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
