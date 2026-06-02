"""
Autora: Lydia Blanco Ruiz
Script con utilidades compartidas para crear la aplicación de pruebas y datos auxiliares.
Su objetivo es proporcionar un entorno de pruebas aislado y reproducible, incluyendo la creación 
de una aplicación Flask de testing, la configuración de una base de datos temporal SQLite, la simulación 
del módulo RAG mediante implementaciones ficticias (stubs), la gestión automática de recursos temporales y 
diversos métodos auxiliares para crear usuarios, documentos, consultas y fragmentos de prueba.
"""

import asyncio
import atexit
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

from app.main.code import create_app
from app.main.code.extensions import db
from app.main.code.model.chunk import Chunk
from app.main.code.model.consulta import Consulta
from app.main.code.model.consulta_chunk import ConsultaChunk
from app.main.code.model.documento import Documento
from app.main.code.model.user import User

RAG_MODULE_NAME = "app.main.code.services.rag.PrototipoRAG"
PASSWORD_FIELD = "Segura"+"123"


def _install_rag_stub() -> None:
    """
    Instala una implementación simulada del módulo PrototipoRAG para permitir la ejecución de pruebas sin depender de servicios externos de recuperación o generación de respuestas.
    """
    if RAG_MODULE_NAME in sys.modules:
        return

    module = types.ModuleType(RAG_MODULE_NAME)

    class QueryCancelledError(RuntimeError):
        """
        Excepción simulada utilizada para representar cancelaciones de consultas RAG durante las pruebas.
        """

    class OllamaTimeoutError(RuntimeError):
        """
        Excepción simulada utilizada para representar tiempos de espera agotados durante la comunicación con Ollama.
        """

    class OllamaModelNotFoundError(RuntimeError):
        """
        Excepción simulada utilizada para representar errores producidos cuando un modelo solicitado no está disponible.
        """

    class _EmbeddingModel:
        """
        Implementación simulada de un modelo de embeddings utilizada durante las pruebas para proporcionar metadatos de configuración sin depender de un
        modelo real.
        """
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
        """
        Genera una respuesta simulada del sistema RAG devolviendo información ficticia sobre la consulta, los filtros aplicados y el entorno de ejecución.
        También permite simular cancelaciones y actualizaciones de estado durante el procesamiento.
        """
        await asyncio.sleep(0.01)
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

def _cleanup_repo_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for pattern in (
        "cfg_*.json",
        "guard_cfg_*.json",
        "configuracion.json",
        "guard_out_*.json",
        "guard_rows_*.json",
        "out_*.json",
        "q_*.json",
        "rows_*.json",
    ):
        """
        Elimina automáticamente artefactos temporales generados por los procesos de evaluación y pruebas, evitando que interfieran en ejecuciones posteriores.
        """
        for candidate in repo_root.glob(pattern):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass

_cleanup_repo_artifacts()
atexit.register(_cleanup_repo_artifacts)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    """
    Configura SQLite para habilitar la comprobación de claves foráneas en todas las conexiones utilizadas durante las pruebas.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class BaseAppTestCase(unittest.TestCase):
    def setUp(self):
        """
        Inicializa un entorno de pruebas aislado creando una aplicación Flask temporal, una base de datos SQLite independiente y directorios temporales para 
        almacenar datos y documentos.
        """
        self._env_backup = {
            key: os.environ.get(key)
            for key in ("FLASK_SESSION_SIGNER", "DATABASE_URL", "DATA_DIR", "DOCS_DIR")
        }
        self._tmpdir = Path(tempfile.mkdtemp(prefix="pythia-tests-"))
        self._db_path = self._tmpdir / "test.sqlite"
        self._docs_dir = self._tmpdir / "docs"

        os.environ["FLASK_SESSION_SIGNER"] = "test-session-signer"
        os.environ["DATABASE_URL"] = f"sqlite:///{self._db_path.as_posix()}"
        os.environ["DATA_DIR"] = str(self._tmpdir / "data")
        os.environ["DOCS_DIR"] = str(self._docs_dir)

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
        """
        Libera los recursos utilizados durante la prueba, elimina archivos temporales y restaura las variables de entorno originales.
        """
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()
        # Limpia artefactos en la raíz del repo si algún test o script escribió por ruta relativa.
        try:
            repo_root = Path(__file__).resolve().parents[3]
            for pattern in ("cfg_*.json", "guard_cfg_*.json", "configuracion.json"):
                for candidate in repo_root.glob(pattern):
                    try:
                        candidate.unlink(missing_ok=True)
                    except OSError:
                        pass
        except OSError:
            pass
        shutil.rmtree(self._tmpdir, ignore_errors=True)

        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def create_user(self, **kwargs) -> User:
        """
        Crea y almacena un usuario de prueba con los atributos indicados.
        """
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

    def login(self, email: str, password: str = PASSWORD_FIELD, follow_redirects: bool = False):
        """
        Realiza el proceso de autenticación de un usuario dentro del entorno de pruebas.
        """
        return self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=follow_redirects,
        )

    def create_document(self, **kwargs) -> Documento:
        """
        Crea un documento de prueba y genera automáticamente un fichero PDF temporal asociado.
        """
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
        """
        Crea un fragmento documental asociado a un documento existente o generado automáticamente.
        """
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
        """
        Crea una consulta de prueba asociada a un usuario determinado.
        """
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
        """
        Establece una relación entre una consulta y un fragmento documental recuperado durante una búsqueda RAG.
        """
        link = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk.id,
            similitud=kwargs.get("similitud", 0.9),
            ranking=kwargs.get("ranking", 1),
        )
        db.session.add(link)
        db.session.commit()
        return link
