from datetime import datetime
from ..extensions import db


class Content(db.Model):
    __tablename__ = "content"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    content_type = db.Column(db.String(20), nullable=False)  # "article", "chapter", "book"
    body = db.Column(db.Text, nullable=True)
    body_format = db.Column(db.String(10), nullable=False, default="richtext")  # "richtext", "markdown"
    status = db.Column(db.String(20), nullable=False, default="draft")  # "draft", "in_review", "published"
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    tags = db.Column(db.Text, default="[]")  # JSON list
    cover_path = db.Column(db.String(500), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("content.id"), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    current_version = db.Column(db.Integer, default=1)
    published_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship("User", back_populates="authored_content", foreign_keys=[author_id])
    parent = db.relationship("Content", remote_side=[id], backref=db.backref("children", lazy="dynamic"))
    versions = db.relationship("ContentVersion", back_populates="content", lazy="dynamic")
    attachments = db.relationship("ContentAttachment", back_populates="content", lazy="dynamic")

    def __repr__(self):
        return f"<Content '{self.title}' [{self.status}]>"


class ContentVersion(db.Model):
    __tablename__ = "content_versions"

    id = db.Column(db.Integer, primary_key=True)
    content_id = db.Column(db.Integer, db.ForeignKey("content.id"), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    change_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    content = db.relationship("Content", back_populates="versions")
    created_by_user = db.relationship("User", back_populates="content_versions", foreign_keys=[created_by])

    def __repr__(self):
        return f"<ContentVersion content={self.content_id} v{self.version_number}>"


class ContentAttachment(db.Model):
    __tablename__ = "content_attachments"

    id = db.Column(db.Integer, primary_key=True)
    content_id = db.Column(db.Integer, db.ForeignKey("content.id"), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(300), nullable=False)
    file_type = db.Column(db.String(10), nullable=False)  # "jpg", "png", "pdf"
    file_size = db.Column(db.Integer, nullable=False)  # bytes
    fingerprint = db.Column(db.String(64), nullable=False)  # SHA-256
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    content = db.relationship("Content", back_populates="attachments")

    def __repr__(self):
        return f"<ContentAttachment {self.original_filename}>"


class ContentFilter(db.Model):
    __tablename__ = "content_filters"

    id = db.Column(db.Integer, primary_key=True)
    pattern = db.Column(db.String(500), nullable=False)
    filter_type = db.Column(db.String(10), nullable=False)  # "keyword", "regex"
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ContentFilter [{self.filter_type}] {self.pattern[:40]}>"
