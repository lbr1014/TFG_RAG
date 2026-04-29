"""
Autora: Lydia Blanco Ruiz
Utilidades compartidas por los modelos que representan procesos asíncronos.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


MADRID_TZ = ZoneInfo("Europe/Madrid")
JOB_MESSAGE_MAX_LENGTH = 255


class JobStateMixin:
    """
    Comportamiento común de los estados de trabajos en segundo plano.
    """

    @staticmethod
    def fit_message(message: str | None, max_length: int = JOB_MESSAGE_MAX_LENGTH) -> str | None:
        """
        Ajusta un mensaje al tamaño máximo permitido, truncando si es necesario.
        
        Args:
            message (str | None): El mensaje a ajustar.
            max_length (int): La longitud máxima permitida para el mensaje.
        """
        if message is None:
            return None
        if len(message) <= max_length:
            return message
        if max_length <= 3:
            return message[:max_length]
        return message[: max_length - 3].rstrip() + "..."

    @staticmethod
    def now() -> datetime:
        """
        Devuelve la fecha y hora actual en la zona de Madrid.
        
        Returns:
            datetime: Fecha y hora actual en la zona de Madrid.
        """
        return datetime.now(MADRID_TZ)

    def set_message(self, message: str | None) -> None:
        """
        Establece el mensaje del estado, ajustándolo al tamaño máximo permitido.
        
        Args:
            message (str | None): El mensaje a establecer.
        """
        if hasattr(self, "message"):
            self.message = self.fit_message(message)

    def set_progress(self, current: int | float, total: int) -> None:
        """
        Establece el progreso del estado como un porcentaje calculado a partir de los valores actuales y totales.
        
        Args:
            current (int | float): El valor actual del progreso.
            total (int): El valor total del progreso.
        """
        self.progress = int((current / total) * 100) if total and total > 0 else 100

    def should_cancel(self) -> bool:
        """
        Indica si se ha solicitado la cancelación del trabajo.
        
        Returns:
            bool: True si se ha solicitado la cancelación, False en caso contrario.
        """
        return bool(self.cancel_requested)

    def mark_running(self, *, progress: int = 0, message: str | None = None) -> None:
        """
        Marca el trabajo como en ejecución.
        
        Args:
            progress (int, optional): El progreso inicial. Defaults to 0.
            message (str | None, optional): El mensaje inicial. Defaults to None.
        """
        self.status = "running"
        self.started_at = self.now()
        self.progress = progress
        self.error = None
        self.set_message(message)

    def mark_cancelled(self, *, message: str | None = None, clear_error: bool = True) -> None:
        """
        Marca el trabajo como cancelado.
        
        Args:
            message (str | None, optional): El mensaje de cancelación. Defaults to None.
            clear_error (bool, optional): Si se debe borrar el error. Defaults to True.
        """
        self.status = "cancelled"
        if clear_error and hasattr(self, "error"):
            self.error = None
        self.set_message(message)
        self.finished_at = self.now()

    def mark_done(self, *, progress: int = 100, message: str | None = None) -> None:
        """
        Marca el trabajo como finalizado exitosamente.
        
        Args:
            progress (int, optional): El progreso final. Defaults to 100.
            message (str | None, optional): El mensaje final. Defaults to None.
        """
        
        self.status = "done"
        self.progress = progress
        self.set_message(message)
        self.finished_at = self.now()

    def mark_failed(self, error: Exception | str, *, message: str | None = None) -> None:
        """
        Marca el trabajo como fallido, registrando el error.
        
        Args:            
            error (Exception | str): El error que causó la falla.
            message (str | None, optional): El mensaje de error. Defaults to None.
        """
        self.status = "failed"
        self.error = str(error)
        self.set_message(message)
        self.finished_at = self.now()
