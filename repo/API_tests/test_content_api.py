"""
API / integration tests for content endpoints.
Uses the shared app/client/db/login_as fixtures from conftest.py.
"""
from io import BytesIO

import pytest
from app.extensions import db as _db
from app.models.content import Content, ContentFilter, ContentVersion
from app.services import content_service, file_service
from werkzeug.datastructures import FileStorage


# ── Public browse ─────────────────────────────────────────────────────────────

class TestPublicBrowse:
    def test_browse_content_public(self, client):
        """GET /content returns 200 without login."""
        resp = client.get("/content/")
        assert resp.status_code == 200

    def test_browse_shows_only_published(self, client, db, editor_user, sample_content):
        """Draft content is not visible in public browse."""
        resp = client.get("/content/")
        assert resp.status_code == 200
        assert sample_content.title.encode() not in resp.data

    def test_browse_htmx_returns_grid_partial(self, client):
        """HTMX request to /content returns only the grid partial."""
        resp = client.get("/content/", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        # Partial does not include the full page chrome
        assert b"Content Library" not in resp.data

    def test_browse_search_filter(self, client):
        """Browse search parameter is echoed in the filter bar."""
        resp = client.get("/content/?search=Test+Article")
        assert resp.status_code == 200
        # The search value appears in the filter bar input
        assert b"Test+Article" in resp.data or b"Test Article" in resp.data

    def test_browse_search_no_match(self, client):
        """Search with no matching results still returns 200."""
        resp = client.get("/content/?search=zzznomatchwhatsoever")
        assert resp.status_code == 200

    def test_content_view_published(self, client, login_as, editor_user, sample_content):
        """Editor can view their own content via the view endpoint."""
        login_as("editor1", "TestPass123!")
        resp = client.get(f"/content/{sample_content.id}")
        assert resp.status_code == 200
        assert sample_content.title.encode() in resp.data

    def test_content_view_draft_returns_404(self, client, db, editor_user, sample_content):
        """GET /content/<id> for a draft returns 404 to unauthenticated users."""
        resp = client.get(f"/content/{sample_content.id}")
        assert resp.status_code == 404

    def test_content_view_nonexistent_returns_404(self, client):
        """GET /content/99999 returns 404."""
        resp = client.get("/content/99999")
        assert resp.status_code == 404


class TestMediaAccess:
    def test_media_requires_login(self, client, sample_content):
        """Unauthenticated media access redirects to login."""
        with client.application.app_context():
            cover = FileStorage(stream=BytesIO(b"fake-jpg-content"), filename="cover.jpg")
            up = file_service.upload_file(cover, sample_content.id, upload_type="cover")
            assert up["success"] is True
            sample_content.cover_path = up["file_path"]
            _db.session.commit()
            media_path = sample_content.cover_path

        resp = client.get(f"/media/{media_path}", follow_redirects=False)
        assert resp.status_code == 302

    def test_media_draft_blocked_for_non_owner(self, client, login_as, sample_users, sample_content):
        """A non-owner authenticated user cannot access draft media."""
        with client.application.app_context():
            cover = FileStorage(stream=BytesIO(b"fake-jpg-content"), filename="draft-cover.jpg")
            up = file_service.upload_file(cover, sample_content.id, upload_type="cover")
            assert up["success"] is True
            sample_content.cover_path = up["file_path"]
            sample_content.status = "draft"
            _db.session.commit()
            media_path = sample_content.cover_path

        login_as("testcustomer", "TestPass123!")
        resp = client.get(f"/media/{media_path}")
        assert resp.status_code == 403

    def test_media_draft_allowed_for_owner(self, client, login_as, sample_content):
        """Content owner can access their draft media."""
        with client.application.app_context():
            cover = FileStorage(stream=BytesIO(b"fake-jpg-content"), filename="owner-cover.jpg")
            up = file_service.upload_file(cover, sample_content.id, upload_type="cover")
            assert up["success"] is True
            sample_content.cover_path = up["file_path"]
            sample_content.status = "draft"
            _db.session.commit()
            media_path = sample_content.cover_path

        login_as("editor1", "TestPass123!")
        resp = client.get(f"/media/{media_path}")
        assert resp.status_code == 200

    def test_media_published_allowed_for_authenticated_user(self, client, login_as, sample_users, sample_content):
        """Published content media is available to authenticated users."""
        with client.application.app_context():
            cover = FileStorage(stream=BytesIO(b"fake-jpg-content"), filename="public-cover.jpg")
            up = file_service.upload_file(cover, sample_content.id, upload_type="cover")
            assert up["success"] is True
            sample_content.cover_path = up["file_path"]
            sample_content.status = "published"
            _db.session.commit()
            media_path = sample_content.cover_path

        login_as("testcustomer", "TestPass123!")
        resp = client.get(f"/media/{media_path}")
        assert resp.status_code == 200


# ── Editor access control ─────────────────────────────────────────────────────

class TestEditorAccess:
    def test_editor_dashboard_requires_login(self, client):
        """Unauthenticated access to editor dashboard returns 401."""
        resp = client.get("/content/editor")
        assert resp.status_code == 401

    def test_editor_dashboard_requires_role(self, client, login_as, sample_users):
        """Customer cannot access editor dashboard."""
        login_as("testcustomer", "TestPass123!")
        resp = client.get("/content/editor")
        assert resp.status_code == 403

    def test_editor_dashboard_accessible_by_editor(self, client, login_as, editor_user):
        """Editor can access their dashboard."""
        login_as("editor1", "TestPass123!")
        resp = client.get("/content/editor")
        assert resp.status_code == 200

    def test_editor_dashboard_accessible_by_admin(self, client, login_as, sample_users):
        """Admin can access editor dashboard."""
        login_as("testadmin", "TestPass123!")
        resp = client.get("/content/editor")
        assert resp.status_code == 200

    def test_new_form_accessible_by_editor(self, client, login_as, editor_user):
        """Editor can access the new content form."""
        login_as("editor1", "TestPass123!")
        resp = client.get("/content/editor/new")
        assert resp.status_code == 200

    def test_edit_form_requires_ownership(self, client, login_as, db, sample_users, sample_content):
        """Non-owner editor cannot edit another user's content."""
        # Create a second editor
        from app.models.user import User
        from app.services.auth_service import hash_password
        with client.application.app_context():
            other_editor = User(
                username="other_editor",
                email="other@test.com",
                role="editor",
                credit_score=100,
                password_hash=hash_password("TestPass123!"),
            )
            _db.session.add(other_editor)
            _db.session.commit()

        login_as("other_editor", "TestPass123!")
        resp = client.get(f"/content/editor/{sample_content.id}/edit")
        assert resp.status_code == 403


# ── Save content ──────────────────────────────────────────────────────────────

class TestSaveContent:
    def test_create_content_success(self, client, login_as, editor_user):
        """POST /content/editor/save creates content and redirects."""
        login_as("editor1", "TestPass123!")
        resp = client.post("/content/editor/save", data={
            "title": "New Post",
            "content_type": "article",
            "body": "Hello world content here",
            "body_format": "markdown",
            "status": "draft",
        })
        assert resp.status_code in (200, 302)

    def test_create_content_empty_title_fails(self, client, login_as, editor_user):
        """Saving with empty title returns 422."""
        login_as("editor1", "TestPass123!")
        resp = client.post("/content/editor/save", data={
            "title": "",
            "content_type": "article",
            "body": "Body",
            "body_format": "markdown",
            "status": "draft",
        })
        assert resp.status_code == 422

    def test_create_content_with_filter_blocked(
        self, client, login_as, editor_user, sample_filter
    ):
        """Saving content with a filtered keyword returns 422."""
        login_as("editor1", "TestPass123!")
        resp = client.post("/content/editor/save", data={
            "title": "Article with badword",
            "content_type": "article",
            "body": "Normal body",
            "body_format": "markdown",
            "status": "draft",
        })
        assert resp.status_code == 422

    def test_update_existing_content(self, client, login_as, editor_user, sample_content):
        """Posting with content_id updates the existing record."""
        login_as("editor1", "TestPass123!")
        resp = client.post("/content/editor/save", data={
            "content_id": str(sample_content.id),
            "title": "Updated Post Title",
            "content_type": "article",
            "body": "Updated body here",
            "body_format": "markdown",
            "status": "draft",
        })
        assert resp.status_code in (200, 302)
        with client.application.app_context():
            content = Content.query.get(sample_content.id)
            assert content.title == "Updated Post Title"

    def test_save_htmx_returns_hx_redirect(self, client, login_as, editor_user):
        """HTMX POST to editor/save returns HX-Redirect header."""
        login_as("editor1", "TestPass123!")
        resp = client.post(
            "/content/editor/save",
            data={
                "title": "HTMX Created Post",
                "content_type": "article",
                "body": "HTMX body",
                "body_format": "markdown",
                "status": "draft",
            },
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "HX-Redirect" in resp.headers

    def test_editor_cannot_forge_published_status(self, client, login_as, editor_user):
        """Editor posting status=published via save is forced to draft."""
        login_as("editor1", "TestPass123!")
        resp = client.post("/content/editor/save", data={
            "title": "Sneaky Publish Attempt",
            "content_type": "article",
            "body": "Trying to bypass the editorial workflow",
            "body_format": "markdown",
            "status": "published",
        })
        assert resp.status_code in (200, 302)
        with client.application.app_context():
            content = Content.query.filter_by(title="Sneaky Publish Attempt").first()
            assert content is not None
            assert content.status == "draft"

    def test_editor_cannot_forge_in_review_status(self, client, login_as, editor_user):
        """Editor posting status=in_review via save is forced to draft."""
        login_as("editor1", "TestPass123!")
        resp = client.post("/content/editor/save", data={
            "title": "Sneaky Review Attempt",
            "content_type": "article",
            "body": "Trying to skip submit-for-review endpoint",
            "body_format": "markdown",
            "status": "in_review",
        })
        assert resp.status_code in (200, 302)
        with client.application.app_context():
            content = Content.query.filter_by(title="Sneaky Review Attempt").first()
            assert content is not None
            assert content.status == "draft"


# ── Cross-editor content isolation ────────────────────────────────────────────

class TestCrossEditorIsolation:
    def test_other_editor_cannot_view_draft(self, client, login_as, db, sample_content):
        """Editor B viewing editor A's draft content gets 404."""
        from app.models.user import User
        from app.services.auth_service import hash_password
        with client.application.app_context():
            other = User(
                username="editor2_isolation",
                email="editor2_isolation@test.com",
                role="editor",
                credit_score=100,
                password_hash=hash_password("TestPass123!"),
            )
            _db.session.add(other)
            _db.session.commit()

        login_as("editor2_isolation", "TestPass123!")
        resp = client.get(f"/content/{sample_content.id}")
        assert resp.status_code == 404

    def test_admin_can_view_any_draft(self, client, login_as, db, sample_users, sample_content):
        """Admin can view any editor's draft content."""
        login_as("testadmin", "TestPass123!")
        resp = client.get(f"/content/{sample_content.id}")
        assert resp.status_code == 200

    def test_author_can_view_own_draft(self, client, login_as, db, editor_user, sample_content):
        """Content author can view their own draft content."""
        login_as("editor1", "TestPass123!")
        resp = client.get(f"/content/{sample_content.id}")
        assert resp.status_code == 200


# ── Workflow endpoints ─────────────────────────────────────────────────────────

class TestWorkflowEndpoints:
    def test_submit_for_review(self, client, login_as, editor_user, sample_content):
        """POST /<id>/submit-review changes status to in_review."""
        login_as("editor1", "TestPass123!")
        resp = client.post(f"/content/{sample_content.id}/submit-review")
        assert resp.status_code == 200
        with client.application.app_context():
            content = Content.query.get(sample_content.id)
            assert content.status == "in_review"

    def test_submit_review_requires_editor(self, client, login_as, sample_users, sample_content):
        """Customer cannot submit content for review."""
        login_as("testcustomer", "TestPass123!")
        resp = client.post(f"/content/{sample_content.id}/submit-review")
        assert resp.status_code == 403

    def test_publish_content(self, client, login_as, sample_users, editor_user, sample_content):
        """POST /<id>/publish sets status to published (admin only)."""
        # First move to in_review
        with client.application.app_context():
            sample_content.status = "in_review"
            _db.session.commit()

        login_as("testadmin", "TestPass123!")
        resp = client.post(f"/content/{sample_content.id}/publish")
        assert resp.status_code == 200
        with client.application.app_context():
            content = Content.query.get(sample_content.id)
            assert content.status == "published"

    def test_publish_requires_admin(self, client, login_as, editor_user, sample_content):
        """Editor cannot publish content."""
        with client.application.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
        login_as("editor1", "TestPass123!")
        resp = client.post(f"/content/{sample_content.id}/publish")
        assert resp.status_code == 403

    def test_reject_content(self, client, login_as, sample_users, editor_user, sample_content):
        """POST /<id>/reject sets status back to draft with a note."""
        with client.application.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            f"/content/{sample_content.id}/reject",
            data={"rejection_note": "Needs significant revision."},
        )
        assert resp.status_code == 200
        with client.application.app_context():
            content = Content.query.get(sample_content.id)
            assert content.status == "draft"

    def test_reject_without_note_fails(self, client, login_as, sample_users, editor_user, sample_content):
        """POST /<id>/reject with no note returns 400."""
        with client.application.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            f"/content/{sample_content.id}/reject",
            data={"rejection_note": ""},
        )
        assert resp.status_code == 400


# ── Version history ───────────────────────────────────────────────────────────

class TestVersionHistory:
    def test_version_history(self, client, login_as, editor_user, sample_content):
        """GET /content/<id>/history returns 200 with version data."""
        login_as("editor1", "TestPass123!")
        resp = client.get(f"/content/{sample_content.id}/history")
        assert resp.status_code == 200
        assert b"Version History" in resp.data

    def test_version_history_requires_editor(self, client, login_as, sample_users, sample_content):
        """Customer cannot view version history."""
        login_as("testcustomer", "TestPass123!")
        resp = client.get(f"/content/{sample_content.id}/history")
        assert resp.status_code == 403

    def test_rollback_via_api(self, client, login_as, editor_user, sample_content):
        """POST /<id>/rollback/<version_id> succeeds and redirects."""
        login_as("editor1", "TestPass123!")
        # Create a second version by updating
        client.post("/content/editor/save", data={
            "content_id": str(sample_content.id),
            "title": "Modified Title",
            "content_type": "article",
            "body": "Modified body",
            "body_format": "markdown",
            "status": "draft",
        })
        with client.application.app_context():
            v1 = ContentVersion.query.filter_by(
                content_id=sample_content.id, version_number=1
            ).first()
            v1_id = v1.id

        resp = client.post(
            f"/content/{sample_content.id}/rollback/{v1_id}",
            follow_redirects=False,
        )
        # Should redirect or return HX-Redirect
        assert resp.status_code in (200, 302)

    def test_rollback_other_editor_forbidden(self, client, login_as, sample_content):
        """A different editor cannot rollback content they do not own."""
        from app.models.user import User
        from app.services.auth_service import hash_password

        with client.application.app_context():
            other_editor = User(
                username="api_rollback_other_editor",
                email="api_rollback_other_editor@test.com",
                role="editor",
                credit_score=100,
                password_hash=hash_password("TestPass123!"),
            )
            _db.session.add(other_editor)
            _db.session.commit()

            v1 = ContentVersion.query.filter_by(
                content_id=sample_content.id, version_number=1
            ).first()
            v1_id = v1.id

        login_as("api_rollback_other_editor", "TestPass123!")
        resp = client.post(
            f"/content/{sample_content.id}/rollback/{v1_id}",
            follow_redirects=False,
        )
        assert resp.status_code == 403


# ── Markdown preview ──────────────────────────────────────────────────────────

class TestMarkdownPreview:
    def test_markdown_preview_endpoint(self, client, login_as, editor_user):
        """POST /content/preview returns rendered HTML."""
        login_as("editor1", "TestPass123!")
        resp = client.post("/content/preview", data={"body": "# Test Heading"})
        assert resp.status_code == 200
        assert b"Test Heading" in resp.data

    def test_markdown_preview_requires_editor(self, client, login_as, sample_users):
        """Customer cannot access the preview endpoint."""
        login_as("testcustomer", "TestPass123!")
        resp = client.post("/content/preview", data={"body": "# Hello"})
        assert resp.status_code == 403

    def test_markdown_preview_bold(self, client, login_as, editor_user):
        """Bold markdown is rendered as <strong>."""
        login_as("editor1", "TestPass123!")
        resp = client.post("/content/preview", data={"body": "**bold**"})
        assert resp.status_code == 200
        assert b"<strong>" in resp.data


# ── XSS / HTML sanitization ──────────────────────────────────────────────────

class TestXSSSanitization:
    """Verify that bleach strips dangerous HTML before it reaches any response."""

    def test_preview_strips_script_tag(self, client, login_as, editor_user):
        """POST /content/preview with a <script> payload must strip the tag itself."""
        login_as("editor1", "TestPass123!")
        resp = client.post(
            "/content/preview",
            data={"body": "<script>alert('xss')</script>Legit content."},
        )
        assert resp.status_code == 200
        # bleach strips the tag; inner text may remain as inert plain text — that is safe
        assert b"<script>" not in resp.data
        assert b"</script>" not in resp.data

    def test_preview_strips_onerror_attribute(self, client, login_as, editor_user):
        """onerror event handler injected via an img tag must be removed."""
        login_as("editor1", "TestPass123!")
        resp = client.post(
            "/content/preview",
            data={"body": '<img src="x" onerror="alert(1)">'},
        )
        assert resp.status_code == 200
        assert b"onerror" not in resp.data

    def test_preview_strips_style_tag(self, client, login_as, editor_user):
        """<style> blocks are stripped from preview output."""
        login_as("editor1", "TestPass123!")
        resp = client.post(
            "/content/preview",
            data={"body": "<style>body{display:none}</style>Normal text."},
        )
        assert resp.status_code == 200
        assert b"<style>" not in resp.data

    def test_save_script_tag_stripped_from_rendered_preview(
        self, client, login_as, editor_user, db
    ):
        """When a body containing <script> is run through the preview endpoint, the
        tag is absent from the sanitized HTML fragment returned."""
        login_as("editor1", "TestPass123!")
        # Use the preview endpoint to render the dangerous body — this exercises
        # the same sanitization path as the content renderer.
        resp = client.post(
            "/content/preview",
            data={"body": "<script>alert('stored-xss')</script>Safe paragraph."},
        )
        assert resp.status_code == 200
        assert b"<script>" not in resp.data
        assert b"</script>" not in resp.data
        # The safe surrounding text must still be present.
        assert b"Safe paragraph" in resp.data

    def test_preview_safe_markdown_preserved(self, client, login_as, editor_user):
        """Legitimate markdown (headers, bold) survives sanitization intact."""
        login_as("editor1", "TestPass123!")
        resp = client.post(
            "/content/preview",
            data={"body": "## Safe Heading\n\n**bold text** and _italic_."},
        )
        assert resp.status_code == 200
        assert b"Safe Heading" in resp.data
        assert b"<strong>" in resp.data or b"bold" in resp.data


# ── Analytics heartbeat ───────────────────────────────────────────────────────

class TestHeartbeat:
    def test_heartbeat_endpoint(self, client, login_as, sample_users):
        """POST /analytics/heartbeat returns 204."""
        login_as("testcustomer", "TestPass123!")
        resp = client.post(
            "/analytics/heartbeat",
            data={"content_id": "1", "page": "/content/1"},
        )
        assert resp.status_code == 204

    def test_heartbeat_anonymous(self, client):
        """Unauthenticated heartbeat also returns 204 (no auth required)."""
        resp = client.post(
            "/analytics/heartbeat",
            data={"content_id": "5", "page": "/content/5"},
        )
        assert resp.status_code == 204

    def test_heartbeat_no_content_id(self, client):
        """Heartbeat with no content_id still returns 204."""
        resp = client.post("/analytics/heartbeat", data={"page": "/content/1"})
        assert resp.status_code == 204


# ── Content filters management ─────────────────────────────────────────────────

class TestFilterManagement:
    def test_filters_page_requires_admin(self, client, login_as, editor_user):
        """Editor cannot access filters management page."""
        login_as("editor1", "TestPass123!")
        resp = client.get("/content/filters")
        assert resp.status_code == 403

    def test_filters_page_accessible_by_admin(self, client, login_as, sample_users):
        """Admin can view filters page."""
        login_as("testadmin", "TestPass123!")
        resp = client.get("/content/filters")
        assert resp.status_code == 200

    def test_create_keyword_filter(self, client, login_as, sample_users):
        """Admin can create a keyword filter."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            "/content/filters",
            data={"pattern": "spamword", "filter_type": "keyword"},
        )
        assert resp.status_code == 201
        with client.application.app_context():
            f = ContentFilter.query.filter_by(pattern="spamword").first()
            assert f is not None
            assert f.is_active is True

    def test_create_regex_filter(self, client, login_as, sample_users):
        """Admin can create a valid regex filter."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            "/content/filters",
            data={"pattern": r"\b\d{4}\b", "filter_type": "regex"},
        )
        assert resp.status_code == 201

    def test_create_invalid_regex_rejected(self, client, login_as, sample_users):
        """Invalid regex pattern is rejected with 400."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            "/content/filters",
            data={"pattern": "[unclosed(", "filter_type": "regex"},
        )
        assert resp.status_code == 400

    def test_create_empty_pattern_rejected(self, client, login_as, sample_users):
        """Empty pattern is rejected with 400."""
        login_as("testadmin", "TestPass123!")
        resp = client.post(
            "/content/filters",
            data={"pattern": "", "filter_type": "keyword"},
        )
        assert resp.status_code == 400

    def test_toggle_filter(self, client, login_as, sample_users, sample_filter):
        """POST /filters/<id>/toggle flips is_active."""
        login_as("testadmin", "TestPass123!")
        original_state = sample_filter.is_active
        resp = client.post(f"/content/filters/{sample_filter.id}/toggle")
        assert resp.status_code == 200
        with client.application.app_context():
            f = ContentFilter.query.get(sample_filter.id)
            assert f.is_active is not original_state

    def test_delete_filter(self, client, login_as, sample_users, sample_filter):
        """DELETE /filters/<id> removes the record."""
        login_as("testadmin", "TestPass123!")
        filter_id = sample_filter.id
        resp = client.delete(f"/content/filters/{filter_id}")
        assert resp.status_code == 200
        with client.application.app_context():
            assert ContentFilter.query.get(filter_id) is None

    def test_delete_filter_requires_admin(self, client, login_as, editor_user, sample_filter):
        """Editor cannot delete a filter."""
        login_as("editor1", "TestPass123!")
        resp = client.delete(f"/content/filters/{sample_filter.id}")
        assert resp.status_code == 403


# ── Categories autocomplete ───────────────────────────────────────────────────

class TestCategories:
    def test_categories_endpoint(self, client):
        """GET /content/categories returns 200."""
        resp = client.get("/content/categories?q=well")
        assert resp.status_code == 200

    def test_categories_returns_options(self, client):
        """GET /content/categories returns 200 (options populated from published content)."""
        resp = client.get("/content/categories?q=")
        assert resp.status_code == 200


# ── Content deletion ──────────────────────────────────────────────────────────

class TestContentDeletion:
    def test_owner_can_delete_own_content(self, client, login_as, editor_user, sample_content, db):
        """DELETE /content/editor/<id> succeeds for the content owner."""
        content_id = sample_content.id
        login_as("editor1", "TestPass123!")
        resp = client.delete(f"/content/editor/{content_id}", follow_redirects=False)
        assert resp.status_code in (200, 302)
        with client.application.app_context():
            assert Content.query.get(content_id) is None

    def test_other_editor_cannot_delete(self, client, login_as, sample_content, db):
        """A different editor cannot delete content they don't own."""
        from app.models.user import User
        from app.services.auth_service import hash_password
        with client.application.app_context():
            other = User(
                username="delete_other_editor",
                email="delete_other@test.com",
                role="editor",
                credit_score=100,
                password_hash=hash_password("TestPass123!"),
            )
            _db.session.add(other)
            _db.session.commit()

        login_as("delete_other_editor", "TestPass123!")
        resp = client.delete(f"/content/editor/{sample_content.id}")
        assert resp.status_code == 403
        with client.application.app_context():
            assert Content.query.get(sample_content.id) is not None

    def test_admin_can_delete_any_content(self, client, login_as, sample_users, editor_user,
                                           sample_content, db):
        """Admin can delete any editor's content."""
        content_id = sample_content.id
        login_as("testadmin", "TestPass123!")
        resp = client.delete(f"/content/editor/{content_id}", follow_redirects=False)
        assert resp.status_code in (200, 302)
        with client.application.app_context():
            assert Content.query.get(content_id) is None

    def test_delete_nonexistent_content_returns_error(self, client, login_as, editor_user):
        """DELETE /content/editor/99999 returns 400 or 404 — not 500."""
        login_as("editor1", "TestPass123!")
        resp = client.delete("/content/editor/99999")
        assert resp.status_code in (400, 404)

    def test_delete_requires_login(self, client, sample_content):
        """Unauthenticated DELETE is rejected."""
        resp = client.delete(f"/content/editor/{sample_content.id}")
        assert resp.status_code in (302, 401)

    def test_customer_cannot_delete_content(self, client, login_as, sample_users, sample_content):
        """Customer role cannot access the delete endpoint."""
        login_as("testcustomer", "TestPass123!")
        resp = client.delete(f"/content/editor/{sample_content.id}")
        assert resp.status_code == 403

    def test_delete_htmx_returns_hx_redirect(self, client, login_as, editor_user, sample_content):
        """HTMX DELETE returns HX-Redirect to the editor dashboard."""
        login_as("editor1", "TestPass123!")
        resp = client.delete(
            f"/content/editor/{sample_content.id}",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "HX-Redirect" in resp.headers
