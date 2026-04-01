"""
Backup service — database and file backups, retention enforcement, and restore.

Backup files are stored in <project_root>/backups/ with timestamped filenames.
CLI commands are registered via register_backup_cli(app).

Supported backup types:
  "database" — SQLite DB file copy
  "files"    — ZIP archive of the uploads directory
"""
import logging
import os
import shutil
import zipfile
from datetime import datetime

import click
from flask import Flask, current_app

from app.extensions import db
from app.models.ops import Backup

logger = logging.getLogger(__name__)

_TS_FMT = "%Y%m%d_%H%M%S"


# ── helpers ───────────────────────────────────────────────────────────────────

def _backup_dir() -> str:
    """Return (and ensure) the backups directory path."""
    base = os.path.join(current_app.root_path, "..", "backups")
    os.makedirs(base, exist_ok=True)
    return os.path.abspath(base)


def _db_file_path() -> str | None:
    """Extract the SQLite file path from SQLALCHEMY_DATABASE_URI, or None."""
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///"):
        raw = uri[len("sqlite:///"):]
        return raw if os.path.isabs(raw) else os.path.join(current_app.root_path, "..", raw)
    if uri.startswith("sqlite://"):
        # relative or in-memory
        raw = uri[len("sqlite://"):]
        if not raw or raw == ":memory:":
            return None
        return os.path.abspath(raw)
    return None


def _fmt_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _backup_to_dict(b: Backup) -> dict:
    return {
        "id": b.id,
        "backup_type": b.backup_type,
        "file_path": b.file_path,
        "file_size": b.file_size,
        "file_size_human": _fmt_size(b.file_size),
        "status": b.status,
        "created_at": b.created_at.strftime("%m/%d/%Y %I:%M %p") if b.created_at else None,
    }


# ── FUNCTION 1: create_database_backup ───────────────────────────────────────

def create_database_backup() -> dict:
    """
    Copy the SQLite database file to the backups directory.

    Returns:
        {"success": True, "backup": dict}
        {"success": False, "reason": str}
    """
    db_path = _db_file_path()
    if not db_path:
        return {"success": False, "reason": "Database backup is not supported for in-memory SQLite."}

    if not os.path.exists(db_path):
        return {"success": False, "reason": f"Database file not found: {db_path}"}

    ts = datetime.utcnow().strftime(_TS_FMT)
    dest_name = f"db_backup_{ts}.sqlite"
    dest_path = os.path.join(_backup_dir(), dest_name)

    try:
        shutil.copy2(db_path, dest_path)
        file_size = os.path.getsize(dest_path)
    except OSError as exc:
        logger.error("Database backup failed: %s", exc)
        record = Backup(backup_type="database", file_path=dest_name, status="failed")
        db.session.add(record)
        db.session.commit()
        return {"success": False, "reason": str(exc)}

    record = Backup(backup_type="database", file_path=dest_path, file_size=file_size, status="completed")
    db.session.add(record)
    db.session.commit()

    logger.info("Database backup created: %s (%s)", dest_name, _fmt_size(file_size))
    return {"success": True, "backup": _backup_to_dict(record)}


# ── FUNCTION 2: create_file_backup ───────────────────────────────────────────

def create_file_backup() -> dict:
    """
    Create a ZIP archive of the uploads directory.

    Returns:
        {"success": True, "backup": dict}
        {"success": False, "reason": str}
    """
    upload_dir = current_app.config.get("UPLOAD_FOLDER", "")
    if not upload_dir or not os.path.isdir(upload_dir):
        return {"success": False, "reason": f"Upload directory not found: {upload_dir}"}

    ts = datetime.utcnow().strftime(_TS_FMT)
    dest_name = f"files_backup_{ts}.zip"
    dest_path = os.path.join(_backup_dir(), dest_name)

    try:
        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_dir, dirs, files in os.walk(upload_dir):
                for fname in files:
                    full_path = os.path.join(root_dir, fname)
                    arcname = os.path.relpath(full_path, os.path.dirname(upload_dir))
                    zf.write(full_path, arcname)
        file_size = os.path.getsize(dest_path)
    except Exception as exc:
        logger.error("File backup failed: %s", exc)
        record = Backup(backup_type="files", file_path=dest_name, status="failed")
        db.session.add(record)
        db.session.commit()
        return {"success": False, "reason": str(exc)}

    record = Backup(backup_type="files", file_path=dest_path, file_size=file_size, status="completed")
    db.session.add(record)
    db.session.commit()

    logger.info("File backup created: %s (%s)", dest_name, _fmt_size(file_size))
    return {"success": True, "backup": _backup_to_dict(record)}


# ── FUNCTION 3: enforce_retention ────────────────────────────────────────────

def enforce_retention(max_backups: int = 30) -> dict:
    """
    Keep only the `max_backups` most recent completed backups of each type.

    Deletes both the physical file and the Backup DB record for excess entries.

    Returns:
        {"deleted": int, "kept": int}
    """
    deleted = 0
    kept = 0

    for backup_type in ("database", "files"):
        backups = (
            Backup.query
            .filter_by(backup_type=backup_type, status="completed")
            .order_by(Backup.created_at.desc())
            .all()
        )

        to_keep = backups[:max_backups]
        to_delete = backups[max_backups:]

        kept += len(to_keep)
        for b in to_delete:
            try:
                if b.file_path and os.path.exists(b.file_path):
                    os.remove(b.file_path)
            except OSError as exc:
                logger.warning("Could not delete backup file %s: %s", b.file_path, exc)
            db.session.delete(b)
            deleted += 1

    db.session.commit()
    logger.info("Retention enforced: deleted=%d kept=%d", deleted, kept)
    return {"deleted": deleted, "kept": kept}


# ── FUNCTION 4: restore_backup ───────────────────────────────────────────────

def restore_backup(backup_id: int) -> dict:
    """
    Mark a backup record as the restore candidate and return the file path.

    This is a non-destructive step — it validates the backup exists and is
    accessible. Call `promote_restore` to actually apply it.

    Returns:
        {"success": True, "file_path": str, "backup_type": str}
        {"success": False, "reason": str}
    """
    backup = db.session.get(Backup, backup_id)
    if not backup:
        return {"success": False, "reason": f"Backup #{backup_id} not found."}

    if backup.status == "failed":
        return {"success": False, "reason": "Cannot restore a failed backup."}

    if backup.backup_type == "database":
        if not backup.file_path or not os.path.exists(backup.file_path):
            return {"success": False, "reason": "Backup file does not exist on disk."}

    backup.status = "restored"
    db.session.commit()

    logger.info("Backup #%d selected for restore: %s", backup_id, backup.file_path)
    return {
        "success": True,
        "backup_id": backup_id,
        "file_path": backup.file_path,
        "backup_type": backup.backup_type,
    }


# ── FUNCTION 5: promote_restore ──────────────────────────────────────────────

def promote_restore(backup_id: int) -> dict:
    """
    Apply a database backup by copying it over the live database file.

    WARNING: This replaces the running database. All in-flight transactions are
    lost. Only valid for SQLite file databases; no-op for in-memory DBs.

    Returns:
        {"success": True, "message": str}
        {"success": False, "reason": str}
    """
    backup = db.session.get(Backup, backup_id)
    if not backup:
        return {"success": False, "reason": f"Backup #{backup_id} not found."}

    if backup.backup_type != "database":
        return {"success": False, "reason": "promote_restore only supports database backups."}

    if not backup.file_path or not os.path.exists(backup.file_path):
        return {"success": False, "reason": "Backup file does not exist on disk."}

    db_path = _db_file_path()
    if not db_path:
        return {"success": False, "reason": "Cannot promote: running on in-memory SQLite."}

    # Close all SQLAlchemy connections before overwriting
    try:
        db.engine.dispose()
    except Exception as exc:
        logger.warning("promote_restore: engine dispose failed: %s", exc)

    try:
        # Create a safety copy of current DB before overwriting
        ts = datetime.utcnow().strftime(_TS_FMT)
        safety_path = os.path.join(_backup_dir(), f"pre_restore_safety_{ts}.sqlite")
        if os.path.exists(db_path):
            shutil.copy2(db_path, safety_path)

        shutil.copy2(backup.file_path, db_path)
    except OSError as exc:
        logger.error("promote_restore failed: %s", exc)
        return {"success": False, "reason": f"Failed to copy backup: {exc}"}

    message = (
        f"Database restored from backup #{backup_id}. "
        f"Pre-restore safety copy saved to {os.path.basename(safety_path)}. "
        "Restart the application to reconnect."
    )
    logger.warning("promote_restore: %s", message)
    return {"success": True, "message": message}


# ── helpers for CLI ──────────────────────────────────────────────────────────

def list_backups() -> list[dict]:
    """Return all backup records, newest first."""
    backups = Backup.query.order_by(Backup.created_at.desc()).all()
    return [_backup_to_dict(b) for b in backups]


# ── CLI ───────────────────────────────────────────────────────────────────────

def register_backup_cli(app: Flask) -> None:
    """Register flask backup-* CLI commands."""

    @app.cli.command("backup-db")
    def backup_db_cmd():
        """Create a database backup."""
        result = create_database_backup()
        if result["success"]:
            b = result["backup"]
            click.echo(f"Database backup created: {b['file_path']} ({b['file_size_human']})")
        else:
            click.echo(f"Error: {result['reason']}", err=True)

    @app.cli.command("backup-files")
    def backup_files_cmd():
        """Create a ZIP backup of the uploads directory."""
        result = create_file_backup()
        if result["success"]:
            b = result["backup"]
            click.echo(f"File backup created: {b['file_path']} ({b['file_size_human']})")
        else:
            click.echo(f"Error: {result['reason']}", err=True)

    @app.cli.command("backup-restore")
    @click.argument("backup_id", type=int)
    @click.option("--promote", is_flag=True, help="Actually apply the backup (destructive).")
    def backup_restore_cmd(backup_id: int, promote: bool):
        """Mark or apply backup BACKUP_ID as a restore target."""
        if promote:
            result = promote_restore(backup_id)
        else:
            result = restore_backup(backup_id)

        if result["success"]:
            msg = result.get("message") or f"Backup #{backup_id} ready for restore: {result.get('file_path')}"
            click.echo(msg)
        else:
            click.echo(f"Error: {result['reason']}", err=True)

    @app.cli.command("backup-list")
    def backup_list_cmd():
        """List all backup records."""
        backups = list_backups()
        if not backups:
            click.echo("No backups found.")
            return
        click.echo(f"{'ID':>4}  {'Type':<10}  {'Size':<10}  {'Status':<12}  {'Created'}")
        click.echo("-" * 66)
        for b in backups:
            click.echo(
                f"{b['id']:>4}  {b['backup_type']:<10}  {b['file_size_human']:<10}  "
                f"{b['status']:<12}  {b['created_at']}"
            )

    @app.cli.command("backup-enforce-retention")
    @click.option("--max-backups", default=30, show_default=True, help="Backups to keep per type.")
    def backup_retention_cmd(max_backups: int):
        """Remove old backups beyond the retention limit."""
        result = enforce_retention(max_backups=max_backups)
        click.echo(f"Retention enforced: deleted={result['deleted']} kept={result['kept']}")
