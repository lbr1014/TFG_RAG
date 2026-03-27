from __future__ import annotations

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Iterable, Optional
from werkzeug.utils import secure_filename
import hashlib
import re
import unicodedata

from .extensions  import db
from .chunk import Chunk
from .embedding import Embedding
from .consultaChunk import ConsultaChunk

ALLOWED_EXT = {".pdf"}


class JobCancelledError(RuntimeError):
    pass

class Documento(db.Model):
    __tablename__ = "documents"
     
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(255), nullable=False,  index=True)
    path = db.Column(db.String(500), unique=True, nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    modified_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    chunks = db.Column(db.Integer, nullable=False,  default=0)
    hash = db.Column(db.String(100),  nullable=False, index=True)
    status = db.Column(db.String(25), nullable=False,default="cargado", index=True)
    error_message = db.Column(db.Text, nullable=True)
    numero_expediente = db.Column(db.String(255), nullable=True, index=True)
    tipo_documento = db.Column(db.String(30), nullable=True, index=True)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        now = datetime.now(ZoneInfo("Europe/Madrid"))
        if not self.modified_at:
            self.modified_at = now
    
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return normalized.lower().strip()


def infer_document_metadata_from_filename(filename: str) -> tuple[str | None, str | None]:
    stem = Path(filename or "").stem
    if "__" not in stem:
        return None, None

    expediente_part, doc_part = stem.split("__", 1)
    expediente = expediente_part.strip() or None

    match = re.match(r"(?P<doc>.+?)_(?P<index>\d+)$", doc_part.strip())
    if match:
        raw_doc_name = match.group("doc").strip()
    else:
        raw_doc_name = doc_part.strip()

    normalized_doc_name = _normalize_text(raw_doc_name).replace("_", " ")
    if "clausulas administrativas" in normalized_doc_name or "administrativ" in normalized_doc_name:
        return expediente, "administrativo"
    if "prescripciones tecnicas" in normalized_doc_name or "tecnic" in normalized_doc_name:
        return expediente, "tecnico"

    return expediente, None


class DocumentosService:
    def __init__(
        self,
        docs_dir: Path,
        index_pliegos_dir,              
        delete_chunks,              
        count_chunks,
        markdown_dir: Path | None = None,
        markdown_converter=None,
    ):
        self.docs_dir = docs_dir
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir = (markdown_dir or (self.docs_dir / "markdown"))
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

        self.index_pliegos_dir = index_pliegos_dir
        self.delete_chunks = delete_chunks
        self.count_chunks = count_chunks
        self.markdown_converter = markdown_converter

    def filename(self, filename: str) -> str:
        return secure_filename(filename or "")
    
    def resolve_pdf_path(self, filename: str) -> Path:
        safe = self.filename(filename)
        if not safe:
            raise ValueError("Nombre de archivo inválido")
        if Path(safe).suffix.lower() not in ALLOWED_EXT:
            raise ValueError("Extensión no permitida")
        return self.docs_dir / safe
    
    def list_documents_paginated(self, page: int, per_page: int):
        return Documento.query.order_by(Documento.modified_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    def markdown_path_for_filename(self, filename: str) -> Path:
        safe = self.filename(filename)
        if not safe:
            raise ValueError("Nombre de archivo inválido")
        return self.markdown_dir / f"{Path(safe).stem}.md"

    def markdown_path_for_doc(self, doc: Documento) -> Path:
        return self.markdown_path_for_filename(doc.nombre)

    def has_markdown(self, doc: Documento) -> bool:
        return self.markdown_path_for_doc(doc).exists()

    def get_markdown_status_map(self, docs: Iterable[Documento]) -> dict[int, bool]:
        return {doc.id: self.has_markdown(doc) for doc in docs}

    def count_pending_markdown(self, docs: Iterable[Documento] | None = None) -> int:
        if docs is None:
            docs = Documento.query.all()
        return sum(1 for doc in docs if not self.has_markdown(doc))

    def save_uploads(self, files: Iterable) -> None:
        """
        Guarda PDFs en el disco y los metadatos en la base de datos.
        """

        for f in files:
            if not f or not f.filename:
                continue
            
            nombre=secure_filename(f.filename)
            
            if not nombre.lower().endswith(".pdf"):
                continue

            dest = self.docs_dir / nombre
            f.save(dest)

            self._upsert_from_path(dest, status="cargado")
        
        db.session.commit()

    def sync_from_folder(self) -> None:
        """
        Escanea el directorio y actualiza los registros de la base de datos.
        """
        for p in sorted(self.docs_dir.glob("*.pdf")):
            self._upsert_from_path(p, status=None)
        db.session.commit()
        
        self.purge_missing_files()
        
    def purge_missing_files(self) -> int:
        """
        Borra de SQL y Qdrant los registros cuyo PDF ya no existe en disco.
        """
        deleted = 0
        for doc in Documento.query.all():
            if not Path(doc.path).exists():
                self.delete_markdown_file(doc)
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
        stat = p.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, ZoneInfo("Europe/Madrid"))

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
                status=status or "cargado",
                error_message=None,
                numero_expediente=numero_expediente,
                tipo_documento=tipo_documento,
            )
            db.session.add(doc)
            
        else:
            
            doc.nombre = p.name
            doc.size_bytes = stat.st_size
            doc.modified_at = mtime
            doc.hash = file_hash
            doc.numero_expediente = numero_expediente
            doc.tipo_documento = tipo_documento
            if status is not None:
                doc.status = status
                doc.error_message = None

    def delete_document(self, doc_id: int) -> None:
        """
        Borra en Qdrant, en el disco y en la base de datos.
        """
        doc = Documento.query.get(doc_id)
        if not doc:
            return
        safe_name = doc.nombre
        # Borra chunks en Qdrant
        try: 
            self.delete_chunks(safe_name)
        except Exception:
            pass

        self.delete_document_relations(doc)
        
        # Borra fichero
        try:
            pdf_path = Path(doc.path)
            if pdf_path.exists():
                pdf_path.unlink()
        except Exception:
            pass

        self.delete_markdown_file(doc)
        
        # Borrra base de datos        
        if doc:
            db.session.delete(doc)
            db.session.commit()

    def delete_markdown_file(self, doc: Documento) -> None:
        try:
            md_path = self.markdown_path_for_doc(doc)
            if md_path.exists():
                md_path.unlink()
        except Exception:
            pass

    def delete_document_relations(self, doc: Documento) -> None:
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
        if self.has_markdown(doc):
            return False
        if self.markdown_converter is None:
            raise RuntimeError("No hay conversor de Markdown configurado.")

        pdf_path = Path(doc.path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF no existe en contenedor: {pdf_path}")

        self.markdown_converter(pdf_path, self.markdown_dir, on_page_start=on_page_start)
        return True

    def convert_pending_to_markdown(self, on_progress=None, on_current_doc=None, should_cancel=None, on_page_start=None) -> dict[str, int]:
        converted = 0
        skipped = 0

        docs = Documento.query.order_by(Documento.modified_at.desc()).all()
        total = len(docs)
        if on_progress:
            on_progress(0, total)

        for i, doc in enumerate(docs, start=1):
            if should_cancel and should_cancel():
                raise JobCancelledError("Conversión a Markdown cancelada por el usuario.")
            if on_current_doc:
                on_current_doc(doc.nombre)
            page_callback = None
            if on_page_start is not None:
                def page_callback(page: int, total_pages: int, doc_index=i, total_docs=total):
                    on_page_start(doc_index, total_docs, page, total_pages)

            if self.convert_document_to_markdown(doc, on_page_start=page_callback):
                converted += 1
            else:
                skipped += 1
            if on_progress:
                on_progress(i, total)

        return {
            "converted": converted,
            "skipped": skipped,
            "total": total,
        }

    def update_vector_db(self, on_progress=None, on_current_doc=None, should_cancel=None) -> dict[str, int]:
        """
        Indexa y acctualiza el estado y los chunks en la base de datos.
        """
        from .rag.PrototipoRAG import index_pdf

        self.purge_missing_files()
        docs = Documento.query.filter(Documento.status.in_(["cargado", "fallido"])).all()

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
                
                # ids de chunks del documento
                chunk_ids_subq = db.session.query(Chunk.id).filter(Chunk.document_id == doc.id).subquery()

                # borrar embeddings cuyo chunk_id esté en esos chunks
                ConsultaChunk.query.filter(
                    ConsultaChunk.chunk_id.in_(chunk_ids_subq)
                ).delete(synchronize_session=False)
                db.session.commit()

                Embedding.query.filter(Embedding.chunk_id.in_(chunk_ids_subq)).delete(synchronize_session=False)
                db.session.commit()

                # borrar chunks del documento
                Chunk.query.filter(Chunk.document_id == doc.id).delete(synchronize_session=False)
                db.session.commit()

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
                indexed += 1
                if on_progress:
                    on_progress(i, total)

            except Exception as ex:
                db.session.rollback()
                doc.status = "fallido"
                doc.error_message = str(ex)
                db.session.commit()
                failed += 1

        return {"total": total, "indexed": indexed, "failed": failed}
                
def update_sql(doc, vector_docs) -> None:
    from .rag.PrototipoRAG import embedding_model
    from .extensions import db
    from .chunk import Chunk
    from .embedding import Embedding

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
