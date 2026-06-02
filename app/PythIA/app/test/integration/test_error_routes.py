"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integracion de las rutas de error de la aplicacion. Su objetivo es verificar que las excepciones HTTP y los errores 
internos son gestionados correctamente por los controladores de errores, devolviendo respuestas JSON estructuradas cuando el cliente las solicita. 
Las pruebas cubren errores de solicitud incorrecta, acceso prohibido, recursos inexistentes y errores internos del servidor, 
garantizando la consistencia del formato de respuesta utilizado por la API.
"""

from unittest.mock import patch

from flask import abort

from app.test.support import BaseAppTestCase


class ErrorRoutesIntegrationTest(BaseAppTestCase):
    def setUp(self):
        """
        Inicializa el entorno de pruebas configurando la aplicación para que las excepciones sean gestionadas por los manejadores 
        de errores registrados en lugar de propagarse directamente durante la ejecución de las pruebas.
        """
        super().setUp()
        self.app.config["PROPAGATE_EXCEPTIONS"] = False

    def _assert_json_error(self, response, expected_status):
        """
        Función auxiliar que verifica que una respuesta de error contiene el código HTTP esperado y sigue el formato JSON estándar
        definido por la aplicación.
        """
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(response.content_type, "application/json")

        payload = response.get_json()
        self.assertEqual(payload["status"], expected_status)
        self.assertIn("title", payload)
        self.assertIn("error", payload)

    def test_bad_request_error_route_returns_json_payload(self):
        """
        Verifica que los errores de tipo Bad Request (HTTP 400) generan una respuesta JSON con la estructura esperada.
        """
        @self.app.get("/test-errors/bad-request")
        def bad_request_route():
            """
            Endpoint de prueba que provoca un error HTTP 400 para validar el comportamiento del manejador de errores correspondiente.
            """
            abort(400)

        response = self.client.get(
            "/test-errors/bad-request",
            headers={"Accept": "application/json"},
        )

        self._assert_json_error(response, 400)

    def test_forbidden_error_route_returns_json_payload(self):
        """
        Comprueba que los errores de acceso prohibido (HTTP 403) son transformados correctamente en respuestas JSON normalizadas.
        """
        @self.app.get("/test-errors/forbidden")
        def forbidden_route():
            """
            Endpoint de prueba que provoca un error HTTP 403 para verificar el tratamiento de errores de autorización.
            """
            abort(403)

        response = self.client.get(
            "/test-errors/forbidden",
            headers={"Accept": "application/json"},
        )

        self._assert_json_error(response, 403)

    def test_not_found_error_route_returns_json_payload(self):
        """
        Verifica que las rutas inexistentes generan respuestas Not Found (HTTP 404) con el formato JSON definido por la aplicación.
        """
        response = self.client.get(
            "/test-errors/not-found",
            headers={"Accept": "application/json"},
        )

        self._assert_json_error(response, 404)

    def test_server_error_route_returns_json_payload(self):
        """
        Comprueba que las excepciones internas no controladas producen respuestas Internal Server Error (HTTP 500) correctamente estructuradas en formato JSON.
        """
        @self.app.get("/test-errors/server-error")
        def server_error_route():
            """
        Endpoint de prueba que genera una excepción no controlada para validar el comportamiento del manejador global de errores.
        """
            raise RuntimeError("boom")

        with patch.object(self.app.logger, "error"):
            response = self.client.get(
                "/test-errors/server-error",
                headers={"Accept": "application/json"},
            )

        self._assert_json_error(response, 500)
