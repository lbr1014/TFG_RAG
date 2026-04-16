"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integración de las rutas de la aplicación.
"""

from unittest.mock import MagicMock, patch

from tests.support import BaseAppTestCase

from app.entities.consulta import Consulta
from app.extensions import db


class MainRoutesIntegrationTest(BaseAppTestCase):
    def test_inicio_renders_public_home(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"PythIA", response.data)

    @patch("app.main.routes.qdrant_get_payloads", return_value={})
    def test_pagina_principal_renders_authenticated_dashboard(self, _mock_qdrant):
        user = self.create_user(email="dashboard@example.com")
        self.create_consulta(user)
        self.login(user.email)

        response = self.client.get("/pagina_principal")

        self.assertEqual(response.status_code, 200)

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

    def test_edit_user_rejects_duplicate_email(self):
        self.create_user(email="existing@example.com")
        user = self.create_user(email="edit-duplicate@example.com")
        self.login(user.email)

        response = self.client.post(
            "/edit_user",
            data={"nombre": "Duplicado", "email": "existing@example.com", "new_password": ""},
        )

        self.assertEqual(response.status_code, 200)
        db.session.refresh(user)
        self.assertEqual(user.email, "edit-duplicate@example.com")

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

    def test_stats_renders_regular_user_scope(self):
        user = self.create_user(email="stats-regular@example.com")
        self.create_consulta(user)
        self.login(user.email)

        response = self.client.get("/stats")

        self.assertEqual(response.status_code, 200)

    def test_stats_admin_global_selected_user_and_missing_user(self):
        admin = self.create_user(email="stats-admin@example.com", is_admin=True)
        selected = self.create_user(nombre="Usuario Stats", email="stats-selected@example.com")
        self.create_consulta(admin)
        self.create_consulta(selected)
        self.login(admin.email)

        global_response = self.client.get("/stats")
        selected_response = self.client.get(f"/stats?user_id={selected.id}")
        missing_response = self.client.get("/stats?user_id=999999")

        self.assertEqual(global_response.status_code, 200)
        self.assertEqual(selected_response.status_code, 200)
        self.assertEqual(missing_response.status_code, 404)

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

    @patch("app.main.routes.EmptyForm")
    def test_delete_consulta_rejects_invalid_form(self, mock_empty_form):
        form = MagicMock()
        form.validate_on_submit.return_value = False
        mock_empty_form.return_value = form
        user = self.create_user(email="delete-invalid@example.com")
        consulta = self.create_consulta(user)
        self.login(user.email)

        response = self.client.post(f"/consulta/{consulta.id}/delete")

        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(db.session.get(Consulta, consulta.id))
