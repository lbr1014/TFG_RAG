"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de la aplicación.
"""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from flask_login import login_user

from tests.support import BaseAppTestCase

from app.entities.consulta import Consulta
from app.main.routes import best_pid_for_consulta, build_meta_by_consulta, build_usage_stats_payload, paginate_consultas


class MainRoutesUnitTest(BaseAppTestCase):
    def test_paginate_consultas_normalizes_page_and_filters_regular_user(self):
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
        self.assertEqual(payload["top_users"][0], {"user": "Ana", "count": 2})

    def test_build_usage_stats_payload_handles_december_calendar_end(self):
        with patch("app.main.routes._month_sequence", return_value=[(2026, 12)]):
            payload = build_usage_stats_payload([])

        self.assertEqual(payload["summary"]["total_queries"], 0)
        self.assertEqual(payload["summary"]["avg_response_time"], 0)
        self.assertEqual(payload["summary"]["first_query_at"], None)
        self.assertEqual(payload["daily_queries"][-1], {"date": "2026-12-31", "count": 0})

    def test_best_pid_for_consulta_uses_fragmentos_chunks_or_empty_value(self):
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

    @patch("app.main.routes.qdrant_get_payloads")
    def test_build_meta_by_consulta_uses_saved_fragmentos_and_legacy_qdrant_payloads(self, mock_qdrant):
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
