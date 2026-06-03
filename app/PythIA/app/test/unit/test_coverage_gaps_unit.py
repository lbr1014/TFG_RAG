import asyncio
import os
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask


class CreateAppPathsUnitTest(unittest.TestCase):
    def test_create_app_uses_data_dir_for_profiles_and_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            env = {
                "DATABASE_URL": "sqlite:///:memory:",
                "DATA_DIR": str(data_dir),
                "DOCS_DIR": "pliegos",
                "SECRET_KEY": "test",
                "FLASK_SESSION_SIGNER": "signer",
            }
            with patch.dict(os.environ, env, clear=False), patch(
                "dotenv.load_dotenv", return_value=False
            ):
                import importlib

                import app.main.code as code_pkg

                importlib.reload(code_pkg)
                app = code_pkg.create_app()

            self.assertEqual(Path(app.config["DATA_DIR"]).resolve(), data_dir.resolve())
            self.assertEqual(Path(app.config["DOCS_DIR"]).resolve(), (data_dir / "pliegos").resolve())
            self.assertEqual(
                Path(app.config["PROFILE_UPLOAD_FOLDER"]).resolve(), (data_dir / "profiles").resolve()
            )
            self.assertTrue(Path(app.config["PROFILE_UPLOAD_FOLDER"]).exists())


class RagRoutesPayloadsUnitTest(unittest.TestCase):
    def test_build_expediente_type_payload_aggregates_and_sorts(self):
        from app.main.code.controllers.rag import routes as rag_routes

        fake_query = MagicMock()
        fake_query.filter.return_value = fake_query
        fake_query.distinct.return_value = fake_query
        fake_query.all.return_value = [
            ("EXP-1", "administrativo"),
            ("EXP-1", "tecnico"),
            ("EXP-2", "administrativo"),
            ("", "tecnico"),
            ("EXP-3", ""),
        ]

        fake_session = MagicMock()
        fake_session.query.return_value = fake_query

        with patch.object(rag_routes, "db") as mock_db:
            mock_db.session = fake_session
            payload = rag_routes.build_expediente_type_payload()

        self.assertEqual(payload["EXP-1"], ["administrativo", "tecnico"])
        self.assertEqual(payload["EXP-2"], ["administrativo"])
        self.assertNotIn("EXP-3", payload)

    def test_build_model_usage_index_payload_counts_months_global(self):
        from app.main.code.controllers.rag import routes as rag_routes

        class _Job:
            def __init__(self, created_at, model_name=None, result_payload=None, user_id=1):
                self.created_at = created_at
                self.model_name = model_name
                self.result_payload = result_payload
                self.user_id = user_id

        now = datetime.now(timezone.utc)
        jobs = [
            _Job(created_at=now, model_name="m1", user_id=1),
            _Job(created_at=now, model_name="m1", user_id=2),
            _Job(created_at=now, model_name="", result_payload={"model": "m2"}, user_id=1),
        ]

        base_query = MagicMock()
        base_query.filter.return_value = base_query
        base_query.order_by.return_value = base_query
        base_query.all.return_value = jobs

        with patch.object(rag_routes, "RAGQueryState") as mock_state, patch(
            "app.main.code.controllers.rag.routes.current_user",
            new=types.SimpleNamespace(is_admin=False, id=1),
        ):
            mock_state.query.filter.return_value = base_query
            payload = rag_routes.build_model_usage_index_payload(months=2)

        self.assertEqual(len(payload["labels"]), 2)
        # La query está mockeada, así que devolvemos jobs de varios usuarios para cubrir el agregado por mes/modelo.
        self.assertEqual(payload["series"]["m1"][-1], 2)
        self.assertEqual(payload["series"]["m2"][-1], 1)


class MainRoutesHelpersUnitTest(unittest.TestCase):
    def test_history_filters_normalizes_sort_and_device(self):
        from app.main.code.controllers.main import routes as main_routes

        app = Flask(__name__)
        with app.test_request_context(
            "/history?sort=invalid&device=gpu&user_id=1&date=2026-01-01&model=x"
        ):
            with patch(
                "app.main.code.controllers.main.routes.current_user",
                new=types.SimpleNamespace(is_admin=True),
            ):
                filters = main_routes._history_filters()

        self.assertEqual(filters["sort"], main_routes.HISTORY_SORT_DATE_DESC)
        self.assertEqual(filters["device"], "GPU")

    def test_profile_initial_prefers_name_then_email_then_fallback(self):
        from app.main.code.controllers.main import routes as main_routes

        u1 = types.SimpleNamespace(nombre=" Lydia ", email="a@b.com")
        u2 = types.SimpleNamespace(nombre="", email=" mail@example.com ")
        u3 = types.SimpleNamespace(nombre=None, email=None, id=7)

        self.assertEqual(main_routes._profile_initial(u1), "L")
        self.assertEqual(main_routes._profile_initial(u2), "M")
        self.assertEqual(main_routes._profile_initial(u3), "U")

    def test_save_profile_image_rejects_invalid_extension(self):
        from app.main.code.controllers.main import routes as main_routes

        storage = types.SimpleNamespace(filename="avatar.exe")
        self.assertIsNone(main_routes._save_profile_image(storage))

    def test_delete_profile_image_noop_on_empty(self):
        from app.main.code.controllers.main import routes as main_routes

        app = Flask(__name__)
        app.config["PROFILE_UPLOAD_FOLDER"] = Path(tempfile.gettempdir()) / "profiles-test"
        with app.app_context():
            main_routes._delete_profile_image(None)
            main_routes._delete_profile_image("")

    def test_apply_history_sort_falls_back_to_date_desc(self):
        from app.main.code.controllers.main import routes as main_routes

        query = MagicMock()
        main_routes._apply_history_sort(query, "unknown")
        query.order_by.assert_called_once()

    def test_display_name_for_donut_prefers_nombre_then_email_then_id(self):
        from app.main.code.controllers.main import routes as main_routes

        self.assertEqual(
            main_routes.display_name_for_donut(types.SimpleNamespace(nombre="N", email="e", id=1)),
            "N",
        )
        self.assertEqual(
            main_routes.display_name_for_donut(types.SimpleNamespace(nombre="", email="e", id=1)),
            "e",
        )
        self.assertEqual(
            main_routes.display_name_for_donut(types.SimpleNamespace(nombre=None, email=None, id=3)),
            "Usuario 3",
        )


class AdminRoutesHelpersUnitTest(unittest.TestCase):
    def test_validate_post_action_returns_json_on_invalid_csrf(self):
        from app.main.code.controllers.admin import routes as admin_routes

        fake_form = MagicMock()
        fake_form.validate_on_submit.return_value = False
        with patch("app.main.code.controllers.admin.routes.EmptyForm", return_value=fake_form), patch(
            "app.main.code.controllers.admin.routes.t", lambda key, **_k: key
        ):
            app = Flask(__name__)
            with app.test_request_context("/admin/users", method="POST"):
                resp = admin_routes._validate_post_action(json_response=True)
        self.assertEqual(resp[1], 400)

    def test_users_query_from_filters_applies_name_country_and_role(self):
        from app.main.code.controllers.admin import routes as admin_routes

        query = MagicMock()
        query.filter.return_value = query
        query.order_by.return_value = query
        with patch.object(admin_routes, "User") as mock_user:
            mock_user.query = query
            mock_user.nombre = MagicMock()
            mock_user.country_code = MagicMock()
            mock_user.is_admin = MagicMock()

            # Country must exist in mapping to apply
            with patch.object(admin_routes, "COUNTRY_BY_CODE", {"ES": "Spain"}):
                out = admin_routes._users_query_from_filters(
                    {"name": "ana", "country": "es", "role": "admin"}
                )
        self.assertIs(out, query)
        self.assertTrue(query.filter.called)


class ChunkModelUnitTest(unittest.TestCase):
    def test_find_from_retrieved_item_prefers_qdrant_point_id_then_fallback(self):
        from app.main.code.extensions import db
        from app.main.code.model.chunk import Chunk
        from app.main.code.model.documento import Documento

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        db.init_app(app)

        with app.app_context():
            db.create_all()

            doc = Documento(
                id=1,
                nombre="doc.pdf",
                path="/tmp/doc.pdf",
                size_bytes=1,
                hash="h",
                status="cargado",
            )
            db.session.add(doc)
            db.session.flush()

            # Inserta un chunk para poder resolver por qdrant_point_id.
            c = Chunk(
                document_id=1,
                doc_sha256="h",
                segment_index=2,
                qdrant_point_id="abc",
                n_chars=1,
                n_tokens=1,
            )
            db.session.add(c)
            db.session.commit()

            found = Chunk.find_from_retrieved_item({"qdrant_point_id": "abc"})
            self.assertIsNotNone(found)
            self.assertEqual(found.qdrant_point_id, "abc")

            found2 = Chunk.find_from_retrieved_item(
                {"document_id": 1, "doc_sha256": "h", "segment_index": 2}
            )
            self.assertIsNotNone(found2)
            self.assertEqual(found2.segment_index, 2)


class DocumentosServiceUnitTest(unittest.TestCase):
    def test_update_vector_db_honors_should_cancel(self):
        from app.main.code.services.documentos import DocumentosService, JobCancelledError

        svc = DocumentosService(Path("."), index_pliegos_dir=MagicMock(), delete_chunks=MagicMock(), markdown_converter=MagicMock())
        with patch("app.main.code.services.documentos.Documento") as mock_doc:
            mock_doc.query.filter.return_value.all.return_value = [MagicMock(nombre="doc", path="x", status="cargado")]
            with self.assertRaises(JobCancelledError):
                svc.update_vector_db(should_cancel=lambda: True)


class PrototipoRAGOllamaDeviceUnitTest(unittest.TestCase):
    def test_effective_device_reads_ps_size_vram(self):
        # Módulo real para acceder a httpx y a la lógica de device.
        import sys
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "app" / "main" / "code" / "services" / "rag" / "PrototipoRAG.py"
        loader = SourceFileLoader("PrototipoRAG_real_for_coverage_gaps", str(module_path))
        spec = spec_from_loader(loader.name, loader)
        pr = module_from_spec(spec)
        sys.modules[loader.name] = pr
        loader.exec_module(pr)

        class _Resp:
            def __init__(self, payload):
                self._payload = payload
                self.content = b"x"

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class _Client:
            def __init__(self, payload):
                self._payload = payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, _path):
                return _Resp(self._payload)

        payload = {"models": [{"name": "m", "size_vram": 123}]}
        with patch.object(pr.httpx, "AsyncClient", return_value=_Client(payload)):
            device = asyncio.run(pr.get_ollama_effective_execution_device(model_name="m"))
        self.assertEqual(device, "GPU")

        payload2 = {"models": [{"name": "m", "size_vram": 0}]}
        with patch.object(pr.httpx, "AsyncClient", return_value=_Client(payload2)):
            device = asyncio.run(pr.get_ollama_effective_execution_device(model_name="m"))
        self.assertEqual(device, "CPU")


class DescargarPliegosUnitTest(unittest.TestCase):
    def test_limpiar_expediente_replaces_bad_chars_and_fallback(self):
        from app.main.code.services.web_scraping.DescargarPliegos import (
            limpiar_expediente,
        )

        self.assertEqual(limpiar_expediente(" EXP/12 "), "EXP_12")
        self.assertEqual(limpiar_expediente(".."), "expediente")

    def test_ensure_dest_dir_falls_back_on_permission_error(self):
        import importlib

        mod = importlib.import_module("app.main.code.services.web_scraping.DescargarPliegos")
        original_dest = mod.DEST
        try:
            configured = "C:\\data\\pliegos" if os.name == "nt" else "/data/pliegos"
            mod.DEST = Path(configured)  
            with patch.object(Path, "mkdir", side_effect=[PermissionError(), None]) as _mk, patch.dict(
                os.environ, {"DOCS_DIR": configured}
            ):
                mod.ensure_dest_dir()
            self.assertEqual(mod.DEST, Path("pliegos"))
        finally:
            mod.DEST = original_dest
