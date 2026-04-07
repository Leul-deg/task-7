"""
Unit tests for content management business logic.
Covers: content_service, file_service, content_filter_service.
"""
import pytest
from io import BytesIO

from werkzeug.datastructures import FileStorage

from app.extensions import db as _db
from app.models.content import Content, ContentVersion, ContentAttachment, ContentFilter
from app.services import content_service, file_service
from app.services.content_filter_service import filter_content


# ── test_create_draft ─────────────────────────────────────────────────────────

class TestCreateDraft:
    def test_create_draft(self, app, db, editor_user):
        """Content saved with status 'draft'."""
        with app.app_context():
            result = content_service.save_content(None, {
                "title": "New Article",
                "content_type": "article",
                "body": "Some body text here",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            assert result["success"] is True
            content = Content.query.get(result["content_id"])
            assert content.status == "draft"
            assert content.title == "New Article"

    def test_create_sets_author(self, app, db, editor_user):
        """Created content is owned by the submitting author."""
        with app.app_context():
            result = content_service.save_content(None, {
                "title": "Authored Article",
                "content_type": "article",
                "body": "Body",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            content = Content.query.get(result["content_id"])
            assert content.author_id == editor_user.id

    def test_title_required(self, app, db, editor_user):
        """Empty title is rejected."""
        with app.app_context():
            result = content_service.save_content(None, {
                "title": "   ",
                "content_type": "article",
                "body": "Body",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            assert result["success"] is False
            assert "required" in result["reason"].lower()

    def test_title_max_length(self, app, db, editor_user):
        """Title exceeding 300 characters is rejected."""
        with app.app_context():
            result = content_service.save_content(None, {
                "title": "x" * 301,
                "content_type": "article",
                "body": "Body",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            assert result["success"] is False
            assert "300" in result["reason"]


# ── test_version_tracking ─────────────────────────────────────────────────────

class TestVersionTracking:
    def test_create_content_creates_version(self, app, db, editor_user):
        """Creating content also creates a version 1 record."""
        with app.app_context():
            result = content_service.save_content(None, {
                "title": "Versioned Article",
                "content_type": "article",
                "body": "Body",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            versions = ContentVersion.query.filter_by(content_id=result["content_id"]).all()
            assert len(versions) == 1
            assert versions[0].version_number == 1
            assert versions[0].change_note == "Initial creation"

    def test_update_content_creates_snapshot(self, app, db, editor_user, sample_content):
        """Updating content creates a version snapshot of the previous state."""
        with app.app_context():
            old_body = sample_content.body
            result = content_service.save_content(sample_content.id, {
                "title": "Updated Title",
                "content_type": "article",
                "body": "Updated body text",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            assert result["success"] is True
            versions = (
                ContentVersion.query
                .filter_by(content_id=sample_content.id)
                .order_by(ContentVersion.version_number.asc())
                .all()
            )
            assert len(versions) >= 2
            # Earliest version contains the original body
            assert versions[0].body == old_body

    def test_update_increments_version_number(self, app, db, editor_user, sample_content):
        """current_version is incremented on each save."""
        with app.app_context():
            original_version = sample_content.current_version
            content_service.save_content(sample_content.id, {
                "title": "Updated Title",
                "content_type": "article",
                "body": "Updated body",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            content = Content.query.get(sample_content.id)
            assert content.current_version == original_version + 1


# ── test_workflow ─────────────────────────────────────────────────────────────

class TestWorkflow:
    def test_submit_for_review(self, app, db, editor_user, sample_content):
        """Status changes from draft to in_review."""
        with app.app_context():
            result = content_service.submit_for_review(sample_content.id, editor_user.id)
            assert result["success"] is True
            content = Content.query.get(sample_content.id)
            assert content.status == "in_review"

    def test_submit_non_draft_fails(self, app, db, editor_user, sample_content):
        """Cannot submit already in-review content."""
        with app.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
            result = content_service.submit_for_review(sample_content.id, editor_user.id)
            assert result["success"] is False
            assert "draft" in result["reason"].lower()

    def test_submit_wrong_owner_fails(self, app, db, sample_users, sample_content):
        """Non-owner non-admin cannot submit for review."""
        with app.app_context():
            result = content_service.submit_for_review(
                sample_content.id, sample_users["customer"].id
            )
            assert result["success"] is False

    def test_publish_creates_version(self, app, db, sample_users, editor_user, sample_content):
        """Publishing creates a new ContentVersion with status 'published'."""
        with app.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
            result = content_service.publish_content(sample_content.id, sample_users["admin"].id)
            assert result["success"] is True
            content = Content.query.get(sample_content.id)
            assert content.status == "published"
            assert content.published_at is not None
            versions = ContentVersion.query.filter_by(content_id=sample_content.id).all()
            assert any(v.status == "published" for v in versions)

    def test_publish_requires_admin(self, app, db, editor_user, sample_content):
        """Non-admin cannot publish."""
        with app.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
            result = content_service.publish_content(sample_content.id, editor_user.id)
            assert result["success"] is False
            assert "admin" in result["reason"].lower()

    def test_publish_requires_in_review_status(self, app, db, sample_users, sample_content):
        """Publishing a draft (not in_review) is rejected."""
        with app.app_context():
            result = content_service.publish_content(
                sample_content.id, sample_users["admin"].id
            )
            assert result["success"] is False
            assert "review" in result["reason"].lower()

    def test_reject_requires_note(self, app, db, sample_users, sample_content):
        """Rejection without note fails."""
        with app.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
            result = content_service.reject_content(
                sample_content.id, sample_users["admin"].id, ""
            )
            assert result["success"] is False
            assert "note" in result["reason"].lower()

    def test_reject_short_note_fails(self, app, db, sample_users, sample_content):
        """Rejection note shorter than 5 chars is rejected."""
        with app.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
            result = content_service.reject_content(
                sample_content.id, sample_users["admin"].id, "bad"
            )
            assert result["success"] is False

    def test_reject_returns_to_draft(self, app, db, sample_users, editor_user, sample_content):
        """Rejected content status reverts to draft."""
        with app.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
            result = content_service.reject_content(
                sample_content.id,
                sample_users["admin"].id,
                "Needs more detail please.",
            )
            assert result["success"] is True
            content = Content.query.get(sample_content.id)
            assert content.status == "draft"

    def test_reject_saves_note_in_version(self, app, db, sample_users, editor_user, sample_content):
        """Rejection note is stored in the ContentVersion snapshot."""
        with app.app_context():
            sample_content.status = "in_review"
            _db.session.commit()
            note = "Please revise the introduction."
            content_service.reject_content(
                sample_content.id, sample_users["admin"].id, note
            )
            versions = ContentVersion.query.filter_by(
                content_id=sample_content.id, status="rejected"
            ).all()
            assert len(versions) == 1
            assert versions[0].change_note == note


# ── test_rollback ─────────────────────────────────────────────────────────────

class TestRollback:
    def test_rollback_restores_body(self, app, db, editor_user, sample_content):
        """Rollback restores body to selected version."""
        with app.app_context():
            original_body = sample_content.body
            content_service.save_content(sample_content.id, {
                "title": sample_content.title,
                "content_type": "article",
                "body": "Completely different body",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            assert Content.query.get(sample_content.id).body == "Completely different body"

            version1 = ContentVersion.query.filter_by(
                content_id=sample_content.id, version_number=1
            ).first()
            result = content_service.rollback_to_version(
                sample_content.id, version1.id, editor_user.id
            )
            assert result["success"] is True
            restored = Content.query.get(sample_content.id)
            assert restored.body == original_body
            assert restored.status == "draft"

    def test_rollback_sets_draft(self, app, db, editor_user, sample_content):
        """Rollback always resets status to draft regardless of prior status."""
        with app.app_context():
            sample_content.status = "published"
            _db.session.commit()
            version1 = ContentVersion.query.filter_by(
                content_id=sample_content.id, version_number=1
            ).first()
            content_service.rollback_to_version(
                sample_content.id, version1.id, editor_user.id
            )
            assert Content.query.get(sample_content.id).status == "draft"

    def test_rollback_wrong_content_fails(self, app, db, editor_user, sample_content):
        """Rolling back with a version_id from a different content fails."""
        with app.app_context():
            # Create a second piece of content with its own version
            result2 = content_service.save_content(None, {
                "title": "Other Article",
                "content_type": "article",
                "body": "Other body",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            other_version = ContentVersion.query.filter_by(
                content_id=result2["content_id"]
            ).first()
            # Try to apply other_version to sample_content
            result = content_service.rollback_to_version(
                sample_content.id, other_version.id, editor_user.id
            )
            assert result["success"] is False

    def test_rollback_other_editor_fails(self, app, db, sample_users, sample_content):
        """A non-owner editor cannot rollback someone else's content."""
        from app.models.user import User
        from app.services.auth_service import hash_password

        with app.app_context():
            other_editor = User(
                username="rollback_other_editor",
                email="rollback_other_editor@test.com",
                role="editor",
                credit_score=100,
                password_hash=hash_password("TestPass123!"),
            )
            _db.session.add(other_editor)
            _db.session.commit()

            version1 = ContentVersion.query.filter_by(
                content_id=sample_content.id, version_number=1
            ).first()
            result = content_service.rollback_to_version(
                sample_content.id, version1.id, other_editor.id
            )
            assert result["success"] is False
            assert "own content" in result["reason"].lower()


# ── test_content_filters ──────────────────────────────────────────────────────

class TestContentFilters:
    def test_content_filter_keyword(self, app, db, editor_user, sample_filter):
        """Content containing a filtered keyword is blocked."""
        with app.app_context():
            result = content_service.save_content(None, {
                "title": "Article with badword inside",
                "content_type": "article",
                "body": "Normal body",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            assert result["success"] is False
            assert len(result["violations"]) > 0

    def test_filter_in_body_blocked(self, app, db, editor_user, sample_filter):
        """Filtered keyword in body is caught."""
        with app.app_context():
            result = content_service.save_content(None, {
                "title": "Clean Title",
                "content_type": "article",
                "body": "This body has badword in it.",
                "body_format": "markdown",
                "status": "draft",
            }, editor_user.id)
            assert result["success"] is False
            assert any(v["match"].lower() == "badword" for v in result["violations"])

    def test_content_filter_regex(self, app, db):
        """Regex filter catches matching patterns."""
        with app.app_context():
            regex_filter = ContentFilter(
                pattern=r"\b\d{3}-\d{2}-\d{4}\b",
                filter_type="regex",
                is_active=True,
            )
            _db.session.add(regex_filter)
            _db.session.commit()
            result = filter_content("My SSN is 123-45-6789 please help")
            assert result["passed"] is False
            assert len(result["violations"]) == 1
            assert result["violations"][0]["filter_type"] == "regex"

    def test_content_filter_inactive_ignored(self, app, db):
        """Inactive filters are not applied."""
        with app.app_context():
            f = ContentFilter(pattern="testword", filter_type="keyword", is_active=False)
            _db.session.add(f)
            _db.session.commit()
            result = filter_content("This has testword in it")
            assert result["passed"] is True
            assert result["violations"] == []

    def test_filter_empty_text_passes(self, app, db, sample_filter):
        """Empty or None text always passes filtering."""
        with app.app_context():
            assert filter_content("") == {"passed": True, "violations": []}
            assert filter_content(None) == {"passed": True, "violations": []}

    def test_filter_case_insensitive(self, app, db):
        """Keyword filter is case-insensitive."""
        with app.app_context():
            f = ContentFilter(pattern="Spam", filter_type="keyword", is_active=True)
            _db.session.add(f)
            _db.session.commit()
            result = filter_content("This contains SPAM in uppercase")
            assert result["passed"] is False

    def test_invalid_regex_skipped(self, app, db):
        """A filter with an invalid regex pattern is skipped without crashing."""
        with app.app_context():
            bad = ContentFilter(pattern="[invalid(", filter_type="regex", is_active=True)
            _db.session.add(bad)
            _db.session.commit()
            result = filter_content("Some safe text here")
            # Should not raise; bad pattern is warned and skipped
            assert isinstance(result, dict)
            assert "passed" in result


# ── test_file_service ─────────────────────────────────────────────────────────

class TestFileService:
    def test_file_upload_validates_type(self, app, db, sample_content):
        """Executable file is rejected."""
        with app.app_context():
            bad_file = FileStorage(stream=BytesIO(b"fake data"), filename="hack.exe")
            result = file_service.upload_file(bad_file, sample_content.id)
            assert result["success"] is False
            assert ".exe" in result["reason"]

    def test_file_upload_validates_size(self, app, db, sample_content):
        """File over 10 MB is rejected."""
        with app.app_context():
            large_data = b"x" * (11 * 1024 * 1024)
            big_file = FileStorage(stream=BytesIO(large_data), filename="big.jpg")
            result = file_service.upload_file(big_file, sample_content.id)
            assert result["success"] is False
            assert "10 MB" in result["reason"]

    def test_duplicate_file_rejected(self, app, db, sample_content):
        """Same file uploaded twice is rejected by fingerprint."""
        with app.app_context():
            data = b"unique test content for dedup"
            file1 = FileStorage(stream=BytesIO(data), filename="photo1.jpg")
            result1 = file_service.upload_file(file1, sample_content.id)
            assert result1["success"] is True

            file2 = FileStorage(stream=BytesIO(data), filename="photo2.jpg")
            result2 = file_service.upload_file(file2, sample_content.id)
            assert result2["success"] is False
            assert "already been uploaded" in result2["reason"]

    def test_file_upload_no_filename(self, app, db, sample_content):
        """FileStorage with no filename is rejected."""
        with app.app_context():
            empty = FileStorage(stream=BytesIO(b""), filename="")
            result = file_service.upload_file(empty, sample_content.id)
            assert result["success"] is False
            assert "No file" in result["reason"]

    def test_file_upload_success_returns_attachment_id(self, app, db, sample_content):
        """Successful upload returns attachment_id and creates DB record."""
        with app.app_context():
            data = b"valid jpg content for upload test"
            f = FileStorage(stream=BytesIO(data), filename="image.jpg")
            result = file_service.upload_file(f, sample_content.id)
            assert result["success"] is True
            assert "attachment_id" in result
            att = ContentAttachment.query.get(result["attachment_id"])
            assert att is not None
            assert att.content_id == sample_content.id
            assert att.original_filename == "image.jpg"

    def test_delete_file_removes_record(self, app, db, sample_content):
        """delete_file removes the ContentAttachment record."""
        with app.app_context():
            data = b"content to delete later"
            f = FileStorage(stream=BytesIO(data), filename="todelete.jpg")
            upload = file_service.upload_file(f, sample_content.id)
            assert upload["success"] is True
            att_id = upload["attachment_id"]

            result = file_service.delete_file(att_id)
            assert result["success"] is True
            assert ContentAttachment.query.get(att_id) is None

    def test_delete_nonexistent_file(self, app, db):
        """Deleting a non-existent attachment returns a clear error."""
        with app.app_context():
            result = file_service.delete_file(99999)
            assert result["success"] is False
            assert "not found" in result["reason"].lower()


# ── test_markdown_preview ─────────────────────────────────────────────────────

class TestMarkdownPreview:
    def test_markdown_preview(self, app):
        """Markdown is converted to HTML."""
        with app.app_context():
            html = content_service.preview_markdown("# Hello\n**Bold text**")
            assert "<h1>" in html or "<h1 " in html
            assert "<strong>" in html

    def test_empty_preview(self, app):
        """Empty input returns empty string."""
        with app.app_context():
            html = content_service.preview_markdown("")
            assert html == ""

    def test_preview_code_block(self, app):
        """Code fences are rendered."""
        with app.app_context():
            html = content_service.preview_markdown("```python\nprint('hi')\n```")
            assert "<code" in html


# ── test_dashboard ────────────────────────────────────────────────────────────

class TestEditorDashboard:
    def test_editor_dashboard_editors_see_own(self, app, db, editor_user, sample_content):
        """Editors see only their own content."""
        with app.app_context():
            items = content_service.get_editor_dashboard(editor_user.id, "editor")
            assert len(items) >= 1
            assert all(item["author_name"] == editor_user.username for item in items)

    def test_admin_dashboard_sees_all(self, app, db, sample_users, editor_user, sample_content):
        """Admins see all content regardless of author."""
        with app.app_context():
            items = content_service.get_editor_dashboard(
                sample_users["admin"].id, "admin"
            )
            assert len(items) >= 1

    def test_dashboard_status_color(self, app, db, editor_user, sample_content):
        """Status color field is present and correct for draft content."""
        with app.app_context():
            items = content_service.get_editor_dashboard(editor_user.id, "editor")
            draft_item = next(
                (i for i in items if i["id"] == sample_content.id), None
            )
            assert draft_item is not None
            assert draft_item["status_color"] == "gray"

    def test_published_content_visible_in_browse(self, app, db, sample_users, editor_user, sample_content):
        """Published content appears in get_published_content."""
        with app.app_context():
            # Publish via workflow
            sample_content.status = "in_review"
            _db.session.commit()
            content_service.publish_content(sample_content.id, sample_users["admin"].id)
            result = content_service.get_published_content()
            ids = [item["id"] for item in result["items"]]
            assert sample_content.id in ids

    def test_draft_not_in_published(self, app, db, editor_user, sample_content):
        """Draft content does not appear in public browse."""
        with app.app_context():
            result = content_service.get_published_content()
            ids = [item["id"] for item in result["items"]]
            assert sample_content.id not in ids

    def test_tags_serialised_correctly(self, app, db, editor_user):
        """Tags provided as a comma-separated string are stored and returned as list."""
        with app.app_context():
            result = content_service.save_content(None, {
                "title": "Tagged Article",
                "content_type": "article",
                "body": "Body",
                "body_format": "markdown",
                "status": "draft",
                "tags": "yoga, wellness, beginner",
            }, editor_user.id)
            import json
            content = Content.query.get(result["content_id"])
            tags = json.loads(content.tags)
            assert "yoga" in tags
            assert "wellness" in tags
            assert "beginner" in tags
