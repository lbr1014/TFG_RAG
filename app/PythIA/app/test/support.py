"""
Autora: Lydia Blanco Ruiz
Script con utilidades compartidas para crear la aplicación de pruebas y datos auxiliares.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine


def _install_rag_stub() -> None:
    if "app.main.code.services.rag.PrototipoRAG" in sys.modules:
        return

    module = types.ModuleType("app.main.code.services.rag.PrototipoRAG")

    class QueryCancelledError(RuntimeError):
        pass

    class OllamaTimeoutError(RuntimeError):
        pass

    class OllamaModelNotFoundError(RuntimeError):
        pass

    class _EmbeddingModel:
        model_id = "test-embedding-model"
        embedding_size = 3
        max_input_length = 128

    async def obtener_mejor_chunk(
        user_query: str,
        model: str = "fake-model",
        should_cancel=None,
        on_status=None,
        numero_expediente=None,
        tipo_documento=None,
        query_profile="general",
        retrieval_k=10,
        min_similarity=None,
    ) -> dict:
        if should_cancel and should_cancel():
            raise QueryCancelledError("Consulta cancelada por el usuario.")
        if on_status:
            on_status("Respuesta simulada.")
        return {
            "answer": f"Respuesta simulada para: {user_query}",
            "title": "",
            "filename": "",
            "segment_index": -1,
            "chunk": "",
            "retrieved": [],
            "execution_device": "CPU",
            "query_profile": query_profile,
            "retrieval_k": retrieval_k,
            "min_similarity": min_similarity,
            "applied_filters": {
                "numero_expediente": numero_expediente,
                "tipo_documento": tipo_documento,
            },
        }

    module.QueryCancelledError = QueryCancelledError
    module.OllamaTimeoutError = OllamaTimeoutError
    module.OllamaModelNotFoundError = OllamaModelNotFoundError
    module.embedding_model = _EmbeddingModel()
    module.resolve_rag_llm_model = lambda model=None: (model or "fake-model").strip() or "fake-model"
    module.get_ollama_execution_device = lambda: "CPU"
    module.get_rag_llm_model_choices = lambda: [
        ("fake-model", "fake-model"),
        ("gemma3:4b", "gemma3:4b"),
        ("qwen3:4b-instruct", "qwen3:4b-instruct"),
    ]
    module.qdrant_get_payloads = lambda point_ids: {}
    module.qdrant_delete_by_filename = lambda filename: None
    module.index_pliegos_dir = lambda path: {}
    module.index_pdf = lambda *args, **kwargs: []
    module.index_markdown = lambda *args, **kwargs: []
    module.obtener_mejor_chunk = obtener_mejor_chunk
    sys.modules["app.main.code.services.rag.PrototipoRAG"] = module


_install_rag_stub()

from app.main.code import create_app  # noqa: E402
from app.main.code.model.chunk import Chunk  # noqa: E402
from app.main.code.model.consulta import Consulta  # noqa: E402
from app.main.code.model.consulta_chunk import ConsultaChunk  # noqa: E402
from app.main.code.model.documento import Documento  # noqa: E402
from app.main.code.model.user import User  # noqa: E402
from app.main.code.extensions import db  # noqa: E402


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class BaseAppTestCase(unittest.TestCase):
    def setUp(self):
        self._env_backup = {key: os.environ.get(key) for key in ("FLASK_SESSION_SIGNER", "DATABASE_URL")}
        self._tmpdir = Path(tempfile.mkdtemp(prefix="pythia-tests-"))
        self._db_path = self._tmpdir / "test.sqlite"
        self._docs_dir = self._tmpdir / "docs"

        os.environ["FLASK_SESSION_SIGNER"] = "test-session-signer"
        os.environ["DATABASE_URL"] = f"sqlite:///{self._db_path.as_posix()}"

        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            MAIL_SUPPRESS_SEND=True,
            DOCS_DIR=str(self._docs_dir),
        )
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def create_user(self, **kwargs) -> User:
        counter = User.query.count() + 1
        user = User(
            nombre=kwargs.get("nombre", f"Usuario {counter}"),
            email=kwargs.get("email", f"user{counter}@example.com"),
            country_code=kwargs.get("country_code", "ES"),
            is_admin=kwargs.get("is_admin", False),
        )
        user.set_password(kwargs.get("password", "Segura123"))
        db.session.add(user)
        db.session.commit()
        return user

    def login(self, email: str, password: str = "Segura123", follow_redirects: bool = False):
        return self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=follow_redirects,
        )

    def create_document(self, **kwargs) -> Documento:
        filename = kwargs.get("nombre", "licitacion.pdf")
        path = self._docs_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"%PDF-1.4 test\n")

        document = Documento(
            nombre=filename,
            path=str(path),
            size_bytes=kwargs.get("size_bytes", path.stat().st_size),
            modified_at=kwargs.get("modified_at"),
            chunks=kwargs.get("chunks", 0),
            hash=kwargs.get("hash", "hash-doc"),
            status=kwargs.get("status", "cargado"),
            error_message=kwargs.get("error_message"),
            numero_expediente=kwargs.get("numero_expediente"),
            tipo_documento=kwargs.get("tipo_documento"),
        )
        db.session.add(document)
        db.session.commit()
        return document

    def create_chunk(self, document: Documento | None = None, **kwargs) -> Chunk:
        document = document or self.create_document()
        chunk = Chunk(
            document_id=document.id,
            qdrant_point_id=kwargs.get("qdrant_point_id", "qid-1"),
            segment_index=kwargs.get("segment_index", 0),
            doc_sha256=kwargs.get("doc_sha256", "hash-doc"),
            n_chars=kwargs.get("n_chars", 10),
            n_tokens=kwargs.get("n_tokens", 3),
            numero_expediente=kwargs.get("numero_expediente"),
            tipo_documento=kwargs.get("tipo_documento"),
        )
        db.session.add(chunk)
        db.session.commit()
        return chunk

    def create_consulta(self, user: User, **kwargs) -> Consulta:
        consulta = Consulta(
            user_id=user.id,
            pregunta=kwargs.get("pregunta", "Pregunta"),
            respuesta=kwargs.get("respuesta", "Respuesta"),
            fragmentos=kwargs.get("fragmentos", []),
            tiempo_respuestas=kwargs.get("tiempo_respuestas", 0.25),
        )
        db.session.add(consulta)
        db.session.commit()
        return consulta

    def link_consulta_chunk(self, consulta: Consulta, chunk: Chunk, **kwargs) -> ConsultaChunk:
        link = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk.id,
            similitud=kwargs.get("similitud", 0.9),
            ranking=kwargs.get("ranking", 1),
        )
        db.session.add(link)
        db.session.commit()
        return link
