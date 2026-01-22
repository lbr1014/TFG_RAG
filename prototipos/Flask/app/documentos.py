from __future__ import annotations

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Iterable, List, Dict, Optional
from werkzeug.utils import secure_filename
import hashlib

from .extensions  import db

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

    def sanitize_filename(self, filename: str) -> str:
        return secure_filename(filename or "")

    def resolve_pdf_path(self, filename: str) -> Path:
        safe = self.sanitize_filename(filename)
        if not safe:
            raise ValueError("Nombre de archivo inválido")
        if Path(safe).suffix.lower() not in self.allowed_ext:
            raise ValueError("Extensión no permitida")
        return self.docs_dir / safe

    def list_documents(self) -> List[Documento]:
        docs: List[Documento] = []
        for p in sorted(self.docs_dir.glob("*.pdf")):
            stat = p.stat()
            name = p.name
            try:
                chunks = int(self.count_chunks(name))
            except Exception:
                chunks = 0

            docs.append(
                Documento(
                    name=name,
                    size_bytes=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    chunks=chunks,
                )
            )

        docs.sort(key=lambda d: d.modified, reverse=True)
        return docs
    
    def list_documents_paginated(self, page: int, per_page: int):
        return Documento.query.order_by(Documento.modified_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    def save_uploads(self, files: Iterable) -> None:
        """
        Guarda PDFs en el disco y los metadatos en la base de datos.
        """

        for f in files:
            if not f or not f.nombre:
                continue
            
            nombre=secure_filename(f.nombre)
            
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
        for p in sorted(self._base.glob("*.pdf")):
            self._upsert_from_path(p, status="cargado")
        db.session.commit()
        
    def _upsert_from_path(self, p: Path, status: str) -> None:
        stat = p.stat()
        now = datetime.now(ZoneInfo("Europe/Madrid"))

        rel_path = str(p)
        file_hash = sha256_file(p)
        
        doc = Documento.query.filter_by(path=rel_path).first()
        if not doc:
            doc = Documento(
                filename=p.name,
                path=rel_path,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, ZoneInfo("Europe/Madrid")),
                chunks_count=0,
                sha256=file_hash,
                status=status,
                created_at=now,
                updated_at=now,
            )
            db.session.add(doc)
            
        else:
            
            doc.filename = p.name
            doc.size_bytes = stat.st_size
            doc.modified_at = datetime.fromtimestamp(stat.st_mtime, ZoneInfo("Europe/Madrid"))
            doc.sha256 = file_hash
            doc.status = status
            doc.updated_at = now

    def delete_document(self, nombre: str) -> None:
        """
        Borra en Qdrant, en el disco y en la base de datos.
        """
        pdf_path = self.resolve_pdf_path(nombre)
        safe_name = pdf_path.name

        if not pdf_path.exists():
            raise FileNotFoundError("El archivo no existe")

        # Borra chunks en Qdrant
        self.delete_chunks(safe_name)
        
        # Borra fichero
        pdf_path.unlink()
        
        # Borrra base de datos
        doc = Documento.query.filter_by(filename=nombre, path=str(pdf_path)).first()
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
                doc.updated_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
                
                self._index_pliegos_dir(str(self.docs_dir))

                try:
                    doc.chunk_count = int(self.count_chunks(doc.name) or 0)
                except Exception:
                    doc.chunk_count = 0
                    
                doc.status = "indexado"
                doc.updated_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
                
            except Exception as ex:
                doc.status = "fallido"
                doc.error_message = str(ex)
                doc.updated_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
                raise
