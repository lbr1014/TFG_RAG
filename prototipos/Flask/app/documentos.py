from __future__ import annotations

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Iterable, Optional
from werkzeug.utils import secure_filename
import hashlib

from .extensions  import db
from .chunk import Chunk
from .embedding import Embedding
from .rag.PrototipoRAG import index_pdf, embedding_model

ALLOWED_EXT = {".pdf"}

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


class DocumentosService:
    def __init__(
        self,
        docs_dir: Path,
        index_pliegos_dir,              
        delete_chunks,              
        count_chunks,               
    ):
        self.docs_dir = docs_dir
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        self.index_pliegos_dir = index_pliegos_dir
        self.delete_chunks = delete_chunks
        self.count_chunks = count_chunks

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
            self._upsert_from_path(p, status="cargado")
        db.session.commit()
        
        self.purge_missing_files()
        
    def purge_missing_files(self) -> int:
        """
        Borra de SQL y Qdrant los registros cuyo PDF ya no existe en disco.
        """
        deleted = 0
        for doc in Documento.query.all():
            if not Path(doc.path).exists():
                try:
                    self.delete_chunks(doc.nombre) 
                except Exception:
                    pass
                db.session.delete(doc)
                deleted += 1

        if deleted:
            db.session.commit()
        return deleted

        
    def _upsert_from_path(self, p: Path, status: str) -> None:
        stat = p.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, ZoneInfo("Europe/Madrid"))

        rel_path = str(p)
        file_hash = sha256_file(p)
        
        doc = Documento.query.filter_by(path=rel_path).first()
        if not doc:
            doc = Documento(
                nombre=p.name,
                path=rel_path,
                size_bytes=stat.st_size,
                modified_at=mtime,
                chunks=0,
                hash=file_hash,
                status=status,
                error_message=None,
            )
            db.session.add(doc)
            
        else:
            
            doc.nombre = p.name
            doc.size_bytes = stat.st_size
            doc.modified_at = mtime
            doc.hash = file_hash
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
        
        # Borra fichero
        try:
            pdf_path = Path(doc.path)
            if pdf_path.exists():
                pdf_path.unlink()
        except Exception:
            pass
        
        # Borrra base de datos        
        if doc:
            db.session.delete(doc)
            db.session.commit()        

    def update_vector_db(self) -> None:
        """
        Indexa y acctualiza el estado y los chunks en la base de datos.
        """
        docs = Documento.query.filter(Documento.status.in_(["cargado", "fallido"])).all()

        for doc in docs:
            try:
                doc.status = "procesado"
                doc.error_message = None
                db.session.commit()
                
                pdf_path = Path(doc.path)

                try:
                    self.delete_chunks(doc.nombre) 
                except Exception:
                    pass
                
                Chunk.query.filter_by(document_id=doc.id).delete()
                db.session.commit()
                
                vector_docs = index_pdf(pdf_path, document_id=doc.id)
                
                # Inserta metadatos Chunk + Embedding en SQL
                for vd in vector_docs:
                    seg = int((vd.metadata or {}).get("segment_index", -1))
                    sha = (vd.metadata or {}).get("sha256", "")
                    content = vd.content or ""

                    c = Chunk(
                        document_id=doc.id,
                        qdrant_point_id=str(vd.id),
                        segment_index=seg,
                        doc_sha256=sha,
                        n_chars=len(content),
                        n_tokens=None,   # si quieres, luego calculas tokens
                    )
                    db.session.add(c)
                    db.session.flush()
                    
                    e = Embedding(
                        chunk_id=c.id,
                        model_id=embedding_model.model_id,
                        embedding_size=embedding_model.embedding_size,
                        distance="cosine",
                    )
                    db.session.add(e)

                db.session.commit()
                    
                doc.chunks = Chunk.query.filter_by(document_id=doc.id).count()
                doc.status = "indexado"
                db.session.commit()
                
            except Exception as ex:
                doc.status = "fallido"
                doc.error_message = str(ex)
                db.session.commit()
                raise
