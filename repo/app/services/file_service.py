import hashlib
import logging
import os
import uuid

from flask import current_app

from app.extensions import db
from app.models.content import ContentAttachment

logger = logging.getLogger(__name__)


def _to_storage_path(content_id: int, filename: str) -> str:
    return os.path.join(str(content_id), filename).replace("\\", "/")


def resolve_upload_path(storage_path: str) -> str:
    """
    Resolve a stored path to an absolute filesystem path under UPLOAD_FOLDER.
    Backwards compatible with legacy absolute paths already in the database.
    """
    if not storage_path:
        return ""
    if os.path.isabs(storage_path):
        return os.path.abspath(storage_path)
    base = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    return os.path.abspath(os.path.join(base, storage_path))


def upload_file(file, content_id: int, upload_type: str = "cover") -> dict:
    """
    Validate and save an uploaded file.

    Parameters:
        file: werkzeug FileStorage object
        content_id: ID of the Content record this file belongs to
        upload_type: "cover" or "attachment"

    Returns:
        {"success": True, "attachment_id": int, "file_path": str, "original_filename": str}
        OR {"success": False, "reason": str}
    """
    # Step 1: Validate file exists and has a filename.
    if not file or not file.filename:
        return {"success": False, "reason": "No file selected."}

    # Step 2: Extract file extension.
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""

    # Step 3: Validate file type.
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}
    if ext not in ALLOWED_EXTENSIONS:
        return {
            "success": False,
            "reason": f"File type '.{ext}' is not allowed. Accepted types: JPG, PNG, PDF.",
        }

    # Step 4: Read file content and check size.
    file_content = file.read()
    file_size = len(file_content)
    MAX_SIZE = 10 * 1024 * 1024  # 10 MB
    if file_size > MAX_SIZE:
        return {
            "success": False,
            "reason": f"File size ({file_size / (1024*1024):.1f} MB) exceeds the 10 MB limit.",
        }
    file.seek(0)  # Reset for saving

    # Step 5: Compute SHA-256 fingerprint.
    fingerprint = hashlib.sha256(file_content).hexdigest()

    # Step 6: Check for duplicate.
    existing = ContentAttachment.query.filter_by(fingerprint=fingerprint).first()
    if existing:
        return {
            "success": False,
            "reason": f"This file has already been uploaded (matches '{existing.original_filename}').",
        }

    # Step 7: Save file.
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(content_id))
    os.makedirs(upload_dir, exist_ok=True)
    safe_filename = f"{uuid.uuid4().hex}.{ext}"
    storage_path = _to_storage_path(content_id, safe_filename)
    abs_path = resolve_upload_path(storage_path)
    with open(abs_path, "wb") as f:
        f.write(file_content)

    logger.info(
        "File saved: %s (content_id=%s, type=%s, size=%d bytes)",
        safe_filename,
        content_id,
        upload_type,
        file_size,
    )

    # Step 8: Create ContentAttachment record.
    attachment = ContentAttachment(
        content_id=content_id,
        file_path=storage_path,
        original_filename=file.filename,
        file_type=ext,
        file_size=file_size,
        fingerprint=fingerprint,
    )
    db.session.add(attachment)
    db.session.commit()

    return {
        "success": True,
        "attachment_id": attachment.id,
        "file_path": storage_path,
        "original_filename": file.filename,
    }


def delete_file(attachment_id: int) -> dict:
    """Delete a file from disk and its database record."""
    attachment = ContentAttachment.query.get(attachment_id)
    if not attachment:
        return {"success": False, "reason": "Attachment not found."}

    try:
        abs_path = resolve_upload_path(attachment.file_path)
        os.remove(abs_path)
        logger.info("Deleted file from disk: %s", abs_path)
    except OSError as e:
        logger.warning(
            "Could not delete file from disk (attachment_id=%d, path=%s): %s",
            attachment_id,
            attachment.file_path,
            e,
        )

    db.session.delete(attachment)
    db.session.commit()

    return {"success": True, "message": "File deleted."}
