"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de la aplicación, relacionadas con la gestión del historial de consultas RAG y la generación de estadísticas 
para la interfaz de administración. Las pruebas verifican la paginación de consultas, la construcción de métricas de uso, 
la comparación de actividad entre usuarios, la elaboración de mapas geográficos de usuarios y la recuperación de metadatos asociados 
a los fragmentos utilizados durante las consultas. Su objetivo es garantizar la correcta generación de información analítica y 
de seguimiento a partir de los datos almacenados por el sistema.
"""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from flask_login import login_user

from app.main.code.controllers.main.routes import (
    best_pid_for_consulta,
    build_meta_by_consulta,
    build_selected_user_comparison_payload,
    build_usage_stats_payload,
    build_user_country_map_payload,
    paginate_consultas,
)
from app.main.code.model.consulta import Consulta
from app.test.support import BaseAppTestCase


class MainRoutesUnitTest(BaseAppTestCase):
    def test_paginate_consultas_normalizes_page_and_filters_regular_user(self):
        """
        Verifica que la paginación de consultas normaliza correctamente el número de página solicitado y limita los 
        resultados a las consultas del usuario autenticado cuando este no es administrador.
        """
        user = self.create_user(email="regular-page@example.com")
        other = self.create_user(email="other-page@example.com")
        own_consulta = self.create_consulta(user)
        self.create_consulta(other)

        with self.app.test_request_context("/history?page=-4"):
            login_user(user)
            items, page, total_pages, total_consultas = paginate_consultas(Consulta.query.order_by(Consulta.id.asc()))

        self.assertEqual(items, [own_consulta])
        self.assertEqual(page, 1)
        self.assertEqual(total_pages, 1)
        self.assertEqual(total_consultas, 1)

    def test_paginate_consultas_caps_page_and_keeps_admin_scope(self):
        """
        Comprueba que la paginación ajusta automáticamente páginas fuera de rango y permite a los administradores visualizar 
        consultas de todos los usuarios.
        """
        admin = self.create_user(email="admin-page@example.com", is_admin=True)
        user = self.create_user(email="regular-admin-page@example.com")
        self.create_consulta(admin)
        second = self.create_consulta(user)

        with self.app.test_request_context("/history?page=99"):
            login_user(admin)
            items, page, total_pages, total_consultas = paginate_consultas(
                Consulta.query.order_by(Consulta.id.asc()),
                per_page=1,
            )

        self.assertEqual(items, [second])
        self.assertEqual(page, 2)
        self.assertEqual(total_pages, 2)
        self.assertEqual(total_consultas, 2)

    def test_build_usage_stats_payload_counts_queries_and_top_users(self):
        """
        Verifica la generación de estadísticas de uso, incluyendo número de consultas, tiempos de respuesta, actividad diaria, 
        usuarios más activos y métricas comparativas.
        """
        user_1 = self.create_user(nombre="Ana", email="ana@example.com")
        user_2 = self.create_user(nombre="Luis", email="luis@example.com")

        consulta_1 = self.create_consulta(user_1, tiempo_respuestas=1.0)
        consulta_2 = self.create_consulta(user_1, tiempo_respuestas=3.0)
        consulta_3 = self.create_consulta(user_2, tiempo_respuestas=2.0)

        consulta_1.created_at = datetime(2026, 2, 2, 9, 0, tzinfo=ZoneInfo("Europe/Madrid"))
        consulta_2.created_at = datetime(2026, 2, 3, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
        consulta_3.created_at = datetime(2026, 2, 3, 11, 0, tzinfo=ZoneInfo("Europe/Madrid"))

        payload = build_usage_stats_payload([consulta_3, consulta_1, consulta_2], include_top_users=True)

        self.assertEqual(payload["summary"]["total_queries"], 3)
        self.assertEqual(payload["summary"]["avg_response_time"], 2.0)
        self.assertEqual(payload["summary"]["active_days"], 2)
        self.assertIn({"date": "2026-02-02", "avg_time": 1.0}, payload["daily_avg_time"])
        self.assertIn({"date": "2026-02-03", "avg_time": 2.5}, payload["daily_avg_time"])
        feb_3_hours = next(item for item in payload["daily_hourly_queries"] if item["date"] == "2026-02-03")["hours"]
        self.assertEqual(feb_3_hours[10], {"hour": 10, "count": 1})
        self.assertEqual(feb_3_hours[11], {"hour": 11, "count": 1})
        self.assertEqual(payload["top_users"][0], {"user": "Ana", "count": 2})
        self.assertEqual(payload["user_comparison"]["stats"]["mean"], 1.5)
        self.assertEqual(payload["user_comparison"]["stats"]["median"], 1.5)
        self.assertEqual(payload["user_comparison"]["stats"]["variance"], 0.5)

    def test_build_usage_stats_payload_handles_december_calendar_end(self):
        """
        Comprueba la generación correcta de estadísticas cuando no existen consultas registradas y se requiere construir series temporales completas.
        """
        with patch("app.main.code.controllers.main.routes._month_sequence", return_value=[(2026, 12)]):
            payload = build_usage_stats_payload([])

        self.assertEqual(payload["summary"]["total_queries"], 0)
        self.assertEqual(payload["summary"]["avg_response_time"], 0)
        self.assertIsNone(payload["summary"]["first_query_at"])
        self.assertEqual(payload["daily_queries"][-1], {"date": "2026-12-31", "count": 0})

    def test_build_selected_user_comparison_payload_respects_admin_selection(self):
        """
        Verifica la construcción de estadísticas comparativas utilizando únicamente los usuarios seleccionados por un administrador.
        """
        user_1 = self.create_user(nombre="Ana", email="ana-selected@example.com")
        user_2 = self.create_user(nombre="Luis", email="luis-selected@example.com")
        user_3 = self.create_user(nombre="Eva", email="eva-selected@example.com")
        self.create_consulta(user_1)
        self.create_consulta(user_1)
        self.create_consulta(user_2)

        payload = build_selected_user_comparison_payload(
            Consulta.query.order_by(Consulta.id.asc()).all(),
            [user_1, user_2, user_3],
            [user_2.id, user_3.id],
        )

        self.assertEqual(payload["selected_user_ids"], [user_2.id, user_3.id])
        self.assertEqual(
            payload["data"],
            [
                {"user": "Global", "count": 3},
                {"user": "Luis (luis-selected@example.com)", "count": 1},
                {"user": "Eva (eva-selected@example.com)", "count": 0},
            ],
        )
        self.assertEqual(payload["stats"]["mean"], 0.5)
        self.assertEqual(payload["stats"]["median"], 0.5)

    def test_build_selected_user_comparison_payload_defaults_to_all_users(self):
        """
        Comprueba que las comparativas de usuarios incluyen automáticamente a todos los usuarios disponibles cuando no se 
        especifica una selección concreta.
        """
        user_1 = self.create_user(nombre="Ana", email="ana-all@example.com")
        user_2 = self.create_user(nombre="Luis", email="luis-all@example.com")
        user_3 = self.create_user(nombre="Eva", email="eva-all@example.com")
        self.create_consulta(user_1)
        self.create_consulta(user_1)
        self.create_consulta(user_2)

        payload = build_selected_user_comparison_payload(
            Consulta.query.order_by(Consulta.id.asc()).all(),
            [user_1, user_2, user_3],
        )

        self.assertEqual(payload["selected_user_ids"], [user_1.id, user_2.id, user_3.id])
        self.assertEqual([item["count"] for item in payload["data"]], [3, 2, 1, 0])
        self.assertEqual(payload["stats"]["mean"], 1)
        self.assertEqual(payload["stats"]["median"], 1)

    def test_build_user_country_map_payload_hides_names_unless_requested(self):
        """
        Verifica la generación de mapas de distribución geográfica de usuarios, ocultando o mostrando nombres 
        individuales según la configuración solicitada.
        """
        user_1 = self.create_user(nombre="Ana", email="ana-map@example.com", country_code="ES")
        user_2 = self.create_user(nombre="Luis", email="luis-map@example.com", country_code="ES")
        user_3 = self.create_user(nombre="Marie", email="marie-map@example.com", country_code="FR")

        public_payload = build_user_country_map_payload([user_1, user_2, user_3])
        admin_payload = build_user_country_map_payload([user_1, user_2, user_3], include_user_names=True)

        self.assertIn({"country_code": "ES", "country_id": "724", "country_name": "España", "count": 2}, public_payload)
        self.assertNotIn("users", public_payload[0])
        spain = next(item for item in admin_payload if item["country_code"] == "ES")
        self.assertEqual(spain["users"], ["Ana", "Luis"])

    def test_best_pid_for_consulta_uses_fragmentos_chunks_or_empty_value(self):
        """
        Comprueba la obtención del identificador de fragmento más representativo asociado a una consulta utilizando diferentes
        fuentes de información disponibles.
        """
        user = self.create_user(email="pid@example.com")
        consulta_with_fragmentos = self.create_consulta(
            user,
            fragmentos=[
                {"ranking": 2, "qdrant_point_id": "later"},
                {"ranking": 1, "qdrant_point_id": " best-pid "},
            ],
        )
        empty_consulta = self.create_consulta(user)
        chunk = self.create_chunk(qdrant_point_id="chunk-pid")
        linked_consulta = self.create_consulta(user)
        self.link_consulta_chunk(linked_consulta, chunk, ranking=3)

        self.assertEqual(best_pid_for_consulta(consulta_with_fragmentos), "best-pid")
        self.assertEqual(best_pid_for_consulta(empty_consulta), "")
        self.assertEqual(best_pid_for_consulta(linked_consulta), "chunk-pid")

    @patch("app.main.code.controllers.main.routes.qdrant_get_payloads")
    def test_build_meta_by_consulta_uses_saved_fragmentos_and_legacy_qdrant_payloads(self, mock_qdrant):
        """
        Verifica la construcción de metadatos asociados a consultas utilizando tanto fragmentos almacenados directamente como información 
        recuperada desde Qdrant para mantener la compatibilidad con datos históricos.
        """
        user = self.create_user(email="meta@example.com")
        saved = self.create_consulta(
            user,
            fragmentos=[{"ranking": 1, "qdrant_point_id": " saved ", "metadata": {"filename": "saved.pdf"}, "chunk": "txt"}],
        )
        legacy = self.create_consulta(user)
        chunk = self.create_chunk(qdrant_point_id="legacy-pid")
        self.link_consulta_chunk(legacy, chunk, ranking=1)
        mock_qdrant.return_value = {"legacy-pid": {"metadata": {"filename": "legacy.pdf"}, "content": "legacy text"}}

        meta = build_meta_by_consulta([saved, legacy])

        self.assertEqual(meta[saved.id]["qdrant_point_id"], "saved")
        self.assertEqual(meta[saved.id]["metadata"], {"filename": "saved.pdf"})
        self.assertEqual(meta[saved.id]["content"], "txt")
        self.assertEqual(meta[legacy.id]["metadata"], {"filename": "legacy.pdf"})
        self.assertEqual(meta[legacy.id]["content"], "legacy text")
        mock_qdrant.assert_called_once()
