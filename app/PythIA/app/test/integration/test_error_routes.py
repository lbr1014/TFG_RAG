"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integracion de las rutas de error de la aplicacion.
"""

from flask import abort
from unittest.mock import patch

from tests.support import BaseAppTestCase


class ErrorRoutesIntegrationTest(BaseAppTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["PROPAGATE_EXCEPTIONS"] = False

    def _assert_json_error(self, response, expected_status):
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(response.content_type, "application/json")

        payload = response.get_json()
        self.assertEqual(payload["status"], expected_status)
        self.assertIn("title", payload)
        self.assertIn("error", payload)

    def test_bad_request_error_route_returns_json_payload(self):
        @self.app.get("/test-errors/bad-request")
        def bad_request_route():
            abort(400)

        response = self.client.get(
            "/test-errors/bad-request",
            headers={"Accept": "application/json"},
        )

        self._assert_json_error(response, 400)

    def test_forbidden_error_route_returns_json_payload(self):
        @self.app.get("/test-errors/forbidden")
        def forbidden_route():
            abort(403)

        response = self.client.get(
            "/test-errors/forbidden",
            headers={"Accept": "application/json"},
        )

        self._assert_json_error(response, 403)

    def test_not_found_error_route_returns_json_payload(self):
        response = self.client.get(
            "/test-errors/not-found",
            headers={"Accept": "application/json"},
        )

        self._assert_json_error(response, 404)

    def test_server_error_route_returns_json_payload(self):
        @self.app.get("/test-errors/server-error")
        def server_error_route():
            raise RuntimeError("boom")

        with patch.object(self.app.logger, "error"):
            response = self.client.get(
                "/test-errors/server-error",
                headers={"Accept": "application/json"},
            )

        self._assert_json_error(response, 500)
