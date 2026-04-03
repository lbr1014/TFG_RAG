from __future__ import annotations

import re

from flask import jsonify, render_template, request
from wtforms.validators import ValidationError

from .inetrnacionalizacion.tarduccion import t


class PasswordSecurity:
    def __init__(self, *, require_upper: bool = True, require_lower: bool = True, require_digit: bool = True, message: str | None = None):
        self.require_upper = require_upper
        self.require_lower = require_lower
        self.require_digit = require_digit
        self.message = message

    def __call__(self, form, field):
        value = (field.data or "").strip()
        if not value:
            return

        has_upper = bool(re.search(r"[A-Z]", value))
        has_lower = bool(re.search(r"[a-z]", value))
        has_digit = bool(re.search(r"\d", value))

        if (
            (self.require_upper and not has_upper)
            or (self.require_lower and not has_lower)
            or (self.require_digit and not has_digit)
        ):
            raise ValidationError(self.message or t("validation.password_security"))


def collect_form_errors(form) -> list[dict[str, str]]:
    if not form:
        return []

    errors: list[dict[str, str]] = []
    for field in form:
        if getattr(field, "type", "") == "CSRFTokenField":
            continue
        for message in getattr(field, "errors", []):
            errors.append(
                {
                    "field": getattr(getattr(field, "label", None), "text", field.name),
                    "message": message,
                }
            )
    return errors


def wants_json_response() -> bool:
    if request.path.startswith("/rag/"):
        return True
    if request.is_json:
        return True
    return request.accept_mimetypes.best == "application/json"


def render_error_response(status_code: int, title_key: str, message_key: str):
    payload = {
        "error": t(message_key),
        "title": t(title_key),
        "status": status_code,
    }

    if wants_json_response():
        return jsonify(payload), status_code

    return (
        render_template(
            "error.html",
            error_status=status_code,
            error_title=t(title_key),
            error_message=t(message_key),
        ),
        status_code,
    )


def register_error_handlers(app) -> None:
    @app.context_processor
    def _inject_form_error_helpers():
        return {
            "collect_form_errors": collect_form_errors,
        }

    @app.errorhandler(400)
    def _handle_bad_request(error):
        return render_error_response(400, "errors.bad_request_title", "errors.bad_request_message")

    @app.errorhandler(403)
    def _handle_forbidden(error):
        return render_error_response(403, "errors.forbidden_title", "errors.forbidden_message")

    @app.errorhandler(404)
    def _handle_not_found(error):
        return render_error_response(404, "errors.not_found_title", "errors.not_found_message")

    @app.errorhandler(500)
    def _handle_server_error(error):
        return render_error_response(500, "errors.server_title", "errors.server_message")
