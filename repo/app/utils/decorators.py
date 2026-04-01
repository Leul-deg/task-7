from functools import wraps
from flask import abort, request, jsonify, render_template, make_response, url_for
from flask_login import current_user


def login_required(f):
    """Redirect to login (or return 401 fragment for HTMX) if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.headers.get("HX-Request"):
                resp = make_response(
                    render_template("partials/error_fragment.html",
                                    code=401, message="You must be logged in."),
                    401,
                )
                resp.headers["HX-Redirect"] = url_for("auth.login")
                return resp
            abort(401)
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    """Restrict a view to users with one of the given roles.

    Returns an HTMX-swappable 403 fragment when the request has HX-Request header,
    otherwise aborts with 403.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.headers.get("HX-Request"):
                    resp = make_response(
                        render_template("partials/error_fragment.html",
                                        code=401, message="You must be logged in."),
                        401,
                    )
                    resp.headers["HX-Redirect"] = url_for("auth.login")
                    return resp
                abort(401)
            if current_user.role not in roles:
                if request.headers.get("HX-Request"):
                    return render_template(
                        "partials/error_fragment.html",
                        code=403,
                        message="You do not have permission to perform this action.",
                    ), 403
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def htmx_required(f):
    """Return 400 if the request is not an HTMX request."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not request.headers.get("HX-Request"):
            if request.accept_mimetypes.accept_json:
                return jsonify(error="HTMX request required"), 400
            abort(400)
        return f(*args, **kwargs)
    return decorated
