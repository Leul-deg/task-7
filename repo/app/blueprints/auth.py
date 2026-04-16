from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, make_response,
)
from flask_login import login_user, logout_user, current_user
from ..services.auth_service import authenticate, register_user, change_password
from ..utils.validators import validate_registration
from ..utils.decorators import login_required

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("booking.schedule"))

    errors = {}
    form_data = {}

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))
        form_data = {"identifier": identifier}

        if not identifier:
            errors["identifier"] = "Username or email is required."
        if not password:
            errors["password"] = "Password is required."

        if not errors:
            user, error = authenticate(identifier, password)
            if user:
                login_user(user, remember=remember)
                next_url = request.args.get("next") or url_for("booking.schedule")
                # Prevent open redirect — only allow relative paths
                if not next_url.startswith("/"):
                    next_url = url_for("booking.schedule")

                if request.headers.get("HX-Request"):
                    response = make_response()
                    response.headers["HX-Redirect"] = next_url
                    return response, 200

                return redirect(next_url)
            else:
                errors["general"] = error

        if request.headers.get("HX-Request"):
            return render_template(
                "auth/_login_form.html",
                errors=errors,
                form_data=form_data,
            ), 422

    return render_template("auth/login.html", errors=errors, form_data=form_data)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    if request.headers.get("HX-Request"):
        response = make_response()
        response.headers["HX-Redirect"] = url_for("auth.login")
        return response, 200
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("booking.schedule"))

    errors = {}
    form_data = {}

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        form_data = {"username": username, "email": email}

        errors = validate_registration(username, email, password, confirm)

        if not errors:
            user, error = register_user(username, email, password, role="customer")
            if user:
                login_user(user)
                flash(f"Welcome, {user.username}! Your account has been created.", "success")

                if request.headers.get("HX-Request"):
                    response = make_response()
                    response.headers["HX-Redirect"] = url_for("booking.schedule")
                    return response, 200

                return redirect(url_for("booking.schedule"))
            else:
                if "username" in error.lower():
                    errors["username"] = error
                elif "email" in error.lower():
                    errors["email"] = error
                else:
                    errors["general"] = error

        if request.headers.get("HX-Request"):
            return render_template(
                "auth/_register_form.html",
                errors=errors,
                form_data=form_data,
            ), 422

    return render_template("auth/register.html", errors=errors, form_data=form_data)


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password_view():
    """GET/POST /auth/change-password — authenticated user changes their own password."""
    errors = {}

    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")

        if not current_pw:
            errors["current_password"] = "Current password is required."
        if not new_pw:
            errors["new_password"] = "New password is required."
        elif len(new_pw) < 10:
            errors["new_password"] = "New password must be at least 10 characters."
        elif new_pw != confirm_pw:
            errors["confirm_password"] = "Passwords do not match."

        if not errors:
            result = change_password(current_user.id, current_pw, new_pw)
            if result["success"]:
                flash(result["message"], "success")
                if request.headers.get("HX-Request"):
                    response = make_response()
                    response.headers["HX-Redirect"] = url_for("booking.schedule")
                    return response, 200
                return redirect(url_for("booking.schedule"))
            else:
                errors["current_password"] = result["reason"]

        if request.headers.get("HX-Request"):
            return render_template("auth/change_password.html", errors=errors), 422

    return render_template("auth/change_password.html", errors=errors)
