"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que representa los documentos PDF gestionados por la aplicación.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.main.code.extensions import db

MADRID_TZ = ZoneInfo("Europe/Madrid")
STATUS_WITH_MARKDOWN = "con markdown"

def _normalize_document_text(value: str) -> str:
    """
    Normaliza un texto de documento para facilitar la inferencia de tipo documental.
    
    Args:
        value (str): El texto a normalizar.
    
    Returns:
        str: El texto normalizado.
    """
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return normalized.lower().strip()


class Documento(db.Model):
    """
    Modelo de persistencia para los documentos gestionados por la aplicación.

    Attributes:
        id: Identificador interno del documento.
        nombre: Nombre del archivo PDF.
        path: Ruta donde se almacena el archivo.
        size_bytes: Tamaño del archivo en bytes.
        modified_at: Fecha de modificación del archivo.
        chunks: Número de fragmentos indexados.
        hash: Hash SHA-256 del archivo.
        status: Estado de procesamiento del documento.
        markdown_content: Contenido Markdown generado a partir del PDF.
        error_message: Mensaje de error asociado al documento.
        numero_expediente: Número de expediente inferido del nombre.
        tipo_documento: Tipo de documento inferido.
    """

    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(255), nullable=False, index=True)
    path = db.Column(db.String(500), unique=True, nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    modified_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    chunks = db.Column(db.Integer, nullable=False, default=0)
    hash = db.Column(db.String(100), nullable=False, index=True)
    status = db.Column(db.String(25), nullable=False, default="cargado", index=True)
    markdown_content = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    numero_expediente = db.Column(db.String(255), nullable=True, index=True)
    tipo_documento = db.Column(db.String(30), nullable=True, index=True)

    def __init__(self, **kwargs) -> None:
        """
        Inicializa un documento y asegura la fecha de modificación.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.modified_at:
            self.modified_at = datetime.now(MADRID_TZ)

    @staticmethod
    def infer_metadata_from_filename(filename: str) -> tuple[str | None, str | None]:
        """
        Infierne expediente y tipo documental desde el nombre del PDF.

        Args:
            filename (str): Nombre del archivo PDF.

        Returns:
            tuple[str | None, str | None]: Tupla con el número de expediente y el tipo de documento inferido.
        """
        stem = Path(filename or "").stem
        if "__" not in stem:
            return None, None

        expediente_part, doc_part = stem.split("__", 1)
        expediente = expediente_part.strip() or None

        match = re.match(r"(?P<doc>.+?)_(?P<index>\d+)$", doc_part.strip())
        raw_doc_name = match.group("doc").strip() if match else doc_part.strip()

        normalized_doc_name = _normalize_document_text(raw_doc_name).replace("_", " ")
        if "clausulas administrativas" in normalized_doc_name or "administrativ" in normalized_doc_name:
            return expediente, "administrativo"
        if "prescripciones tecnicas" in normalized_doc_name or "tecnic" in normalized_doc_name:
            return expediente, "tecnico"

        return expediente, None

    @property
    def has_markdown(self) -> bool:
        """
        Indica si el documento tiene contenido Markdown persistido.
        
        Returns:
            bool: True si existe contenido Markdown, False en caso contrario.
        """
        return bool(self.markdown_content)

    def clear_markdown_content(self) -> None:
        """
        Elimina el Markdown asociado al documento.
        """
        self.markdown_content = None

    def clear_error(self) -> None:
        """
        Elimina el mensaje de error asociado al documento.
        """
        self.error_message = None

    @staticmethod
    def status_for_markdown(base_status: str, markdown_content: str | None) -> str:
        """
        Devuelve el estado apropiado cuando existe Markdown.

        Args:
            base_status (str): Estado base.
            markdown_content (str | None): Contenido Markdown.

        Returns:
            str: Estado actualizado.
        """
        if markdown_content and base_status != "indexado":
            return STATUS_WITH_MARKDOWN
        return base_status

    @classmethod
    def from_pdf_path(cls, pdf_path: Path, file_hash: str, modified_at: datetime, status: str = "cargado") -> Documento:
        """
        Crea un documento a partir de los metadatos de un PDF en disco.

        Args:
            pdf_path: Ruta del PDF.
            file_hash: Hash SHA-256 del archivo.
            modified_at: Fecha de modificacion del archivo.
            status: Estado inicial del documento.

        Returns:
            Documento inicializado con metadatos inferidos.
        """
        numero_expediente, tipo_documento = cls.infer_metadata_from_filename(pdf_path.name)
        return cls(
            nombre=pdf_path.name,
            path=str(pdf_path),
            size_bytes=pdf_path.stat().st_size,
            modified_at=modified_at,
            chunks=0,
            hash=file_hash,
            markdown_content=None,
            status=status,
            error_message=None,
            numero_expediente=numero_expediente,
            tipo_documento=tipo_documento,
        )

    def refresh_file_metadata(self, pdf_path: Path, file_hash: str, modified_at: datetime) -> bool:
        """
        Actualiza metadatos del archivo y devuelve si cambió el hash.
        
        Args:            
            pdf_path (Path): Ruta al archivo PDF.
            file_hash (str): Nuevo hash del archivo.
            modified_at (datetime): Fecha de modificación del archivo.
            
        Returns:            
            bool: True si el hash cambió, False si es el mismo.
        """
        previous_hash = self.hash
        numero_expediente, tipo_documento = self.infer_metadata_from_filename(pdf_path.name)
        self.nombre = pdf_path.name
        self.size_bytes = pdf_path.stat().st_size
        self.modified_at = modified_at
        self.hash = file_hash
        self.numero_expediente = numero_expediente
        self.tipo_documento = tipo_documento
        return previous_hash != file_hash

    def sync_from_pdf_path(self, pdf_path: Path, file_hash: str, modified_at: datetime, status: str | None = None) -> bool:
        """
        Sincroniza metadatos y estado del documento desde un PDF en disco.

        Args:
            pdf_path: Ruta del PDF.
            file_hash: Hash SHA-256 del archivo.
            modified_at: Fecha de modificacion del archivo.
            status: Estado base opcional que debe asignarse.

        Returns:
            ``True`` si el hash del PDF cambio.
        """
        hash_changed = self.refresh_file_metadata(pdf_path, file_hash, modified_at)
        if hash_changed:
            self.clear_markdown_content()

        if status is not None:
            self.status = self.status_for_markdown(status, self.markdown_content)
            self.clear_error()
        else:
            self.sync_existing_markdown_status()

        return hash_changed

    def sync_existing_markdown_status(self) -> bool:
        """
        Ajusta el estado si el documento ya tiene Markdown y no esta indexado.

        Returns:
            ``True`` si el documento fue modificado.
        """
        if self.markdown_content and self.status != "indexado":
            self.status = STATUS_WITH_MARKDOWN
            self.clear_error()
            return True
        return False

    def mark_markdown_available(self, markdown_content: str | None = None) -> None:
        """
        Guarda o reconoce Markdown disponible y limpia errores previos.

        Args:
            markdown_content: Nuevo contenido Markdown, si se acaba de generar.
        """
        if markdown_content is not None:
            self.markdown_content = markdown_content
        self.sync_existing_markdown_status()
        self.clear_error()

    def mark_vector_processing(self) -> None:
        """
        Marca el documento como listo para reindexacion vectorial.
        """
        self.status = "procesado"
        self.clear_error()

    def mark_indexed(self, chunk_count: int) -> None:
        """
        Marca el documento como indexado.

        Args:
            chunk_count: Numero de chunks generados.
        """
        self.chunks = int(chunk_count)
        self.status = "indexado"
        self.clear_error()

    def mark_failed(self, error: Exception | str) -> None:
        """
        Marca el documento como fallido y registra el error.

        Args:
            error: Excepcion o mensaje del fallo.
        """
        self.status = "fallido"
        self.error_message = str(error)

    def delete_vector_relations(self) -> None:
        """
        Elimina las relaciones SQL de indexacion asociadas al documento.
        """
        from app.main.code.model.chunk import Chunk
        from app.main.code.model.consulta_chunk import ConsultaChunk
        from app.main.code.model.embedding import Embedding

        chunk_ids_subq = db.session.query(Chunk.id).filter(Chunk.document_id == self.id).subquery()

        ConsultaChunk.query.filter(
            ConsultaChunk.chunk_id.in_(chunk_ids_subq)
        ).delete(synchronize_session=False)
        db.session.commit()

        Embedding.query.filter(
            Embedding.chunk_id.in_(chunk_ids_subq)
        ).delete(synchronize_session=False)
        db.session.commit()

        Chunk.query.filter(Chunk.document_id == self.id).delete(synchronize_session=False)
        db.session.commit()

    def sync_vector_metadata(self, vector_docs, embedding_model) -> None:
        """
        Sincroniza chunks y embeddings SQL generados al indexar este documento.
        
        Args:
            vector_docs: Lista de documentos vectoriales generados al indexar el PDF.
            embedding_model: Modelo de embedding utilizado para indexar.
        """
        from app.main.code.model.chunk import Chunk
        from app.main.code.model.embedding import Embedding

        for vd in vector_docs:
            qid = str(vd.id)
            meta = vd.metadata or {}
            seg = int(meta.get("segment_index", -1))
            sha = (meta.get("sha256") or meta.get("doc_sha256") or "").strip()
            numero_expediente = meta.get("numero_expediente")
            tipo_documento = meta.get("tipo_documento")

            if seg < 0 or not sha:
                continue

            chunk = Chunk.query.filter_by(document_id=self.id, doc_sha256=sha, segment_index=seg).first()
            if chunk is None:
                chunk = Chunk(
                    document_id=self.id,
                    qdrant_point_id=qid,
                    segment_index=seg,
                    doc_sha256=sha,
                    n_chars=len(vd.content or ""),
                    n_tokens=None,
                    numero_expediente=numero_expediente,
                    tipo_documento=tipo_documento,
                )
                db.session.add(chunk)
                db.session.flush()
            else:
                chunk.qdrant_point_id = qid
                chunk.n_chars = len(vd.content or "")
                chunk.numero_expediente = numero_expediente
                chunk.tipo_documento = tipo_documento

            embedding = Embedding.query.filter_by(chunk_id=chunk.id).first()
            if embedding is None:
                embedding = Embedding(
                    chunk_id=chunk.id,
                    model_id=embedding_model.model_id,
                    embedding_size=embedding_model.embedding_size,
                    distance="cosine",
                )
                db.session.add(embedding)
            else:
                embedding.model_id = embedding_model.model_id
                embedding.embedding_size = embedding_model.embedding_size
                embedding.distance = "cosine"

