import hashlib
import logging
import os
import uuid

from flask import current_app

from app.extensions import db
from app.models.content import ContentAttachment

logger = logging.getLogger(__name__)


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
    file_path = os.path.join(upload_dir, safe_filename)
    with open(file_path, "wb") as f:
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
        file_path=file_path,
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
        "file_path": file_path,
        "original_filename": file.filename,
    }


def delete_file(attachment_id: int) -> dict:
    """Delete a file from disk and its database record."""
    attachment = ContentAttachment.query.get(attachment_id)
    if not attachment:
        return {"success": False, "reason": "Attachment not found."}

    try:
        os.remove(attachment.file_path)
        logger.info("Deleted file from disk: %s", attachment.file_path)
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
