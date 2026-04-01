import traceback
from flask import current_app, request, jsonify, render_template


def _is_htmx() -> bool:
    return bool(request.headers.get("HX-Request"))


def _wants_json() -> bool:
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json"


def register_error_handlers(app):
    @app.errorhandler(400)
    def bad_request(e):
        if _wants_json():
            return jsonify(error="Bad request", detail=str(e)), 400
        if _is_htmx():
            return render_template("partials/error_fragment.html",
                                   code=400, message="Bad request."), 400
        return render_template("errors/400.html", error=e), 400

    @app.errorhandler(401)
    def unauthorized(e):
        if _wants_json():
            return jsonify(error="Unauthorized"), 401
        if _is_htmx():
            return render_template("partials/error_fragment.html",
                                   code=401, message="You must be logged in."), 401
        return render_template("errors/401.html", error=e), 401

    @app.errorhandler(403)
    def forbidden(e):
        if _wants_json():
            return jsonify(error="Forbidden"), 403
        if _is_htmx():
            return render_template("partials/error_fragment.html",
                                   code=403, message="You do not have permission."), 403
        return render_template("errors/403.html", error=e), 403

    @app.errorhandler(404)
    def not_found(e):
        if _wants_json():
            return jsonify(error="Not found"), 404
        if _is_htmx():
            return render_template("partials/error_fragment.html",
                                   code=404, message="Resource not found."), 404
        return render_template("errors/404.html", error=e), 404

    @app.errorhandler(500)
    def server_error(e):
        current_app.logger.error(
            "500 Internal Server Error: %s\n%s",
            str(e),
            traceback.format_exc(),
        )
        if _wants_json():
            return jsonify(error="Internal server error"), 500
        if _is_htmx():
            return render_template("partials/error_fragment.html",
                                   code=500, message="An unexpected error occurred."), 500
        return render_template("errors/500.html", error=e), 500
