"""
Request-logging middleware.

Registers before/after request hooks on the Flask app:
  before_request — assigns a UUID request_id and records start time in g
  after_request  — writes a LogEntry row with latency, status, endpoint

Also registers POST /analytics/client-error to accept client-side errors.
"""
import logging
import time
import uuid

from flask import Flask, g, request, jsonify

from app.extensions import db

logger = logging.getLogger(__name__)

# Prefixes whose log chatter we suppress (static assets, favicon, etc.)
_SKIP_PREFIXES = ("/static/", "/favicon")


def _should_skip() -> bool:
    path = request.path or ""
    return any(path.startswith(p) for p in _SKIP_PREFIXES)


def register_middleware(app: Flask) -> None:
    """Attach before/after request hooks and the client-error endpoint."""

    @app.before_request
    def _before():
        g.request_id = str(uuid.uuid4())
        g.start_time = time.monotonic()

    @app.after_request
    def _after(response):
        if _should_skip():
            return response

        elapsed_ms = round((time.monotonic() - g.get("start_time", time.monotonic())) * 1000, 2)

        if response.status_code >= 500:
            level = "ERROR"
        elif response.status_code >= 400:
            level = "WARNING"
        else:
            level = "INFO"

        try:
            from flask_login import current_user
            user_id = current_user.id if current_user.is_authenticated else None
        except Exception:
            user_id = None

        try:
            from app.models.ops import LogEntry
            entry = LogEntry(
                level=level,
                source="server",
                message=f"{request.method} {request.path} → {response.status_code}",
                request_id=g.get("request_id"),
                user_id=user_id,
                endpoint=request.endpoint or request.path,
                method=request.method,
                status_code=response.status_code,
                latency_ms=elapsed_ms,
            )
            db.session.add(entry)
            db.session.commit()
        except Exception as exc:
            logger.warning("Middleware: failed to write LogEntry: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass

        return response

    # ── Client-side error ingestion ───────────────────────────────────────────

    @app.route("/analytics/client-error", methods=["POST"])
    def _client_error():
        """Accept a client-side JS error and persist it as a LogEntry."""
        try:
            from flask_login import current_user
            user_id = current_user.id if current_user.is_authenticated else None
        except Exception:
            user_id = None

        message = (request.form.get("message") or "").strip()[:2000] or "Unknown client error"
        page = (request.form.get("page") or request.form.get("url") or "").strip()[:500]
        stack = (request.form.get("stack") or "").strip()[:2000]
        full_msg = message + (f"\n{stack}" if stack else "")

        try:
            from app.models.ops import LogEntry
            entry = LogEntry(
                level="ERROR",
                source="client",
                message=full_msg[:2000],
                request_id=g.get("request_id"),
                user_id=user_id,
                endpoint=page or None,
                method="CLIENT",
                status_code=None,
                latency_ms=None,
            )
            db.session.add(entry)
            db.session.commit()
        except Exception as exc:
            logger.warning("client-error endpoint: failed to store: %s", exc)
            db.session.rollback()

        return "", 204
