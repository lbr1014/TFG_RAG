"""
Autora: Lydia Blanco Ruiz
Script para gestionar documentos PDF, su sincronización, conversión a Markdown e indexación en la base de datos vectorial.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Iterable, Optional
import unicodedata
from zoneinfo import ZoneInfo

from werkzeug.utils import secure_filename

from .entities.chunk import Chunk
from .entities.consulta_chunk import ConsultaChunk
from .entities.documento import Documento
from .entities.embedding import Embedding
from .extensions import db

ALLOWED_EXT = {".pdf"}
MADRID_TZ = ZoneInfo("Europe/Madrid")
STATUS_WITH_MARKDOWN = "con markdown"


class JobCancelledError(RuntimeError):
    """Excepción lanzada cuando un proceso largo se cancela manualmente."""

    pass


def sha256_file(path: Path) -> str:
    """Calcula el hash SHA-256 de un archivo.

    Args:
        path: Ruta del archivo cuyo contenido se va a resumir.

    Returns:
        El hash SHA-256 del archivo en formato hexadecimal.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_text(value: str) -> str:
    """Normaliza un texto para comparaciones flexibles.

    Args:
        value: Texto original que se desea normalizar.

    Returns:
        El texto en minusculas, sin tildes y sin espacios sobrantes.
    """
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return normalized.lower().strip()


def infer_document_metadata_from_filename(filename: str) -> tuple[str | None, str | None]:
    """Infiere metadatos del documento a partir del nombre del archivo.

    Args:
        filename: Nombre del archivo PDF.

    Returns:
        Una tupla con el Número de expediente y el tipo de documento.
    """
    stem = Path(filename or "").stem
    if "__" not in stem:
        return None, None

    expediente_part, doc_part = stem.split("__", 1)
    expediente = expediente_part.strip() or None

    match = re.match(r"(?P<doc>.+?)_(?P<index>\d+)$", doc_part.strip())
    raw_doc_name = match.group("doc").strip() if match else doc_part.strip()

    normalized_doc_name = _normalize_text(raw_doc_name).replace("_", " ")
    if "clausulas administrativas" in normalized_doc_name or "administrativ" in normalized_doc_name:
        return expediente, "administrativo"
    if "prescripciones tecnicas" in normalized_doc_name or "tecnic" in normalized_doc_name:
        return expediente, "tecnico"

    return expediente, None


class DocumentosService:
    """Servicio de gestion documental para archivos, Markdown e indexación."""

    def __init__(
        self,
        docs_dir: Path,
        index_pliegos_dir,
        delete_chunks,
        markdown_converter=None,
    ):
        """Construye el servicio con sus dependencias principales.

        Args:
            docs_dir: Directorio base donde se almacenan los PDFs.
            index_pliegos_dir: Dependencia para la función de pliegos.
            delete_chunks: Función que elimina chunks previos del indice.
            markdown_converter: Función opcional para convertir PDFs a Markdown.
        """
        self.docs_dir = docs_dir
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        self.index_pliegos_dir = index_pliegos_dir
        self.delete_chunks = delete_chunks
        self.markdown_converter = markdown_converter

    def filename(self, filename: str) -> str:
        """Genera un nombre de archivo seguro.

        Args:
            filename: Nombre de archivo original.

        Returns:
            El nombre seguro para usarlo en disco.
        """
        return secure_filename(filename or "")

    def resolve_pdf_path(self, filename: str) -> Path:
        """Resuelve la ruta absoluta de un PDF.

        Args:
            filename: Nombre del archivo PDF.

        Returns:
            La ruta absoluta donde debe almacenarse el PDF.
        """
        safe = self.filename(filename)
        if not safe:
            raise ValueError("Nombre de archivo invalido")
        if Path(safe).suffix.lower() not in ALLOWED_EXT:
            raise ValueError("Extensión no permitida")
        return self.docs_dir / safe

    def _is_pdf_upload(self, file_storage) -> bool:
        """Comprueba extensión y firma del archivo subido sin consumir el stream.

        Args:
            file_storage: Archivo recibido desde un formulario Flask-WTF.

        Returns:
            ``True`` si el nombre termina en ``.pdf`` y el contenido empieza
            con la firma ``%PDF-``.
        """
        filename = self.filename(getattr(file_storage, "filename", ""))
        if not filename or Path(filename).suffix.lower() not in ALLOWED_EXT:
            return False

        stream = getattr(file_storage, "stream", None)
        if stream is None:
            return False

        if not hasattr(stream, "seekable") or not stream.seekable():
            return False

        position = stream.tell()
        header = stream.read(5)
        stream.seek(position)

        return header == b"%PDF-"

    def list_documents_paginated(self, page: int, per_page: int):
        """Obtiene documentos paginados ordenados por fecha de modificación.

        Args:
            page: Número de página solicitado.
            per_page: Número de elementos por página.

        Returns:
            El objeto de paginación devuelto por SQLAlchemy.
        """
        return Documento.query.order_by(Documento.modified_at.desc()).paginate(
            page=page,
            per_page=per_page,
            error_out=False,
        )

    def has_markdown(self, doc: Documento) -> bool:
        """Comprueba si un documento dispone de Markdown valido.

        Args:
            doc: Documento que se va a comprobar.

        Returns:
            ``True`` si el documento tiene Markdown actual y valido.
        """
        return bool(doc.markdown_content)

    def get_markdown_status_map(self, docs: Iterable[Documento]) -> dict[int, bool]:
        """Calcula si cada documento de una coleccion tiene Markdown.

        Args:
            docs: Coleccion de documentos a evaluar.

        Returns:
            Un diccionario ``document_id -> tiene_markdown``.
        """
        return {doc.id: self.has_markdown(doc) for doc in docs}

    def count_pending_markdown(self, docs: Iterable[Documento] | None = None) -> int:
        """Cuenta cuantos documentos siguen pendientes de Markdown.

        Args:
            docs: Coleccion opcional de documentos a evaluar.

        Returns:
            El Número de documentos sin Markdown disponible.
        """
        if docs is None:
            docs = Documento.query.all()
        return sum(1 for doc in docs if not self.has_markdown(doc))

    def save_uploads(self, files: Iterable) -> int:
        """Guarda en disco los archivos subidos y actualiza la base de datos.

        Args:
            files: Coleccion de archivos recibidos en una subida.

        Returns:
            El número de PDFs guardados.
        """
        saved = 0
        for f in files:
            if not f or not f.filename:
                continue

            if not self._is_pdf_upload(f):
                continue

            dest = self.resolve_pdf_path(f.filename)
            f.save(dest)
            self._upsert_from_path(dest, status="cargado")
            saved += 1

        db.session.commit()
        return saved

    def sync_from_folder(self) -> None:
        """Sincroniza la base de datos con los PDFs existentes en disco.

        Returns:
            None.
        """
        for p in sorted(self.docs_dir.glob("*.pdf")):
            self._upsert_from_path(p, status=None)
        db.session.commit()
        self.purge_missing_files()

    def purge_missing_files(self) -> int:
        """Elimina registros y relaciones de documentos que ya no existen.

        Returns:
            El Número de documentos eliminados de la base de datos.
        """
        deleted = 0
        for doc in Documento.query.all():
            if Path(doc.path).exists():
                continue

            self.clear_markdown_content(doc)
            try:
                self.delete_chunks(doc.nombre)
            except Exception:
                pass
            self.delete_document_relations(doc)
            db.session.delete(doc)
            deleted += 1

        if deleted:
            db.session.commit()
        return deleted

    def _upsert_from_path(self, p: Path, status: Optional[str]) -> None:
        """Crea o actualiza un documento a partir de un PDF en disco.

        Args:
            p: Ruta del PDF que se va a sincronizar.
            status: Estado opcional que debe asignarse al documento.

        Returns:
            None.
        """
        stat = p.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, MADRID_TZ)
        rel_path = str(p)
        file_hash = sha256_file(p)
        numero_expediente, tipo_documento = infer_document_metadata_from_filename(p.name)

        doc = Documento.query.filter_by(path=rel_path).first()
        if not doc:
            doc = Documento(
                nombre=p.name,
                path=rel_path,
                size_bytes=stat.st_size,
                modified_at=mtime,
                chunks=0,
                hash=file_hash,
                markdown_content=None,
                status=status or "cargado",
                error_message=None,
                numero_expediente=numero_expediente,
                tipo_documento=tipo_documento,
            )
            db.session.add(doc)
            return

        previous_hash = doc.hash
        hash_changed = previous_hash != file_hash

        doc.nombre = p.name
        doc.size_bytes = stat.st_size
        doc.modified_at = mtime
        doc.hash = file_hash
        doc.numero_expediente = numero_expediente
        doc.tipo_documento = tipo_documento

        if hash_changed:
            self.clear_markdown_content(doc)

        if status is not None:
            doc.status = self._status_for_existing_markdown(status, doc.markdown_content)
            doc.error_message = None
        elif doc.markdown_content and doc.status != "indexado":
            doc.status = STATUS_WITH_MARKDOWN

    def delete_document(self, doc_id: int) -> None:
        """Elimina un documento, su PDF y sus relaciones asociadas.

        Args:
            doc_id: Identificador del documento que se va a borrar.

        Returns:
            None.
        """
        doc = Documento.query.get(doc_id)
        if not doc:
            return

        try:
            self.delete_chunks(doc.nombre)
        except Exception:
            pass

        self.delete_document_relations(doc)

        try:
            pdf_path = Path(doc.path)
            if pdf_path.exists():
                pdf_path.unlink()
        except Exception:
            pass

        self.clear_markdown_content(doc)
        db.session.delete(doc)
        db.session.commit()

    def clear_markdown_content(self, doc: Documento) -> None:
        """Limpia el contenido Markdown asociado a un documento.

        Args:
            doc: Documento cuyo Markdown debe limpiarse.

        Returns:
            None.
        """
        doc.markdown_content = None

    def _status_for_existing_markdown(self, base_status: str, markdown_content: str | None) -> str:
        """Determina el estado correcto cuando ya existe Markdown.

        Args:
            base_status: Estado base del documento.
            markdown_content: Contenido Markdown disponible.

        Returns:
            El estado que debe persistirse para el documento.
        """
        if markdown_content and base_status != "indexado":
            return STATUS_WITH_MARKDOWN
        return base_status

    def delete_document_relations(self, doc: Documento) -> None:
        """Elimina chunks y relaciones asociadas a un documento.

        Args:
            doc: Documento cuyas relaciones deben eliminarse.

        Returns:
            None.
        """
        chunk_ids_subq = db.session.query(Chunk.id).filter(Chunk.document_id == doc.id).subquery()

        ConsultaChunk.query.filter(
            ConsultaChunk.chunk_id.in_(chunk_ids_subq)
        ).delete(synchronize_session=False)
        db.session.commit()

        Embedding.query.filter(
            Embedding.chunk_id.in_(chunk_ids_subq)
        ).delete(synchronize_session=False)
        db.session.commit()

        Chunk.query.filter(Chunk.document_id == doc.id).delete(synchronize_session=False)
        db.session.commit()

    def convert_document_to_markdown(self, doc: Documento, on_page_start=None) -> bool:
        """Convierte un documento individual a Markdown si es necesario.

        Args:
            doc: Documento que se quiere convertir.
            on_page_start: Callback opcional invocado al comenzar cada página.

        Returns:
            ``True`` si se genero un Markdown nuevo.
        """
        if doc.markdown_content:
            if doc.status != "indexado":
                doc.status = STATUS_WITH_MARKDOWN
            doc.error_message = None
            db.session.commit()
            return False

        if self.markdown_converter is None:
            raise RuntimeError("No hay conversor de Markdown configurado.")

        pdf_path = Path(doc.path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF no existe en contenedor: {pdf_path}")

        markdown_content = self.markdown_converter(pdf_path, on_page_start=on_page_start)
        if not markdown_content:
            raise RuntimeError(f"No se pudo guardar el Markdown generado para {doc.nombre}.")
        doc.markdown_content = markdown_content
        if doc.status != "indexado":
            doc.status = STATUS_WITH_MARKDOWN
        doc.error_message = None

        db.session.commit()
        return True

    def _collect_pending_markdown_docs(self) -> tuple[list[Documento], int]:
        """Separa los documentos pendientes de los ya resueltos.

        Returns:
            Una tupla con la lista de pendientes y el Número de omitidos.
        """
        docs = Documento.query.order_by(Documento.modified_at.desc()).all()
        pending_docs: list[Documento] = []
        skipped = 0
        changed_existing = False

        for doc in docs:
            if doc.markdown_content:
                if doc.status not in {"indexado", STATUS_WITH_MARKDOWN}:
                    doc.status = STATUS_WITH_MARKDOWN
                    doc.error_message = None
                    changed_existing = True
                skipped += 1
                continue

            pending_docs.append(doc)

        if changed_existing:
            db.session.commit()

        return pending_docs, skipped

    def _build_markdown_page_callback(self, on_page_start, doc_index: int, total_docs: int):
        """Crea el callback de progreso por página para Markdown.

        Args:
            on_page_start: Callback externo de progreso por página.
            doc_index: Posicion del documento actual.
            total_docs: Número total de documentos del lote.

        Returns:
            Un callback listo para el conversor o ``None``.
        """
        if on_page_start is None:
            return None

        def page_callback(page: int, total_pages: int) -> None:
            on_page_start(doc_index, total_docs, page, total_pages)

        return page_callback

    def _process_pending_markdown_doc(
        self,
        doc: Documento,
        doc_index: int,
        total_docs: int,
        on_current_doc=None,
        on_page_start=None,
    ) -> str:
        """Procesa un documento pendiente dentro del lote Markdown.

        Args:
            doc: Documento que se va a procesar.
            doc_index: Posicion del documento actual.
            total_docs: Número total de documentos del lote.
            on_current_doc: Callback opcional al iniciar un documento.
            on_page_start: Callback opcional al iniciar una página.

        Returns:
            ``converted``, ``skipped`` o ``failed`` segun el resultado.
        """
        if on_current_doc:
            on_current_doc(doc.nombre)

        page_callback = self._build_markdown_page_callback(on_page_start, doc_index, total_docs)

        try:
            converted = self.convert_document_to_markdown(doc, on_page_start=page_callback)
            return "converted" if converted else "skipped"
        except JobCancelledError:
            raise
        except Exception:
            db.session.rollback()
            return "failed"

    def _prepare_document_for_vector_update(self, doc: Documento) -> Path:
        """Prepara un documento para reindexarlo en la base vectorial.

        Args:
            doc: Documento que se va a reindexar.

        Returns:
            La ruta del PDF listo para ser indexado.
        """
        doc.status = "procesado"
        doc.error_message = None
        db.session.commit()

        pdf_path = Path(doc.path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF no existe en contenedor: {pdf_path}")

        try:
            self.delete_chunks(doc.nombre)
        except Exception:
            pass

        chunk_ids_subq = db.session.query(Chunk.id).filter(Chunk.document_id == doc.id).subquery()

        ConsultaChunk.query.filter(
            ConsultaChunk.chunk_id.in_(chunk_ids_subq)
        ).delete(synchronize_session=False)
        db.session.commit()

        Embedding.query.filter(
            Embedding.chunk_id.in_(chunk_ids_subq)
        ).delete(synchronize_session=False)
        db.session.commit()

        Chunk.query.filter(Chunk.document_id == doc.id).delete(synchronize_session=False)
        db.session.commit()
        return pdf_path

    def _index_vector_document(self, doc: Documento, index_pdf) -> int:
        """Indexa un documento y actualiza su estado y Número de chunks.

        Args:
            doc: Documento que se va a indexar.
            index_pdf: Función que genera los chunks vectoriales.

        Returns:
            El Número de chunks indexados para el documento.
        """
        pdf_path = self._prepare_document_for_vector_update(doc)
        vector_docs = index_pdf(
            pdf_path,
            document_id=doc.id,
            numero_expediente=doc.numero_expediente,
            tipo_documento=doc.tipo_documento,
        )
        if not vector_docs:
            raise RuntimeError("index_pdf devolvió 0 chunks (PDF sin texto o ruta inválida)")

        update_sql(doc, vector_docs)
        db.session.commit()

        doc.chunks = len(vector_docs)
        doc.status = "indexado"
        db.session.commit()
        return len(vector_docs)

    def _mark_vector_update_failed(self, doc: Documento, error: Exception) -> None:
        """Marca como fallida la actualizacion vectorial de un documento.

        Args:
            doc: Documento que ha fallado.
            error: Excepcion que explica el fallo.

        Returns:
            None.
        """
        db.session.rollback()
        doc.status = "fallido"
        doc.error_message = str(error)
        db.session.commit()

    def convert_pending_to_markdown(
        self,
        on_progress=None,
        on_current_doc=None,
        should_cancel=None,
        on_page_start=None,
    ) -> dict[str, int]:
        """Convierte a Markdown todos los documentos pendientes.

        Args:
            on_progress: Callback opcional para informar del progreso total.
            on_current_doc: Callback opcional al comenzar un documento.
            should_cancel: Callback opcional para comprobar cancelacion.
            on_page_start: Callback opcional al comenzar una página.

        Returns:
            Un resumen con convertidos, fallidos, omitidos y total.
        """
        converted = 0
        failed = 0
        pending_docs, skipped = self._collect_pending_markdown_docs()

        total = len(pending_docs)
        if on_progress:
            on_progress(0, total)

        for i, doc in enumerate(pending_docs, start=1):
            if should_cancel and should_cancel():
                raise JobCancelledError("Conversión a Markdown cancelada por el usuario.")
            result = self._process_pending_markdown_doc(
                doc,
                i,
                total,
                on_current_doc=on_current_doc,
                on_page_start=on_page_start,
            )
            if result == "converted":
                converted += 1
            elif result == "skipped":
                skipped += 1
            else:
                failed += 1

            if on_progress:
                on_progress(i, total)

        return {
            "converted": converted,
            "failed": failed,
            "skipped": skipped,
            "total": total,
        }

    def update_vector_db(self, on_progress=None, on_current_doc=None, should_cancel=None) -> dict[str, int]:
        """Actualiza la base de datos vectorial con los documentos pendientes.

        Args:
            on_progress: Callback opcional para informar del progreso total.
            on_current_doc: Callback opcional al comenzar un documento.
            should_cancel: Callback opcional para comprobar cancelacion.

        Returns:
            Un resumen con total, indexados y fallidos.
        """
        from .rag.PrototipoRAG import index_pdf

        self.purge_missing_files()
        docs = Documento.query.filter(Documento.status.in_(["cargado", STATUS_WITH_MARKDOWN, "fallido"])).all()

        total = len(docs)
        indexed = 0
        failed = 0
        if on_progress:
            on_progress(0, total)

        for i, doc in enumerate(docs, start=1):
            if should_cancel and should_cancel():
                raise JobCancelledError("Actualización cancelada por el usuario.")
            if on_current_doc:
                on_current_doc(doc.nombre)

            try:
                self._index_vector_document(doc, index_pdf)
                indexed += 1
                if on_progress:
                    on_progress(i, total)

            except Exception as ex:
                self._mark_vector_update_failed(doc, ex)
                failed += 1

        return {"total": total, "indexed": indexed, "failed": failed}


def update_sql(doc, vector_docs) -> None:
    """Sincroniza chunks y embeddings en SQL a partir de documentos vectoriales.

    Args:
        doc: Documento al que pertenecen los chunks indexados.
        vector_docs: Coleccion de documentos vectoriales generados al indexar.

    Returns:
        None.
    """
    from .entities.chunk import Chunk
    from .entities.embedding import Embedding
    from .extensions import db
    from .rag.PrototipoRAG import embedding_model

    for vd in vector_docs:
        qid = str(vd.id)
        meta = vd.metadata or {}
        seg = int(meta.get("segment_index", -1))
        sha = (meta.get("sha256") or meta.get("doc_sha256") or "").strip()
        numero_expediente = meta.get("numero_expediente")
        tipo_documento = meta.get("tipo_documento")

        if seg < 0 or not sha:
            continue

        c = Chunk.query.filter_by(document_id=doc.id, doc_sha256=sha, segment_index=seg).first()
        if c is None:
            c = Chunk(
                document_id=doc.id,
                qdrant_point_id=qid,
                segment_index=seg,
                doc_sha256=sha,
                n_chars=len(vd.content or ""),
                n_tokens=None,
                numero_expediente=numero_expediente,
                tipo_documento=tipo_documento,
            )
            db.session.add(c)
            db.session.flush()
        else:
            c.qdrant_point_id = qid
            c.n_chars = len(vd.content or "")
            c.numero_expediente = numero_expediente
            c.tipo_documento = tipo_documento

        exists = Embedding.query.filter_by(chunk_id=c.id, model_id=embedding_model.model_id).first()
        if not exists:
            e = Embedding(
                chunk_id=c.id,
                model_id=embedding_model.model_id,
                embedding_size=embedding_model.embedding_size,
                distance="cosine",
            )
            db.session.add(e)
