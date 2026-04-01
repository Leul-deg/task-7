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
    from flask import redirect, url_for, jsonify
    from flask_login import current_user

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("booking.schedule"))
        return redirect(url_for("auth.login"))

    # Health endpoint
    @app.route("/health")
    def health():
        from datetime import datetime as _now
        try:
            db.session.execute(db.text("SELECT 1"))
            db_status = "connected"
        except Exception as exc:
            db_status = f"error: {exc}"
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
