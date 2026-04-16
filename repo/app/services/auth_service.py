from datetime import datetime, timedelta
from typing import Optional, Tuple
from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app, request
from ..extensions import db
from ..models.user import User, LoginAttempt


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def is_locked_out(user: User) -> bool:
    if user.locked_until and user.locked_until > datetime.utcnow():
        return True
    return False


def record_attempt(user: User, success: bool, ip: str = None) -> None:
    attempt = LoginAttempt(
        user_id=user.id,
        ip_address=ip or _get_client_ip(),
        success=success,
    )
    db.session.add(attempt)

    if success:
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login = datetime.utcnow()
    else:
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        max_attempts = current_app.config.get("MAX_LOGIN_ATTEMPTS", 5)
        if user.failed_login_attempts >= max_attempts:
            lockout_minutes = current_app.config.get("LOCKOUT_MINUTES", 15)
            user.locked_until = datetime.utcnow() + timedelta(minutes=lockout_minutes)

    db.session.commit()


def authenticate(username_or_email: str, password: str) -> Tuple[Optional[User], str]:
    """
    Returns (user, error_message). user is None on failure.
    """
    user = (
        User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email)
        ).first()
    )

    if user is None:
        return None, "Invalid credentials."

    if not user.is_active:
        return None, "This account has been deactivated."

    if is_locked_out(user):
        minutes_left = int((user.locked_until - datetime.utcnow()).total_seconds() / 60) + 1
        return None, f"Account is locked. Try again in {minutes_left} minute(s)."

    if not verify_password(password, user.password_hash):
        record_attempt(user, success=False)
        remaining = max(
            0,
            current_app.config.get("MAX_LOGIN_ATTEMPTS", 5) - user.failed_login_attempts,
        )
        if remaining == 0:
            return None, "Too many failed attempts. Account is now locked."
        return None, f"Invalid credentials. {remaining} attempt(s) remaining."

    record_attempt(user, success=True)
    return user, ""


def register_user(username: str, email: str, password: str, role: str = "customer") -> Tuple[Optional[User], str]:
    """
    Creates a new user. Returns (user, error_message).
    """
    if role not in User.VALID_ROLES:
        return None, f"Invalid role '{role}'."

    if User.query.filter_by(username=username).first():
        return None, "Username already taken."

    if User.query.filter_by(email=email).first():
        return None, "Email already registered."

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role,
    )
    db.session.add(user)
    db.session.commit()
    return user, ""


def change_password(user_id: int, current_password: str, new_password: str) -> dict:
    """
    Change a user's password after verifying the current password.

    Returns
    -------
    dict
        ``{"success": True, "message": str}``
        ``{"success": False, "reason": str}``
    """
    user = User.query.get(user_id)
    if user is None:
        return {"success": False, "reason": "User not found."}
    if not verify_password(current_password, user.password_hash):
        return {"success": False, "reason": "Current password is incorrect."}
    user.password_hash = hash_password(new_password)
    db.session.commit()
    return {"success": True, "message": "Password updated successfully."}


def _get_client_ip() -> str:
    try:
        return request.remote_addr or "unknown"
    except RuntimeError:
        return "unknown"
