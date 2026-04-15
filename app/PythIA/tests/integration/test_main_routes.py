"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integración de las rutas de la aplicación.
"""

from unittest.mock import patch

from tests.support import BaseAppTestCase

from app.entities.consulta import Consulta
from app.extensions import db


class MainRoutesIntegrationTest(BaseAppTestCase):
    def test_edit_user_updates_profile(self):
        user = self.create_user(email="edit@example.com")
        self.login("edit@example.com")

        response = self.client.post(
            "/edit_user",
            data={
                "nombre": "Nombre Nuevo",
                "email": "nuevo@example.com",
                "new_password": "Nueva123",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        db.session.refresh(user)
        self.assertEqual(user.nombre, "Nombre Nuevo")
        self.assertEqual(user.email, "nuevo@example.com")
        self.assertTrue(user.check_password("Nueva123"))

    @patch("app.main.routes.qdrant_get_payloads")
    def test_history_uses_saved_fragmentos_without_calling_qdrant(self, mock_qdrant):
        user = self.create_user(email="history@example.com")
        self.login("history@example.com")
        self.create_consulta(
            user,
            fragmentos=[
                {
                    "ranking": 1,
                    "qdrant_point_id": "saved-qid",
                    "metadata": {"filename": "saved.pdf"},
                    "chunk": "texto guardado",
                }
            ],
        )

        response = self.client.get("/history?page=1")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"saved.pdf", response.data)
        mock_qdrant.assert_not_called()

    def test_delete_consulta_only_allows_owner(self):
        owner = self.create_user(email="owner@example.com")
        other = self.create_user(email="other@example.com")
        consulta = self.create_consulta(owner)

        self.login(other.email)
        forbidden = self.client.post(f"/consulta/{consulta.id}/delete")
        self.assertEqual(forbidden.status_code, 403)

        self.login(owner.email)
        allowed = self.client.post(f"/consulta/{consulta.id}/delete", follow_redirects=False)
        self.assertEqual(allowed.status_code, 302)
        self.assertIsNone(db.session.get(Consulta, consulta.id))
