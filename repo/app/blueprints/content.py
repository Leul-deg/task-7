"""
Content blueprint — all content-related HTTP endpoints.

URL layout (blueprint registered at /content):
  GET  /content                           – public content browsing
  GET  /content/<id>                      – single content view
  GET  /content/editor                    – editor dashboard
  GET  /content/editor/new                – create new content form
  GET  /content/editor/<id>/edit          – edit existing content
  POST /content/editor/save               – save content (create or update)
  POST /content/<id>/submit-review        – submit for review
  POST /content/<id>/publish              – publish content (admin)
  POST /content/<id>/reject               – reject content (admin)
  GET  /content/<id>/history              – version history
  POST /content/<id>/rollback/<version_id>– rollback to version
  POST /content/preview                   – markdown live preview
  GET  /content/categories                – autocomplete endpoint
  GET  /content/filters                   – content filter management (admin)
  POST /content/filters                   – create filter (admin)
  POST /content/filters/<id>/toggle       – toggle filter active/inactive (admin)
  DELETE /content/filters/<id>            – delete filter (admin)
"""
import logging

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, abort, make_response,
)
from flask_login import current_user

from app.extensions import db
from app.models.content import Content, ContentFilter
from app.services import content_service, file_service
from app.utils.decorators import login_required, role_required

logger = logging.getLogger(__name__)

content_bp = Blueprint("content", __name__)


def _is_htmx() -> bool:
    return bool(request.headers.get("HX-Request"))


def _error_fragment(message: str, code: int = 400):
    return render_template(
        "partials/error_fragment.html", code=code, message=message
    ), code


# ── nav alias — base.html calls url_for('content.index') ─────────────────────

@content_bp.route("/index")
def index():
    """Redirect used by the nav bar — sends to the public browse page."""
    return redirect(url_for("content.browse"))


# ── Route 1 — public content browse ───────────────────────────────────────────

@content_bp.route("/")
def browse():
    """GET /content — public content browsing, no auth required."""
    page = request.args.get("page", 1, type=int)
    category = request.args.get("category") or None
    content_type = request.args.get("content_type") or None
    search = request.args.get("search") or None
    tags_raw = request.args.get("tags") or None
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None

    result = content_service.get_published_content(
        page=page,
        per_page=12,
        category=category,
        content_type=content_type,
        search=search,
        tags=tags,
    )

    # Distinct categories for the filter bar
    categories = [
        row[0] for row in
        db.session.query(Content.category)
        .filter(Content.status == "published", Content.category.isnot(None))
        .distinct()
        .order_by(Content.category)
        .all()
    ]

    if _is_htmx():
        return render_template(
            "partials/content/content_grid.html",
            items=result["items"],
            has_next=result["has_next"],
            page=result["page"],
        )

    return render_template(
        "content/browse.html",
        items=result["items"],
        total=result["total"],
        page=result["page"],
        pages=result["pages"],
        has_next=result["has_next"],
        categories=categories,
        selected_category=category,
        selected_type=content_type,
        search=search or "",
        tags_raw=tags_raw or "",
    )


# ── Route 2 — single content view ─────────────────────────────────────────────

@content_bp.route("/<int:content_id>")
def view(content_id: int):
    """GET /content/<id> — full content view."""
    user_role = current_user.role if current_user.is_authenticated else None
    user_id = current_user.id if current_user.is_authenticated else None
    content = content_service.get_content_detail(content_id, user_role=user_role, user_id=user_id)
    if content is None:
        abort(404)
    return render_template("content/view.html", content=content)


# ── Route 3 — editor dashboard ─────────────────────────────────────────────────

@content_bp.route("/editor")
@login_required
@role_required("editor", "admin")
def editor_dashboard():
    """GET /content/editor — editor's content management dashboard."""
    items = content_service.get_editor_dashboard(current_user.id, current_user.role)
    return render_template("content/editor_dashboard.html", items=items)


# ── Route 4 — new content form ─────────────────────────────────────────────────

@content_bp.route("/editor/new")
@login_required
@role_required("editor", "admin")
def editor_new():
    """GET /content/editor/new — blank create form."""
    if current_user.role == "admin":
        books = Content.query.filter_by(content_type="book").order_by(Content.title).all()
    else:
        books = Content.query.filter_by(
            content_type="book", author_id=current_user.id
        ).order_by(Content.title).all()

    return render_template("content/editor_form.html", content=None, books=books)


# ── Route 5 — edit existing content ───────────────────────────────────────────

@content_bp.route("/editor/<int:content_id>/edit")
@login_required
@role_required("editor", "admin")
def editor_edit(content_id: int):
    """GET /content/editor/<id>/edit — pre-filled edit form."""
    content = Content.query.get_or_404(content_id)

    if content.author_id != current_user.id and current_user.role != "admin":
        abort(403)

    import json
    tags_str = ", ".join(json.loads(content.tags or "[]"))

    if current_user.role == "admin":
        books = Content.query.filter_by(content_type="book").order_by(Content.title).all()
    else:
        books = Content.query.filter_by(
            content_type="book", author_id=current_user.id
        ).order_by(Content.title).all()

    return render_template(
        "content/editor_form.html",
        content=content,
        tags_str=tags_str,
        books=books,
    )


# ── Route 6 — save content ─────────────────────────────────────────────────────

@content_bp.route("/editor/save", methods=["POST"])
@login_required
@role_required("editor", "admin")
def editor_save():
    """POST /content/editor/save — create or update content with file uploads."""
    content_id_raw = request.form.get("content_id") or None
    content_id = int(content_id_raw) if content_id_raw else None

    data = {
        "title": request.form.get("title", "").strip(),
        "content_type": request.form.get("content_type", "article"),
        "body": request.form.get("body", ""),
        "body_format": request.form.get("body_format", "markdown"),
        "category": request.form.get("category", "").strip() or None,
        "tags": request.form.get("tags", ""),
        "status": request.form.get("status", "draft"),
        "parent_id": request.form.get("parent_id", type=int) or None,
        "sort_order": request.form.get("sort_order", 0, type=int),
    }

    result = content_service.save_content(content_id, data, current_user.id)

    if not result["success"]:
        violations = result.get("violations", [])
        return render_template(
            "partials/content/save_error.html",
            reason=result["reason"],
            violations=violations,
        ), 422

    saved_id = result["content_id"]

    # Handle cover image upload
    cover_file = request.files.get("cover")
    if cover_file and cover_file.filename:
        upload_result = file_service.upload_file(cover_file, saved_id, upload_type="cover")
        if upload_result["success"]:
            content_obj = Content.query.get(saved_id)
            if content_obj:
                content_obj.cover_path = upload_result["file_path"]
                db.session.commit()
        else:
            flash(f"Cover upload failed: {upload_result['reason']}", "warning")

    # Handle attachment uploads (multiple)
    for att_file in request.files.getlist("attachments"):
        if att_file and att_file.filename:
            att_result = file_service.upload_file(att_file, saved_id, upload_type="attachment")
            if not att_result["success"]:
                flash(f"Attachment '{att_file.filename}' failed: {att_result['reason']}", "warning")

    flash("Content saved successfully.", "success")

    if _is_htmx():
        resp = make_response()
        resp.headers["HX-Redirect"] = url_for("content.editor_dashboard")
        return resp, 200

    return redirect(url_for("content.editor_dashboard"))


# ── Route 7 — submit for review ───────────────────────────────────────────────

@content_bp.route("/<int:content_id>/submit-review", methods=["POST"])
@login_required
@role_required("editor", "admin")
def submit_review(content_id: int):
    """POST /content/<id>/submit-review — move from draft to in_review."""
    result = content_service.submit_for_review(content_id, current_user.id)

    if not result["success"]:
        return _error_fragment(result["reason"], 400)

    content = Content.query.get(content_id)
    return render_template(
        "partials/content/status_badge.html",
        status=content.status if content else "in_review",
        content_id=content_id,
        user_role=current_user.role,
    ), 200


# ── Route 8 — publish content ─────────────────────────────────────────────────

@content_bp.route("/<int:content_id>/publish", methods=["POST"])
@login_required
@role_required("admin")
def publish(content_id: int):
    """POST /content/<id>/publish — admin publishes content."""
    result = content_service.publish_content(content_id, current_user.id)

    if not result["success"]:
        return _error_fragment(result["reason"], 400)

    flash(result["message"], "success")
    content = Content.query.get(content_id)
    return render_template(
        "partials/content/status_badge.html",
        status=content.status if content else "published",
        content_id=content_id,
        user_role=current_user.role,
    ), 200


# ── Route 9 — reject content ──────────────────────────────────────────────────

@content_bp.route("/<int:content_id>/reject", methods=["POST"])
@login_required
@role_required("admin")
def reject(content_id: int):
    """POST /content/<id>/reject — admin rejects content with a note."""
    rejection_note = request.form.get("rejection_note", "").strip()
    result = content_service.reject_content(content_id, current_user.id, rejection_note)

    if not result["success"]:
        return _error_fragment(result["reason"], 400)

    flash(result["message"], "info")
    content = Content.query.get(content_id)
    return render_template(
        "partials/content/status_badge.html",
        status=content.status if content else "draft",
        content_id=content_id,
        user_role=current_user.role,
    ), 200


# ── Route 10 — version history ────────────────────────────────────────────────

@content_bp.route("/<int:content_id>/history")
@login_required
@role_required("editor", "admin")
def history(content_id: int):
    """GET /content/<id>/history — version history page."""
    content = Content.query.get_or_404(content_id)

    if content.author_id != current_user.id and current_user.role != "admin":
        abort(403)

    versions = content_service.get_version_history(content_id)
    return render_template(
        "content/history.html",
        content=content,
        versions=versions,
    )


# ── Route 11 — rollback ───────────────────────────────────────────────────────

@content_bp.route("/<int:content_id>/rollback/<int:version_id>", methods=["POST"])
@login_required
@role_required("editor", "admin")
def rollback(content_id: int, version_id: int):
    """POST /content/<id>/rollback/<version_id> — restore to a previous version."""
    content = Content.query.get_or_404(content_id)
    if content.author_id != current_user.id and current_user.role != "admin":
        abort(403)

    result = content_service.rollback_to_version(content_id, version_id, current_user.id)

    if not result["success"]:
        return _error_fragment(result["reason"], 400)

    flash(result["message"], "success")

    if _is_htmx():
        resp = make_response()
        resp.headers["HX-Redirect"] = url_for("content.editor_edit", content_id=content_id)
        return resp, 200

    return redirect(url_for("content.editor_edit", content_id=content_id))


# ── Route 11b — delete content ────────────────────────────────────────────────

@content_bp.route("/editor/<int:content_id>", methods=["DELETE"])
@login_required
@role_required("editor", "admin")
def delete(content_id: int):
    """DELETE /content/editor/<id> — permanently remove content (owner or admin)."""
    result = content_service.delete_content(content_id, current_user.id)

    if not result["success"]:
        code = 403 if "only delete your own" in result["reason"] else 400
        return _error_fragment(result["reason"], code)

    if _is_htmx():
        resp = make_response()
        resp.headers["HX-Redirect"] = url_for("content.editor_dashboard")
        return resp, 200

    return redirect(url_for("content.editor_dashboard"))


# ── Route 12 — markdown preview ───────────────────────────────────────────────

@content_bp.route("/preview", methods=["POST"])
@login_required
@role_required("editor", "admin")
def preview():
    """POST /content/preview — HTMX live markdown preview."""
    body = request.form.get("body", "")
    html = content_service.preview_markdown(body)
    return render_template("partials/content/preview.html", html=html)


# ── Route 13 — categories autocomplete ───────────────────────────────────────

@content_bp.route("/categories")
def categories():
    """GET /content/categories?q=<search> — datalist option fragments."""
    q = request.args.get("q", "").strip()
    query = db.session.query(Content.category).filter(
        Content.category.isnot(None),
        Content.status == "published",
    )
    if q:
        query = query.filter(Content.category.ilike(f"{q}%"))
    rows = query.distinct().order_by(Content.category).limit(20).all()
    options = [row[0] for row in rows]
    return render_template("partials/content/category_options.html", options=options)


# ── Route 15 — content filters management ────────────────────────────────────

@content_bp.route("/filters")
@login_required
@role_required("admin")
def filters():
    """GET /content/filters — admin content filter management."""
    all_filters = ContentFilter.query.order_by(ContentFilter.created_at.desc()).all()
    return render_template("content/filters.html", filters=all_filters)


# ── Route 16 — create filter ──────────────────────────────────────────────────

@content_bp.route("/filters", methods=["POST"])
@login_required
@role_required("admin")
def create_filter():
    """POST /content/filters — create a new content filter."""
    pattern = request.form.get("pattern", "").strip()
    filter_type = request.form.get("filter_type", "").strip()

    if not pattern:
        return _error_fragment("Pattern is required.", 400)
    if filter_type not in ("keyword", "regex"):
        return _error_fragment("Filter type must be 'keyword' or 'regex'.", 400)

    if filter_type == "regex":
        import re
        try:
            re.compile(pattern)
        except re.error as e:
            return _error_fragment(f"Invalid regex: {e}", 400)

    new_filter = ContentFilter(pattern=pattern, filter_type=filter_type, is_active=True)
    db.session.add(new_filter)
    db.session.commit()

    logger.info("ContentFilter created: type=%s pattern=%s", filter_type, pattern)
    return render_template("partials/content/filter_row.html", f=new_filter), 201


# ── Route 17 — toggle filter ──────────────────────────────────────────────────

@content_bp.route("/filters/<int:filter_id>/toggle", methods=["POST"])
@login_required
@role_required("admin")
def toggle_filter(filter_id: int):
    """POST /content/filters/<id>/toggle — flip is_active."""
    f = ContentFilter.query.get_or_404(filter_id)
    f.is_active = not f.is_active
    db.session.commit()
    return render_template("partials/content/filter_row.html", f=f), 200


# ── Route 18 — delete filter ──────────────────────────────────────────────────

@content_bp.route("/filters/<int:filter_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_filter(filter_id: int):
    """DELETE /content/filters/<id> — delete a content filter."""
    f = ContentFilter.query.get_or_404(filter_id)
    db.session.delete(f)
    db.session.commit()
    logger.info("ContentFilter deleted: id=%d", filter_id)
    return "", 200
