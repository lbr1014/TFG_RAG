"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que representa una consulta realizada al sistema RAG.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import JSON

from app.main.code.extensions import db
from app.main.code.model.consulta_chunk import ConsultaChunk


class Consulta(db.Model):
    """
    Consulta realizada por un usuario y respuesta generada por el sistema.

    Attributes:
        id: Identificador interno de la consulta.
        user_id: Identificador del usuario que hizo la pregunta.
        user: Usuario asociado a la consulta.
        pregunta: Texto enviado por el usuario.
        respuesta: Respuesta generada por el sistema RAG.
        fragmentos: Fragmentos recuperados y guardados junto a la respuesta.
        tiempo_respuestas: Tiempo de generación de la respuesta, en segundos.
        created_at: Fecha y hora de creación de la consulta.
    """

    __tablename__ = "consultas"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user = db.relationship(
        "User",
        backref=db.backref("consultas", lazy=True, cascade="all, delete-orphan", passive_deletes=True),
        passive_deletes=True,
    )
    pregunta = db.Column(db.Text, nullable=False)
    respuesta = db.Column(db.Text, nullable=False)
    fragmentos = db.Column(JSON, nullable=False, default=list)
    tiempo_respuestas = db.Column(db.Float, nullable=False)
    execution_device = db.Column(db.String(10), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    def __init__(self, **kwargs):
        """
        Inicializa la consulta con fecha de creación por defecto.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))

    @classmethod
    def from_rag_result(cls, *, user_id: int, question: str, data: dict, elapsed: float) -> Consulta:
        """
        Crea una consulta y sus enlaces a chunks a partir de una respuesta RAG.
        
        Args:
            user_id (int): Identificador del usuario que hizo la pregunta.
            question (str): Texto de la pregunta realizada.
            data (dict): Resultado generado por el sistema RAG, incluyendo respuesta y fragmentos recuperados.
            elapsed (float): Tiempo que tardó el sistema en generar la respuesta, en segundos.
            
        Returns:
            Consulta: Objeto Consulta SQLAlchemy creado a partir de los datos proporcionados.
        """
        from app.main.code.model.chunk import Chunk

        retrieved = data.get("retrieved", []) or []
        top_retrieved = retrieved[:10]
        chunk_links: list[tuple[dict, Chunk]] = []
        fragmentos: list[dict] = []

        for item in top_retrieved:
            chunk_obj = Chunk.find_from_retrieved_item(item)
            if chunk_obj is not None:
                chunk_links.append((item, chunk_obj))
            fragmentos.append(Chunk.build_fragment_from_retrieved_item(item, chunk_obj))

        consulta = cls(
            user_id=int(user_id),
            pregunta=question,
            respuesta=str(data.get("answer", "")),
            fragmentos=fragmentos,
            tiempo_respuestas=float(elapsed),
            execution_device=str(data.get("execution_device") or "").upper() or None,
        )
        db.session.add(consulta)
        db.session.flush()

        for item, chunk_obj in chunk_links:
            db.session.add(
                ConsultaChunk(
                    consulta_id=int(consulta.id),
                    chunk_id=int(chunk_obj.id),
                    similitud=float(item.get("similitud", 0.0)),
                    ranking=int(item.get("ranking", 0)),
                )
            )

        return consulta
    
