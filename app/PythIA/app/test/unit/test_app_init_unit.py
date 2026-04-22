"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de la factoria de aplicacion.
"""

import os
from unittest.mock import patch

import app.main.code as app_factory
from app.main.code.model.user import User
from app.main.code.extensions import login_manager
from app.test.support import BaseAppTestCase


class AppInitHelpersUnitTest(BaseAppTestCase):
    def test_get_required_env_raises_when_value_is_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                app_factory._get_required_env("FLASK_SESSION_SIGNER")

        self.assertIn("FLASK_SESSION_SIGNER", str(raised.exception))

    def test_build_database_url_returns_none_when_postgres_parts_are_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(app_factory._build_database_url_from_env())

        with patch.dict(os.environ, {"POSTGRES_USER": "user", "POSTGRES_PASSWORD": "pass"}, clear=True):
            self.assertIsNone(app_factory._build_database_url_from_env())

    def test_build_database_url_prefers_database_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///direct.sqlite"}, clear=True):
            self.assertEqual(app_factory._build_database_url_from_env(), "sqlite:///direct.sqlite")

    def test_build_database_url_builds_postgres_url_with_defaults(self):
        env = {
            "POSTGRES_USER": "pythia",
            "POSTGRES_PASSWORD": "secret",
            "POSTGRES_DB": "rag",
        }

        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                app_factory._build_database_url_from_env(),
                "postgresql+psycopg2://pythia:secret@db:5432/rag",
            )

    def test_build_database_url_builds_postgres_url_with_custom_host_and_port(self):
        env = {
            "POSTGRES_USER": "pythia",
            "POSTGRES_PASSWORD": "secret",
            "POSTGRES_DB": "rag",
            "POSTGRES_HOST": "postgres.local",
            "POSTGRES_PORT": "6543",
        }

        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                app_factory._build_database_url_from_env(),
                "postgresql+psycopg2://pythia:secret@postgres.local:6543/rag",
            )


class CreateAppUnitTest(BaseAppTestCase):
    def test_create_app_raises_when_database_url_cannot_be_built(self):
        with patch("app.main.code.load_dotenv"), patch.dict(
            os.environ,
            {"FLASK_SESSION_SIGNER": "test-secret"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as raised:
                app_factory.create_app()

        self.assertIn("DATABASE_URL", str(raised.exception))

    def test_create_app_normalizes_legacy_postgres_url(self):
        with patch("app.main.code.load_dotenv"), patch.object(app_factory.db, "init_app"), patch.object(
            app_factory.migrate, "init_app"
        ), patch.object(app_factory.mail, "init_app"), patch.object(app_factory.csrf, "init_app"), patch.dict(
            os.environ,
            {
                "FLASK_SESSION_SIGNER": "test-secret",
                "DATABASE_URL": "postgres://user:pass@db:5432/rag",
            },
            clear=True,
        ):
            created_app = app_factory.create_app()

        self.assertEqual(
            created_app.config["SQLALCHEMY_DATABASE_URI"],
            "postgresql://user:pass@db:5432/rag",
        )

    def test_login_manager_user_loader_loads_user_by_integer_id(self):
        with patch.object(User, "get_by_id", return_value="loaded-user") as mock_get_by_id:
            self.assertEqual(login_manager._user_callback("12"), "loaded-user")

        mock_get_by_id.assert_called_once_with(12)
