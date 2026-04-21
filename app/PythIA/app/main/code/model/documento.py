"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que representa los documentos PDF gestionados por la aplicación.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.extensions import db

MADRID_TZ = ZoneInfo("Europe/Madrid")


class Documento(db.Model):
    """Modelo de persistencia para los documentos gestionados por la aplicación.

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

    def __init__(self, **kwargs):
        """Inicializa un documento y asegura la fecha de modificación.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.modified_at:
            self.modified_at = datetime.now(MADRID_TZ)
