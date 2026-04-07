import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, session
from .config import config
from .extensions import db, login_manager, csrf, migrate


def _setup_logging(app: Flask) -> None:
    """Configure Python logging: console + rotating file handler."""
    log_dir = app.config.get("LOG_DIR", os.path.join(app.root_path, "..", "logs"))
    os.makedirs(log_dir, exist_ok=True)
    log_file = app.config.get("LOG_FILE", os.path.join(log_dir, "app.log"))

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)
    console_handler.setFormatter(formatter)

    # Rotating file handler (10 MB, keep 5 backups)
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    app.logger.addHandler(console_handler)
    app.logger.addHandler(file_handler)

    # Also attach to root logger so SQLAlchemy / Werkzeug messages flow through
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)


def _seed_admin(app: Flask) -> None:
    """Create the default admin account on first run if it doesn't exist."""
    from .models.user import User
    from .services.auth_service import hash_password

    with app.app_context():
        if not User.query.filter_by(username="admin").first():
            admin = User(
                username="admin",
                email="admin@studioops.local",
                password_hash=hash_password("Admin12345!"),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()
            app.logger.info("Default admin account created (username=admin).")


def create_app(config_name: str = None) -> Flask:
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "default")

    app = Flask(__name__, template_folder="templates", static_folder="static")
    cfg = config[config_name]
    if hasattr(cfg, "_validate"):
        cfg._validate()
    app.config.from_object(cfg)

    # Ensure runtime directories exist
    for folder in [
        app.config["UPLOAD_FOLDER"],
        os.path.join(app.root_path, "..", "backups"),
        os.path.join(app.root_path, "..", "logs"),
    ]:
        os.makedirs(folder, exist_ok=True)

    # Logging
    _setup_logging(app)

    # Extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    # Models (needed for migrate to discover them)
    from .models import user, studio, content, review, analytics, ops  # noqa: F401

    # User loader for Flask-Login
    from .models.user import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    # Refresh session on every request (sliding 8-hour window)
    @app.before_request
    def refresh_session():
        session.permanent = True

    # Blueprints
    from .blueprints.auth import auth_bp
    from .blueprints.booking import booking_bp
    from .blueprints.staff import staff_bp
    from .blueprints.content import content_bp
    from .blueprints.reviews import reviews_bp
    from .blueprints.analytics import analytics_bp
    from .blueprints.admin import admin_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    # booking_bp carries explicit paths (/schedule, /booking/*) so no prefix
    app.register_blueprint(booking_bp)
    app.register_blueprint(staff_bp, url_prefix="/staff")
    app.register_blueprint(content_bp, url_prefix="/content")
    app.register_blueprint(reviews_bp, url_prefix="/reviews")
    app.register_blueprint(analytics_bp, url_prefix="/analytics")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # Request logging middleware
    from .utils.middleware import register_middleware
    register_middleware(app)

    # CSRF exempt for client-error endpoint (fire-and-forget telemetry only)
    if "_client_error" in app.view_functions:
        csrf.exempt(app.view_functions["_client_error"])

    # Error handlers
    from .utils.errors import register_error_handlers
    register_error_handlers(app)

    # Jinja globals and filters
    from datetime import datetime as _dt
    import json as _json
    app.jinja_env.globals["now"] = _dt.utcnow
    app.jinja_env.filters["from_json"] = _json.loads
    # Date/time formatting — always MM/DD/YYYY, 12-hour clock
    app.jinja_env.filters["dt"]    = lambda d, fmt="%m/%d/%Y": d.strftime(fmt) if d else "—"
    app.jinja_env.filters["dtime"] = lambda d: d.strftime("%m/%d/%Y %I:%M %p") if d else "—"

    # Feature flag Jinja global
    from .services.feature_flag_service import register_jinja_global as _reg_ff
    _reg_ff(app)

    # Root redirect
    from flask import abort, jsonify, redirect, send_file, url_for
    from flask_login import current_user

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("booking.schedule"))
        return redirect(url_for("auth.login"))

    @app.route("/media/<path:storage_path>")
    def media_file(storage_path: str):
        # Serve uploaded files through an authenticated route.
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))

        from .services.file_service import resolve_upload_path
        from .models.content import Content, ContentAttachment
        from .models.review import ReviewImage

        abs_path = resolve_upload_path(storage_path)
        upload_root = os.path.abspath(app.config["UPLOAD_FOLDER"])

        # Accept legacy absolute paths only if they still resolve under upload root.
        try:
            common = os.path.commonpath([os.path.abspath(abs_path), upload_root])
        except ValueError:
            common = ""
        if common != upload_root or not os.path.isfile(abs_path):
            abort(404)

        # Normalize to a relative storage path for object-level checks.
        normalized_path = os.path.relpath(abs_path, upload_root).replace("\\", "/")

        def _is_content_allowed() -> bool:
            content = (
                Content.query.filter_by(cover_path=normalized_path).first()
                or Content.query.filter_by(cover_path=abs_path).first()
            )
            if content:
                return (
                    current_user.role == "admin"
                    or content.author_id == current_user.id
                    or content.status == "published"
                )

            attachment = (
                ContentAttachment.query.filter_by(file_path=normalized_path).first()
                or ContentAttachment.query.filter_by(file_path=abs_path).first()
            )
            if not attachment:
                return False

            content = attachment.content
            return (
                current_user.role == "admin"
                or (content and content.author_id == current_user.id)
                or (content and content.status == "published")
            )

        def _is_review_allowed() -> bool:
            image = (
                ReviewImage.query.filter_by(file_path=normalized_path).first()
                or ReviewImage.query.filter_by(file_path=abs_path).first()
            )
            if not image:
                return False

            review = image.review
            if not review or not review.reservation or not review.reservation.session:
                return False

            reservation = review.reservation
            instructor_id = reservation.session.instructor_id
            return (
                current_user.role == "admin"
                or current_user.id == review.user_id
                or current_user.id == reservation.user_id
                or current_user.id == instructor_id
            )

        if not (_is_content_allowed() or _is_review_allowed()):
            abort(403)

        return send_file(abs_path)

    # Health endpoint
    @app.route("/health")
    def health():
        from datetime import datetime as _now
        try:
            db.session.execute(db.text("SELECT 1"))
            db_status = "connected"
        except Exception as exc:
            app.logger.error("Health check DB failure: %s", exc)
            db_status = "error"
        status = "healthy" if db_status == "connected" else "unhealthy"
        return jsonify({
            "status": status,
            "timestamp": _now.utcnow().isoformat(),
            "database": db_status,
        }), 200 if status == "healthy" else 503

    # CLI commands
    from .cli import register_seed_cli as _register_seed_cli
    _register_seed_cli(app)

    from .services.credit_service import register_cli as _register_credit_cli
    _register_credit_cli(app)

    from .services.data_retention_service import register_cleanup_cli as _register_cleanup_cli
    _register_cleanup_cli(app)

    from .services.backup_service import register_backup_cli as _register_backup_cli
    _register_backup_cli(app)

    return app
