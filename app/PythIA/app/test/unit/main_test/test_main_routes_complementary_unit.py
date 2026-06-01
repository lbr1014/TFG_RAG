"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias complementarias para las rutas pricipales de la aplicaicón. Su objetivo es verificar ramas de ejecución menos frecuentes
relacionadas con el historial de consultas, la generación de estadísticas de uso, la construcción de métricas para la interfaz de usuario, 
la gestión de perfiles y la actualización de datos de usuario. Las pruebas validan el correcto funcionamiento de filtros, cálculos estadísticos, 
mecanismos de visualización y operaciones auxiliares utilizadas por las vistas principales de la aplicación.
"""

import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask_login import login_user

from app.main.code.controllers.main import routes as main_routes
from app.main.code.extensions import db
from app.main.code.model.consulta import Consulta
from app.main.code.model.rag_query_state import RAGQueryState
from app.main.code.model.user import User
from app.test.support import BaseAppTestCase


class MainRoutesAdditionalCoverageUnitTest(BaseAppTestCase):
    def test_apply_history_filters_date_device_model_and_invalid_date(self):
        """
        Verifica la aplicación de filtros sobre el historial de consultas utilizando fecha, dispositivo de ejecución y modelo empleado, 
        incluyendo el tratamiento de fechas inválidas.
        """
        admin = self.create_user(email="hist-admin@example.com", is_admin=True)
        user = self.create_user(email="hist-user@example.com")
        consulta = self.create_consulta(user)

        job = RAGQueryState(
            user_id=user.id,
            question=consulta.pregunta,
            status="done",
            model_name="m1",
        )
        db.session.add(job)
        db.session.commit()

        with self.app.test_request_context("/history"), patch.object(main_routes, "current_user", admin):
            base = Consulta.query
            filtered = main_routes._apply_history_filters(
                base,
                {
                    "user_id": str(user.id),
                    "date": "not-a-date",
                    "model": "",
                    "device": "",
                },
            )
            self.assertEqual(filtered.count(), 1)

            consulta.created_at = datetime(2026, 5, 31, 9, 0, tzinfo=timezone.utc)
            db.session.commit()
            filtered2 = main_routes._apply_history_filters(
                base,
                {
                    "user_id": str(user.id),
                    "date": date(2026, 5, 31).isoformat(),
                    "model": "",
                    "device": "",
                },
            )
            self.assertEqual(filtered2.count(), 1)

            consulta.execution_device = "gpu"
            db.session.commit()
            filtered3 = main_routes._apply_history_filters(
                base,
                {
                    "user_id": str(user.id),
                    "date": "",
                    "model": "",
                    "device": "GPU",
                },
            )
            self.assertEqual(filtered3.count(), 1)

            filtered4 = main_routes._apply_history_filters(
                base,
                {
                    "user_id": str(user.id),
                    "date": "",
                    "model": "m1",
                    "device": "",
                },
            )
            self.assertEqual(filtered4.count(), 1)

    def test_build_model_by_consulta(self):
        """
        Comprueba la construcción del mapa de modelos asociados a consultas cuando existen múltiples ejecuciones relacionadas con la misma pregunta.
        """
        user = self.create_user(email="model-by@example.com")
        consulta = self.create_consulta(user)
        j1 = RAGQueryState(user_id=user.id, question=consulta.pregunta, status="done", model_name="m1")
        j2 = RAGQueryState(user_id=user.id, question=consulta.pregunta, status="done", model_name="m2")
        db.session.add_all([j1, j2])
        db.session.commit()

        mapping = main_routes.build_model_by_consulta([consulta])
        self.assertIn(consulta.id, mapping)
        self.assertIn(mapping[consulta.id], {"m1", "m2"})

    def test_build_model_by_consulta_empty(self):
        """
        Verifica que la construcción del mapa de modelos devuelve una estructura vacía cuando no existen consultas para procesar.
        """
        self.assertEqual(main_routes.build_model_by_consulta([]), {})

    def test_build_activity_streak_returns_zero_when_no_days(self):
        """
        Comprueba que el cálculo de rachas de actividad devuelve correctamente cero cuando no existen días con actividad registrada.
        """
        user = self.create_user(email="streak-empty@example.com")
        self.assertEqual(main_routes.build_activity_streak(user, []), 0)

    def test_build_home_query_donut_admin_and_global_segments(self):
        """
        Verifica la generación de los datos utilizados por el gráfico de consultas de la página principal tanto para administradores 
        como para usuarios normales.
        """
        admin = self.create_user(email="donut-admin@example.com", is_admin=True)
        u1 = self.create_user(nombre="A", email="donut-a@example.com")
        u2 = self.create_user(nombre="B", email="donut-b@example.com")
        self.create_consulta(u1)
        self.create_consulta(u2)
        with self.app.test_request_context("/"
        ), patch("app.main.code.controllers.main.routes.t", side_effect=lambda key, **_k: key):
            donut = main_routes.build_home_query_donut(admin, user_total_queries=0)
        self.assertEqual(donut["title"], "home.donut_admin_title")
        self.assertGreaterEqual(donut["total"], 2)

        user = self.create_user(email="donut-user@example.com", is_admin=False)
        with self.app.test_request_context("/"
        ), patch("app.main.code.controllers.main.routes.t", side_effect=lambda key, **_k: key):
            donut2 = main_routes.build_home_query_donut(user, user_total_queries=1)
        self.assertTrue(
            any(seg["label"] == "home.donut_global_segment" for seg in donut2["segments"])
        )

    def test_build_usage_query_non_admin_global_scope_branch(self):
        """
        Comprueba la construcción de consultas estadísticas para usuarios no administradores cuando se solicita información de ámbito global.
        """
        user = self.create_user(email="usage-nonadmin@example.com", is_admin=False)
        other = self.create_user(email="usage-other@example.com", is_admin=False)
        self.create_consulta(user)
        self.create_consulta(other)

        with self.app.test_request_context("/stats"):
            login_user(user)
            query = main_routes._build_usage_query(None, "global")
        self.assertGreaterEqual(query.count(), 1)

    def test_profile_image_helpers_url_and_delete_existing(self):
        """
        Verifica la generación de URLs de imágenes de perfil y la eliminación correcta de imágenes almacenadas en el sistema de archivos.
        """
        user = SimpleNamespace(profile_image="profiles/../avatar.png")
        with self.app.test_request_context("/"):
            self.assertIn("/profile_image/", main_routes._profile_image_url(user))

        with tempfile.TemporaryDirectory() as tmpdir:
            upload_dir = Path(tmpdir)
            self.app.config["PROFILE_UPLOAD_FOLDER"] = upload_dir
            target = upload_dir / "avatar.png"
            target.write_text("x", encoding="utf-8")
            with self.app.app_context():
                main_routes._delete_profile_image("something/avatar.png")
            self.assertFalse(target.exists())

    def test_apply_edit_user_form_when_email_exists(self):
        """
        Comprueba que la actualización del perfil de usuario se rechaza cuando se intenta utilizar una dirección 
        de correo electrónico ya registrada por otro usuario.
        """
        self.create_user(email="exists@example.com")
        user = self.create_user(email="edit-exists@example.com")
        with self.app.test_request_context("/edit_user"):
            login_user(user)
            form = MagicMock()
            form.nombre.data = ""
            form.email.data = "exists@example.com"
            form.country_code.data = "ES"
            form.new_password.data = ""
            form.theme_mode.data = "system"
            form.language.data = "es"
            form.preferred_model.data = "m"
            form.profile_image.data = None
            with patch("app.main.code.controllers.main.routes.User.get_by_email", return_value=User(email="exists@example.com")), patch(
                "app.main.code.controllers.main.routes.t", return_value="dup"
            ):
                self.assertFalse(main_routes._apply_edit_user_form(form))

    def test_update_profile_email_when_field_empty(self):
        """
        Verifica que la actualización del correo electrónico se considera válida cuando el campo correspondiente se deja vacío y 
        no requiere modificación.
        """
        user = self.create_user(email="email-empty@example.com")
        with self.app.test_request_context("/edit_user"):
            login_user(user)
            form = MagicMock()
            form.email.data = ""
            self.assertTrue(main_routes._update_profile_email(form))
