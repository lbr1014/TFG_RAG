"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integracion de decoradores de autorizacion. Su objetivo es verificar el comportamiento del decorador 
admin_required, encargado de restringir el acceso a determinadas rutas únicamente a usuarios con privilegios de administrador.
Las pruebas validan los distintos escenarios de acceso posibles, incluyendo usuarios anónimos, usuarios autenticados sin permisos 
administrativos y administradores autorizados.
"""

from app.main.code.decorators import admin_required
from app.test.support import BaseAppTestCase


class DecoratorsIntegrationTest(BaseAppTestCase):
    def setUp(self):
        """
        Inicializa el entorno de pruebas y registra una ruta protegida mediante el decorador admin_required, que será utilizada 
        para verificar los distintos escenarios de autorización.
        """
        super().setUp()

        @self.app.get("/test-decorators/admin-only")
        @admin_required
        def admin_only_route():
            """
            Endpoint de prueba protegido por el decorador `admin_required` utilizado para verificar los mecanismos de control de acceso basados
            en privilegios de administrador.
            """
            return "admin ok"

    def test_admin_required_redirects_anonymous_user_to_login(self):
        """
        Verifica que un usuario no autenticado es redirigido automáticamente a la página de inicio de sesión cuando
        intenta acceder a una ruta protegida para administradores.
        """
        response = self.client.get("/test-decorators/admin-only", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_admin_required_aborts_for_authenticated_non_admin_user(self):
        """
        Comprueba que un usuario autenticado sin privilegios de administrador recibe una respuesta de acceso denegado al intentar acceder 
        a una ruta protegida.        
        """
        user = self.create_user(email="normal@example.com", is_admin=False)
        self.login(user.email)

        response = self.client.get(
            "/test-decorators/admin-only",
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["status"], 403)

    def test_admin_required_allows_authenticated_admin_user(self):
        """
        Verifica que un usuario autenticado con permisos de administrador puede acceder correctamente a una ruta protegida por el decorador.
        """
        admin = self.create_user(email="admin-decorator@example.com", is_admin=True)
        self.login(admin.email)

        response = self.client.get("/test-decorators/admin-only")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"admin ok")
