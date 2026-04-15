"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de la aplicación.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from tests.support import BaseAppTestCase

from app.main.routes import build_usage_stats_payload


class MainHelpersUnitTest(BaseAppTestCase):
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
