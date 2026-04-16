import json
import logging
import math
import re
from datetime import datetime

import bleach
import markdown

_ALLOWED_TAGS = {
    "a", "abbr", "acronym", "b", "blockquote", "br", "caption", "cite",
    "code", "col", "colgroup", "dd", "del", "dfn", "div", "dl", "dt",
    "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "ins", "kbd", "li", "mark", "ol", "p", "pre",
    "q", "s", "samp", "small", "span", "strong", "sub", "sup", "table",
    "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul", "var",
}
_ALLOWED_ATTRS = {
    "a": ["href", "title", "rel"],
    "abbr": ["title"],
    "acronym": ["title"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["align", "colspan", "rowspan"],
    "th": ["align", "colspan", "rowspan", "scope"],
    "*": ["class"],
}


def _sanitize_html(html: str) -> str:
    return bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)

from app.extensions import db
from app.models.content import Content, ContentAttachment, ContentVersion
from app.models.user import User
from app.services.content_filter_service import filter_content

logger = logging.getLogger(__name__)

# Maps content status to a Tailwind color hint for the dashboard
_STATUS_COLORS = {
    "published": "green",
    "in_review": "yellow",
    "draft": "gray",
    "rejected": "red",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_SYNTAX_RE = re.compile(
    r"(\*{1,3}|_{1,3}|~~|`{1,3}|#{1,6}\s|>\s|\[.*?\]\(.*?\)|\!\[.*?\]\(.*?\))"
)


def _strip_markup(text: str) -> str:
    """Remove HTML tags and common markdown syntax for plain-text excerpts."""
    if not text:
        return ""
    text = _HTML_TAG_RE.sub("", text)
    text = _MARKDOWN_SYNTAX_RE.sub("", text)
    return text.strip()


def _estimated_read_time(body: str) -> str:
    if not body:
        return "1 min read"
    word_count = len(body.split())
    minutes = math.ceil(word_count / 200)
    return f"{minutes} min read"


def _format_date(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%m/%d/%Y")


def _format_datetime(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%m/%d/%Y %I:%M %p")


def _parse_tags(tags_json: str | None) -> list:
    if not tags_json:
        return []
    try:
        parsed = json.loads(tags_json)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# FUNCTION 1
# ---------------------------------------------------------------------------

def get_published_content(
    page: int = 1,
    per_page: int = 12,
    category: str = None,
    content_type: str = None,
    search: str = None,
    tags: list[str] = None,
) -> dict:
    """Get paginated published content with filters."""
    query = Content.query.filter_by(status="published")

    if category:
        query = query.filter(Content.category == category)
    if content_type:
        query = query.filter(Content.content_type == content_type)
    if search:
        query = query.filter(Content.title.ilike(f"%{search}%"))
    if tags:
        for tag in tags:
            query = query.filter(Content.tags.like(f'%"{tag}"%'))

    query = query.order_by(Content.published_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for c in pagination.items:
        plain_body = _strip_markup(c.body or "")
        excerpt = plain_body[:200]

        author_name = c.author.username if c.author else "Unknown"

        items.append(
            {
                "id": c.id,
                "title": c.title,
                "content_type": c.content_type,
                "category": c.category,
                "tags": _parse_tags(c.tags),
                "author_name": author_name,
                "published_at": _format_date(c.published_at),
                "cover_url": c.cover_path,
                "excerpt": excerpt,
                "estimated_read_time": _estimated_read_time(c.body),
            }
        )

    return {
        "items": items,
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
        "has_next": pagination.has_next,
    }


# ---------------------------------------------------------------------------
# FUNCTION 2
# ---------------------------------------------------------------------------

def get_content_detail(content_id: int, user_role: str = None, user_id: int = None) -> dict | None:
    """Get full content for display, rendering markdown to HTML if needed."""
    content = Content.query.get(content_id)
    if not content:
        return None

    if content.status != "published":
        if user_role == "admin":
            pass
        elif user_role == "editor" and user_id and content.author_id == user_id:
            pass
        else:
            return None

    # Render body
    if content.body_format == "markdown":
        body_html = _sanitize_html(markdown.markdown(
            content.body or "",
            extensions=["extra", "codehilite", "toc"],
        ))
    else:
        body_html = content.body or ""

    # Chapters (for books)
    chapters = []
    if content.content_type == "book":
        children = (
            Content.query.filter_by(parent_id=content_id)
            .order_by(Content.sort_order)
            .all()
        )
        for ch in children:
            chapters.append(
                {
                    "id": ch.id,
                    "title": ch.title,
                    "sort_order": ch.sort_order,
                    "status": ch.status,
                }
            )

    # Attachments
    attachments = []
    for att in content.attachments.all():
        attachments.append(
            {
                "id": att.id,
                "original_filename": att.original_filename,
                "file_type": att.file_type,
                "file_size": att.file_size,
                "file_path": att.file_path,
            }
        )

    author_name = content.author.username if content.author else "Unknown"

    return {
        "id": content.id,
        "title": content.title,
        "content_type": content.content_type,
        "body_html": body_html,
        "category": content.category,
        "tags": _parse_tags(content.tags),
        "author_name": author_name,
        "published_at": _format_date(content.published_at),
        "cover_path": content.cover_path,
        "attachments": attachments,
        "chapters": chapters,
        "current_version": content.current_version,
    }


# ---------------------------------------------------------------------------
# FUNCTION 3
# ---------------------------------------------------------------------------

def save_content(content_id: int | None, data: dict, author_id: int) -> dict:
    """Create or update content, with version tracking and content filtering."""
    # Step 1: Validate title.
    if not data.get("title") or not data["title"].strip():
        return {"success": False, "reason": "Title is required."}
    if len(data["title"]) > 300:
        return {"success": False, "reason": "Title cannot exceed 300 characters."}

    # Step 2: Run content filter on title AND body.
    title_check = filter_content(data["title"])
    body_check = filter_content(data.get("body", ""))
    all_violations = title_check["violations"] + body_check["violations"]
    if all_violations:
        return {
            "success": False,
            "reason": "Content contains prohibited terms.",
            "violations": all_violations,
        }

    # Step 3: Parse tags.
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags_json = json.dumps(tags)

    # Enforce status transitions: only admins may set arbitrary statuses via
    # save.  Non-admin editors always save as "draft"; they must use the
    # dedicated submit_for_review / publish / reject endpoints for transitions.
    author = User.query.get(author_id)
    if not author or author.role != "admin":
        data["status"] = "draft"

    if content_id is not None:
        # Step 4: Update existing content.
        content = Content.query.get(content_id)
        if not content:
            return {"success": False, "reason": "Content not found."}
        if content.author_id != author_id:
            if not author or author.role != "admin":
                return {"success": False, "reason": "You can only edit your own content."}

        # Snapshot current state before update
        version = ContentVersion(
            content_id=content.id,
            version_number=content.current_version,
            title=content.title,
            body=content.body,
            status=content.status,
            created_by=author_id,
            change_note="Auto-saved before update",
        )
        db.session.add(version)

        content.title = data["title"]
        content.body = data.get("body", "")
        content.body_format = data.get("body_format", "markdown")
        content.content_type = data.get("content_type", content.content_type)
        content.category = data.get("category")
        content.tags = tags_json
        content.status = data.get("status", "draft")
        content.parent_id = data.get("parent_id")
        content.sort_order = data.get("sort_order", 0)
        content.current_version += 1
        content.updated_at = datetime.utcnow()

        logger.info("Updated content id=%d to version %d", content.id, content.current_version)
    else:
        # Step 5: Create new content (status already sanitised above).
        content = Content(
            title=data["title"],
            content_type=data.get("content_type", "article"),
            body=data.get("body", ""),
            body_format=data.get("body_format", "markdown"),
            status=data["status"],
            author_id=author_id,
            category=data.get("category"),
            tags=tags_json,
            parent_id=data.get("parent_id"),
            sort_order=data.get("sort_order", 0),
            current_version=1,
        )
        db.session.add(content)
        db.session.flush()  # Get the ID

        version = ContentVersion(
            content_id=content.id,
            version_number=1,
            title=content.title,
            body=content.body,
            status=content.status,
            created_by=author_id,
            change_note="Initial creation",
        )
        db.session.add(version)

        logger.info("Created new content id=%d by author_id=%d", content.id, author_id)

    # Step 6: Commit
    db.session.commit()
    return {"success": True, "content_id": content.id, "version": content.current_version}


# ---------------------------------------------------------------------------
# FUNCTION 4
# ---------------------------------------------------------------------------

def submit_for_review(content_id: int, user_id: int) -> dict:
    """Change status from 'draft' to 'in_review'. Creates a version snapshot."""
    content = Content.query.get(content_id)
    if not content:
        return {"success": False, "reason": "Content not found."}

    user = User.query.get(user_id)
    if not user:
        return {"success": False, "reason": "User not found."}
    if content.author_id != user_id and user.role != "admin":
        return {"success": False, "reason": "You can only submit your own content for review."}

    if content.status != "draft":
        return {"success": False, "reason": "Only draft content can be submitted for review."}

    version = ContentVersion(
        content_id=content.id,
        version_number=content.current_version,
        title=content.title,
        body=content.body,
        status=content.status,
        created_by=user_id,
        change_note="Submitted for review",
    )
    db.session.add(version)

    content.status = "in_review"
    content.current_version += 1
    content.updated_at = datetime.utcnow()
    db.session.commit()

    logger.info("Content id=%d submitted for review by user_id=%d", content_id, user_id)
    return {"success": True, "message": "Content submitted for review."}


# ---------------------------------------------------------------------------
# FUNCTION 5
# ---------------------------------------------------------------------------

def publish_content(content_id: int, admin_id: int) -> dict:
    """Admin publishes content."""
    content = Content.query.get(content_id)
    if not content:
        return {"success": False, "reason": "Content not found."}

    admin = User.query.get(admin_id)
    if not admin:
        return {"success": False, "reason": "User not found."}
    if admin.role != "admin":
        return {"success": False, "reason": "Only admins can publish content."}

    if content.status != "in_review":
        return {"success": False, "reason": "Only content in review can be published."}

    version = ContentVersion(
        content_id=content.id,
        version_number=content.current_version,
        title=content.title,
        body=content.body,
        status="published",
        created_by=admin_id,
        change_note="Published",
    )
    db.session.add(version)

    content.status = "published"
    content.published_at = datetime.utcnow()
    content.current_version += 1
    content.updated_at = datetime.utcnow()
    db.session.commit()

    logger.info("Content id=%d published by admin_id=%d", content_id, admin_id)
    return {"success": True, "message": f"'{content.title}' has been published."}


# ---------------------------------------------------------------------------
# FUNCTION 6
# ---------------------------------------------------------------------------

def reject_content(content_id: int, admin_id: int, rejection_note: str) -> dict:
    """Admin rejects content, returning it to draft."""
    content = Content.query.get(content_id)
    if not content:
        return {"success": False, "reason": "Content not found."}

    admin = User.query.get(admin_id)
    if not admin:
        return {"success": False, "reason": "User not found."}
    if admin.role != "admin":
        return {"success": False, "reason": "Only admins can reject content."}

    if not rejection_note or len(rejection_note.strip()) < 5:
        return {
            "success": False,
            "reason": "A rejection note is required (minimum 5 characters).",
        }

    version = ContentVersion(
        content_id=content.id,
        version_number=content.current_version,
        title=content.title,
        body=content.body,
        status="rejected",
        created_by=admin_id,
        change_note=rejection_note,
    )
    db.session.add(version)

    content.status = "draft"
    content.current_version += 1
    content.updated_at = datetime.utcnow()
    db.session.commit()

    logger.info("Content id=%d rejected by admin_id=%d", content_id, admin_id)
    return {"success": True, "message": "Content has been sent back to draft with feedback."}


# ---------------------------------------------------------------------------
# FUNCTION 7
# ---------------------------------------------------------------------------

def get_version_history(content_id: int) -> list[dict]:
    """Get all versions for a content item, most recent first."""
    versions = (
        ContentVersion.query.filter_by(content_id=content_id)
        .order_by(ContentVersion.version_number.desc())
        .all()
    )

    result = []
    for v in versions:
        created_by_name = (
            v.created_by_user.username if v.created_by_user else f"user#{v.created_by}"
        )
        result.append(
            {
                "version_id": v.id,
                "version_number": v.version_number,
                "title": v.title,
                "status": v.status,
                "change_note": v.change_note,
                "created_by_name": created_by_name,
                "created_at": _format_datetime(v.created_at),
            }
        )
    return result


# ---------------------------------------------------------------------------
# FUNCTION 8
# ---------------------------------------------------------------------------

def rollback_to_version(content_id: int, version_id: int, user_id: int) -> dict:
    """Restore content to a previous version."""
    content = Content.query.get(content_id)
    if not content:
        return {"success": False, "reason": "Content not found."}

    actor = User.query.get(user_id)
    if not actor:
        return {"success": False, "reason": "User not found."}
    if content.author_id != user_id and actor.role != "admin":
        return {"success": False, "reason": "You can only rollback your own content."}

    target = ContentVersion.query.get(version_id)
    if not target:
        return {"success": False, "reason": "Version not found."}
    if target.content_id != content_id:
        return {"success": False, "reason": "Version does not belong to this content."}

    # Snapshot current state before rollback
    pre_rollback_version = ContentVersion(
        content_id=content.id,
        version_number=content.current_version,
        title=content.title,
        body=content.body,
        status=content.status,
        created_by=user_id,
        change_note=f"State before rollback to version {target.version_number}",
    )
    db.session.add(pre_rollback_version)

    # Apply rollback
    content.title = target.title
    content.body = target.body
    content.status = "draft"
    content.current_version += 1
    content.updated_at = datetime.utcnow()

    # Record the rollback action
    rollback_version = ContentVersion(
        content_id=content.id,
        version_number=content.current_version,
        title=content.title,
        body=content.body,
        status="draft",
        created_by=user_id,
        change_note=f"Rolled back to version {target.version_number}",
    )
    db.session.add(rollback_version)
    db.session.commit()

    logger.info(
        "Content id=%d rolled back to version %d by user_id=%d",
        content_id,
        target.version_number,
        user_id,
    )
    return {
        "success": True,
        "message": f"Content rolled back to version {target.version_number}. Status reset to draft.",
    }


# ---------------------------------------------------------------------------
# FUNCTION 9
# ---------------------------------------------------------------------------

def get_editor_dashboard(user_id: int, role: str) -> list[dict]:
    """Get content items for the editor dashboard."""
    if role == "admin":
        items = Content.query.order_by(Content.updated_at.desc()).all()
    else:
        items = (
            Content.query.filter_by(author_id=user_id)
            .order_by(Content.updated_at.desc())
            .all()
        )

    result = []
    for c in items:
        author_name = c.author.username if c.author else "Unknown"
        result.append(
            {
                "id": c.id,
                "title": c.title,
                "content_type": c.content_type,
                "status": c.status,
                "status_color": _STATUS_COLORS.get(c.status, "gray"),
                "current_version": c.current_version,
                "updated_at": _format_date(c.updated_at),
                "author_name": author_name,
            }
        )
    return result


# ---------------------------------------------------------------------------
# FUNCTION 10
# ---------------------------------------------------------------------------

def delete_content(content_id: int, user_id: int) -> dict:
    """Delete content and all its versions. Owner or admin only."""
    content = Content.query.get(content_id)
    if not content:
        return {"success": False, "reason": "Content not found."}

    actor = User.query.get(user_id)
    if not actor:
        return {"success": False, "reason": "User not found."}
    if content.author_id != user_id and actor.role != "admin":
        return {"success": False, "reason": "You can only delete your own content."}

    title = content.title
    # Delete versions explicitly (no cascade configured on the relationship)
    ContentVersion.query.filter_by(content_id=content_id).delete()
    db.session.delete(content)
    db.session.commit()

    logger.info("Content id=%d ('%s') deleted by user_id=%d", content_id, title, user_id)
    return {"success": True, "message": f"'{title}' has been deleted."}


def preview_markdown(text: str) -> str:
    """Convert markdown text to sanitized HTML for live preview."""
    if not text:
        return ""
    html = markdown.markdown(text, extensions=["extra", "codehilite", "toc"])
    return _sanitize_html(html)
