import re

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,80}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN_LENGTH = 10


def validate_username(username: str) -> str:
    """Returns an error string, or empty string on success."""
    if not username:
        return "Username is required."
    if not USERNAME_RE.match(username):
        return "Username must be 3–80 characters: letters, numbers, underscores only."
    return ""


def validate_email(email: str) -> str:
    if not email:
        return "Email is required."
    if not EMAIL_RE.match(email):
        return "Invalid email address."
    return ""


def validate_password(password: str) -> str:
    if not password:
        return "Password is required."
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if not any(c.isupper() for c in password):
        return "Password must contain at least one uppercase letter."
    if not any(c.isdigit() for c in password):
        return "Password must contain at least one digit."
    return ""


def validate_registration(username: str, email: str, password: str, confirm: str) -> dict:
    """Returns a dict of field -> error_message. Empty dict means all valid."""
    errors = {}
    u_err = validate_username(username)
    if u_err:
        errors["username"] = u_err
    e_err = validate_email(email)
    if e_err:
        errors["email"] = e_err
    p_err = validate_password(password)
    if p_err:
        errors["password"] = p_err
    if not p_err and password != confirm:
        errors["confirm"] = "Passwords do not match."
    return errors
