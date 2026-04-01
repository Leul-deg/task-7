"""
Admin blueprint — admin-only management views.

URL layout (registered at /admin):
  GET  /admin/                                  – admin index
  GET  /admin/appeals                           – appeal dashboard
  POST /admin/appeals/<id>/resolve              – resolve an appeal
  GET  /admin/dashboard                         – analytics dashboard
  GET  /admin/reports/export                    – report config page
  POST /admin/reports/generate                  – generate CSV/JSON download

  Diagnostics
  GET  /admin/diagnostics                       – live metrics + health panel
  GET  /admin/diagnostics/metrics               – HTMX partial: request metrics
  GET  /admin/diagnostics/errors                – recent ERROR/CRITICAL entries
  GET  /admin/diagnostics/slow                  – slow requests
  GET  /admin/diagnostics/client-logs          – client-side JS errors

  Alert Thresholds
  GET  /admin/alerts                            – list thresholds
  POST /admin/alerts                            – create threshold
  POST /admin/alerts/<id>/toggle               – toggle is_active
  DELETE /admin/alerts/<id>                    – delete threshold

  Feature Flags
  GET  /admin/flags                             – list flags
  POST /admin/flags                             – create flag
  POST /admin/flags/<name>/toggle              – toggle is_enabled
  POST /admin/flags/<name>/canary              – update canary user IDs
  DELETE /admin/flags/<name>                   – delete flag

  Backups
  GET  /admin/backups                           – list backups
  POST /admin/backups/db                        – create database backup
  POST /admin/backups/files                     – create file backup
  POST /admin/backups/<id>/restore             – mark + optionally promote restore
  POST /admin/backups/enforce-retention        – prune old backups
"""
import csv
import io
import json
import logging
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request,
    make_response, redirect, url_for, flash,
)
from flask_login import current_user

from app.extensions import db
from app.models.ops import AlertThreshold, LogEntry
from app.services import (
    analytics_service, credit_service, review_service,
    ops_service, feature_flag_service, backup_service,
)
from app.utils.decorators import login_required, role_required

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_date(raw: str | None, fallback: datetime) -> datetime:
    if raw:
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return fallback


def _default_range() -> tuple[datetime, datetime]:
    end = datetime.utcnow()
    start = end - timedelta(days=30)
    return start, end


def _is_htmx() -> bool:
    return bool(request.headers.get("HX-Request"))


def _error_frag(message: str, code: int = 400):
    return render_template(
        "partials/error_fragment.html", code=code, message=message
    ), code


# ── index ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/")
@login_required
@role_required("admin")
def index():
    return render_template("admin/index.html")


# ── Appeals ───────────────────────────────────────────────────────────────────

@admin_bp.route("/appeals")
@login_required
@role_required("admin")
def appeals_dashboard():
    pending = review_service.get_pending_appeals()
    return render_template("reviews/appeals_dashboard.html", appeals=pending)


@admin_bp.route("/appeals/<int:appeal_id>/resolve", methods=["POST"])
@login_required
@role_required("admin")
def resolve_appeal(appeal_id: int):
    decision = request.form.get("decision", "").strip()
    resolution_text = request.form.get("resolution_text", "").strip()

    result = review_service.resolve_appeal(
        appeal_id=appeal_id,
        admin_id=current_user.id,
        decision=decision,
        resolution_text=resolution_text,
    )

    if result["success"]:
        return render_template(
            "partials/reviews/appeal_resolved.html",
            decision=decision,
            resolution_text=resolution_text,
            message=result["message"],
            appeal_id=appeal_id,
        ), 200

    return _error_frag(result["reason"])


# ── Analytics dashboard ───────────────────────────────────────────────────────

@admin_bp.route("/dashboard")
@login_required
@role_required("admin")
def dashboard():
    default_start, default_end = _default_range()
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), default_end)

    overview = analytics_service.get_overview_metrics(start, end)
    funnel = analytics_service.compute_booking_funnel(start, end)
    trends = analytics_service.get_booking_trends(start, end)
    review_summary = analytics_service.get_review_summary(start, end)
    content_engagement = analytics_service.get_content_engagement(start, end, limit=10)
    credit_dist = credit_service.get_credit_distribution()

    trend_max = max((t["new_bookings"] for t in trends), default=1) or 1
    funnel_max = max(funnel["view_schedule"], 1)
    rating_max = max(review_summary["rating_distribution"].values(), default=1) or 1
    credit_max = max(credit_dist.values(), default=1) or 1

    return render_template(
        "admin/dashboard.html",
        start=start.strftime("%m/%d/%Y"),
        end=end.strftime("%m/%d/%Y"),
        overview=overview,
        funnel=funnel,
        funnel_max=funnel_max,
        trends=trends,
        trend_max=trend_max,
        review_summary=review_summary,
        rating_max=rating_max,
        content_engagement=content_engagement,
        credit_dist=credit_dist,
        credit_max=credit_max,
    )


# ── Reports ───────────────────────────────────────────────────────────────────

@admin_bp.route("/reports/export")
@login_required
@role_required("admin")
def reports_export():
    default_start, default_end = _default_range()
    return render_template(
        "admin/reports.html",
        default_start=default_start.strftime("%m/%d/%Y"),
        default_end=default_end.strftime("%m/%d/%Y"),
    )


@admin_bp.route("/reports/generate", methods=["POST"])
@login_required
@role_required("admin")
def reports_generate():
    report_type = request.form.get("report_type", "overview")
    fmt = request.form.get("format", "csv").lower()
    default_start, default_end = _default_range()
    start = _parse_date(request.form.get("start"), default_start)
    end = _parse_date(request.form.get("end"), default_end)

    if report_type == "trends":
        rows = analytics_service.get_booking_trends(start, end)
    elif report_type == "funnel":
        rows = [analytics_service.compute_booking_funnel(start, end)]
    elif report_type == "reviews":
        summary = analytics_service.get_review_summary(start, end)
        dist = summary.pop("rating_distribution", {})
        rows = [{**summary, **{f"rating_{k}": v for k, v in dist.items()}}]
    elif report_type == "credit":
        rows = credit_service.get_credit_dashboard_data()
    else:
        rows = [analytics_service.get_overview_metrics(start, end)]

    filename = f"studioops_{report_type}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"

    if fmt == "json":
        response = make_response(json.dumps(rows, indent=2, default=str))
        response.headers["Content-Type"] = "application/json"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}.json"'
        return response

    if not rows:
        rows = [{}]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    return response


# ════════════════════════════════════════════════════════════════════════════════
# DIAGNOSTICS
# ════════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/diagnostics")
@login_required
@role_required("admin")
def diagnostics():
    """Live system health + request metrics dashboard."""
    hours = request.args.get("hours", 24, type=int)
    health = ops_service.get_system_health()
    metrics = ops_service.get_request_metrics(hours=hours)
    triggered = ops_service.check_alerts()
    return render_template(
        "admin/diagnostics.html",
        health=health,
        metrics=metrics,
        triggered=triggered,
        hours=hours,
    )


@admin_bp.route("/diagnostics/metrics")
@login_required
@role_required("admin")
def diagnostics_metrics():
    """HTMX partial — refreshes the metrics panel."""
    hours = request.args.get("hours", 24, type=int)
    health = ops_service.get_system_health()
    metrics = ops_service.get_request_metrics(hours=hours)
    triggered = ops_service.check_alerts()
    return render_template(
        "partials/admin/metrics_panel.html",
        health=health,
        metrics=metrics,
        triggered=triggered,
        hours=hours,
    )


@admin_bp.route("/diagnostics/errors")
@login_required
@role_required("admin")
def diagnostics_errors():
    """Recent ERROR/CRITICAL log entries."""
    limit = request.args.get("limit", 50, type=int)
    errors = ops_service.get_recent_errors(limit=limit)
    if _is_htmx():
        return render_template("partials/admin/error_rows.html", errors=errors)
    return render_template("admin/errors.html", errors=errors, limit=limit)


@admin_bp.route("/diagnostics/slow")
@login_required
@role_required("admin")
def diagnostics_slow():
    """Slow request log."""
    threshold = request.args.get("threshold", 1000.0, type=float)
    slow = ops_service.get_slow_requests(threshold_ms=threshold)
    if _is_htmx():
        return render_template("partials/admin/slow_rows.html", slow=slow, threshold=threshold)
    return render_template("admin/slow_requests.html", slow=slow, threshold=threshold)


@admin_bp.route("/diagnostics/client-logs")
@login_required
@role_required("admin")
def client_logs():
    """Client-side JS error log."""
    limit = request.args.get("limit", 50, type=int)
    entries = (
        LogEntry.query
        .filter_by(source="client")
        .order_by(LogEntry.created_at.desc())
        .limit(limit)
        .all()
    )
    logs = [
        {
            "id": e.id,
            "message": e.message,
            "endpoint": e.endpoint,
            "user_id": e.user_id,
            "date": e.created_at.strftime("%m/%d/%Y %I:%M %p") if e.created_at else None,
        }
        for e in entries
    ]
    return render_template("admin/client_logs.html", logs=logs, limit=limit)


# ════════════════════════════════════════════════════════════════════════════════
# ALERT THRESHOLDS
# ════════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/alerts", methods=["GET", "POST"])
@login_required
@role_required("admin")
def alerts():
    """List alert thresholds; POST creates a new one."""
    if request.method == "POST":
        metric = request.form.get("metric", "").strip()
        operator = request.form.get("operator", ">").strip()
        try:
            threshold_value = float(request.form.get("threshold_value", ""))
            window_minutes = int(request.form.get("window_minutes", "60"))
        except (ValueError, TypeError):
            flash("Invalid threshold value or window.", "error")
            return redirect(url_for("admin.alerts"))

        valid_metrics = ("error_rate", "latency_p99", "disk_usage")
        valid_ops = (">", "<", ">=", "<=")
        if metric not in valid_metrics or operator not in valid_ops:
            flash("Invalid metric or operator.", "error")
            return redirect(url_for("admin.alerts"))

        threshold = AlertThreshold(
            metric=metric,
            operator=operator,
            threshold_value=threshold_value,
            window_minutes=window_minutes,
            is_active=True,
        )
        db.session.add(threshold)
        db.session.commit()

        if _is_htmx():
            all_thresholds = AlertThreshold.query.order_by(AlertThreshold.created_at.desc()).all()
            return render_template("partials/admin/alert_rows.html", thresholds=all_thresholds), 201

        flash("Alert threshold created.", "success")
        return redirect(url_for("admin.alerts"))

    thresholds = AlertThreshold.query.order_by(AlertThreshold.created_at.desc()).all()
    return render_template("admin/alerts.html", thresholds=thresholds)


@admin_bp.route("/alerts/<int:threshold_id>/toggle", methods=["POST"])
@login_required
@role_required("admin")
def toggle_alert(threshold_id: int):
    """Toggle is_active on an AlertThreshold."""
    t = db.session.get(AlertThreshold, threshold_id)
    if not t:
        return _error_frag("Threshold not found.", 404)
    t.is_active = not t.is_active
    db.session.commit()
    if _is_htmx():
        return render_template("partials/admin/alert_row.html", t=t)
    return redirect(url_for("admin.alerts"))


@admin_bp.route("/alerts/<int:threshold_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_alert(threshold_id: int):
    """Delete an AlertThreshold record."""
    t = db.session.get(AlertThreshold, threshold_id)
    if not t:
        return _error_frag("Threshold not found.", 404)
    db.session.delete(t)
    db.session.commit()
    return "", 200


# ════════════════════════════════════════════════════════════════════════════════
# FEATURE FLAGS
# ════════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/flags", methods=["GET", "POST"])
@login_required
@role_required("admin")
def flags():
    """List feature flags; POST creates a new one."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None

        result = feature_flag_service.create_flag(name=name, description=description)
        if not result["success"]:
            if _is_htmx():
                return _error_frag(result["reason"])
            flash(result["reason"], "error")
            return redirect(url_for("admin.flags"))

        if _is_htmx():
            all_flags = feature_flag_service.get_all_flags()
            return render_template("partials/admin/flag_rows.html", flags=all_flags), 201

        flash(f"Flag '{name}' created.", "success")
        return redirect(url_for("admin.flags"))

    all_flags = feature_flag_service.get_all_flags()
    return render_template("admin/flags.html", flags=all_flags)


@admin_bp.route("/flags/<name>/toggle", methods=["POST"])
@login_required
@role_required("admin")
def toggle_flag(name: str):
    """Toggle is_enabled on a feature flag."""
    from app.models.ops import FeatureFlag
    flag = FeatureFlag.query.filter_by(name=name).first()
    if not flag:
        return _error_frag("Flag not found.", 404)

    result = feature_flag_service.update_flag(name=name, is_enabled=not flag.is_enabled)
    if not result["success"]:
        return _error_frag(result["reason"])

    if _is_htmx():
        return render_template("partials/admin/flag_row.html", flag=result["flag"])
    return redirect(url_for("admin.flags"))


@admin_bp.route("/flags/<name>/canary", methods=["POST"])
@login_required
@role_required("admin")
def update_canary(name: str):
    """Update canary user ID list for a feature flag."""
    raw_ids = request.form.get("canary_ids", "").strip()
    try:
        ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
    except ValueError:
        ids = []

    result = feature_flag_service.update_flag(name=name, canary_staff_ids=ids)
    if not result["success"]:
        return _error_frag(result["reason"])

    if _is_htmx():
        return render_template("partials/admin/flag_row.html", flag=result["flag"])
    flash("Canary list updated.", "success")
    return redirect(url_for("admin.flags"))


@admin_bp.route("/flags/<name>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_flag(name: str):
    """Delete a feature flag."""
    result = feature_flag_service.delete_flag(name)
    if not result["success"]:
        return _error_frag(result["reason"], 404)
    return "", 200


# ════════════════════════════════════════════════════════════════════════════════
# BACKUPS
# ════════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/backups")
@login_required
@role_required("admin")
def backups():
    """Backup management page."""
    all_backups = backup_service.list_backups()
    return render_template("admin/backups.html", backups=all_backups)


@admin_bp.route("/backups/db", methods=["POST"])
@login_required
@role_required("admin")
def backup_db():
    """Trigger a database backup."""
    result = backup_service.create_database_backup()
    if _is_htmx():
        all_backups = backup_service.list_backups()
        msg = None if result["success"] else result["reason"]
        return render_template("partials/admin/backup_rows.html",
                               backups=all_backups, flash_msg=msg)
    if result["success"]:
        flash("Database backup created.", "success")
    else:
        flash(result["reason"], "error")
    return redirect(url_for("admin.backups"))


@admin_bp.route("/backups/files", methods=["POST"])
@login_required
@role_required("admin")
def backup_files():
    """Trigger a file (uploads) backup."""
    result = backup_service.create_file_backup()
    if _is_htmx():
        all_backups = backup_service.list_backups()
        msg = None if result["success"] else result["reason"]
        return render_template("partials/admin/backup_rows.html",
                               backups=all_backups, flash_msg=msg)
    if result["success"]:
        flash("File backup created.", "success")
    else:
        flash(result["reason"], "error")
    return redirect(url_for("admin.backups"))


@admin_bp.route("/backups/<int:backup_id>/restore", methods=["POST"])
@login_required
@role_required("admin")
def restore_backup(backup_id: int):
    """Mark a backup as the restore target; optionally promote it."""
    promote = request.form.get("promote") == "1"
    if promote:
        result = backup_service.promote_restore(backup_id)
    else:
        result = backup_service.restore_backup(backup_id)

    if _is_htmx():
        if result["success"]:
            msg = result.get("message") or f"Backup #{backup_id} marked for restore."
            return render_template("partials/admin/backup_restored.html", message=msg)
        return _error_frag(result["reason"])

    if result["success"]:
        flash(result.get("message") or "Backup marked for restore.", "success")
    else:
        flash(result["reason"], "error")
    return redirect(url_for("admin.backups"))


@admin_bp.route("/backups/enforce-retention", methods=["POST"])
@login_required
@role_required("admin")
def backup_enforce_retention():
    """Prune old backups beyond the retention limit."""
    max_backups = request.form.get("max_backups", 30, type=int)
    result = backup_service.enforce_retention(max_backups=max_backups)
    if _is_htmx():
        all_backups = backup_service.list_backups()
        return render_template("partials/admin/backup_rows.html",
                               backups=all_backups,
                               flash_msg=f"Retention enforced: {result['deleted']} deleted.")
    flash(f"Retention enforced: {result['deleted']} deleted, {result['kept']} kept.", "success")
    return redirect(url_for("admin.backups"))
