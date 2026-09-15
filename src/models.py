"""
Modelos de datos con Pydantic. Definen el contrato entre la entrada
(anuncios crudos) y la salida (inmuebles evaluados).

NOTA: no usamos `from __future__ import annotations`: FastAPI resuelve
el tipo de retorno de cada endpoint en tiempo real y con anotaciones como
strings salta el error "ForwardRef not fully defined".
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Veredicto(str, Enum):
    LLAMAR_HOY = "LLAMAR HOY"
    REVISAR = "REVISAR"
    DESCARTAR = "DESCARTAR"


class Estado(str, Enum):
    NUEVO = "nuevo"
    ANALIZADO = "analizado"
    CONTACTADO = "contactado"
    DESCARTADO = "descartado"


class AnuncioBase(BaseModel):
    """Un anuncio o alerta recibida desde cualquier fuente."""

    titulo: str = Field(default="", description="Título del anuncio")
    url: Optional[str] = Field(default=None, description="URL enlace (clave de deduplicación)")
    precio: Optional[float] = None
    m2: Optional[float] = None
    zona: Optional[str] = None
    texto: str = Field(default="", description="Cuerpo del anuncio / alerta / correo")
    fuente: str = Field(default="manual", description="Origen: manual, json, csv, n8n...")
    fecha_publicacion: Optional[datetime] = None


class Inmueble(AnuncioBase):
    """Un inmueble ya evaluado por el motor de scoring."""

    id: int = 0
    precio_eur_m2: Optional[float] = None
    alquiler_estimado_mes: Optional[float] = None
    rentabilidad_bruta: Optional[float] = None
    precio_compra_recomendado: Optional[float] = None
    puntuacion: float = 0.0
    veredicto: Veredicto = Veredicto.REVISAR
    estado_crm: Estado = Estado.NUEVO
    banderas_rojas: list = Field(default_factory=list)
    motivos: list = Field(default_factory=list)
    desglose_puntos: dict = Field(default_factory=dict)
    fecha_analisis: datetime = Field(default_factory=datetime.now)
    datos_completos: bool = True

    class Config:
        use_enum_values = True


class StatResumen(BaseModel):
    total: int
    llamar_hoy: int
    revisar: int
    descartar: int
    rentabilidad_media: float
    precio_medio: float
    mejor_oportunidad: Optional[dict] = None


class Filtros(BaseModel):
    texto: str = ""
    veredicto: Optional[str] = None
    rentabilidad_min: Optional[float] = None
    orden: str = "puntuacion_desc"
    zona: Optional[str] = None
    limite: int = 50


class CambioEstado(BaseModel):
    """Body para PATCH del estado CRM de un inmueble."""
    estado: str


class ConfigUpdate(BaseModel):
    """
    Body para POST /api/config. Solo se aplican los campos presentes
    (payload parcial), el resto se mantiene con su valor previo.
    """

    model_config = ConfigDict(extra="ignore")

    zona_objetivo: Optional[str] = None
    precio_min: Optional[float] = None
    precio_max: Optional[float] = None
    precio_max_eur_m2: Optional[float] = None
    alquiler_estimado_eur_m2_mes: Optional[float] = None
    rentabilidad_min: Optional[float] = None
    umbral_llamar_hoy: Optional[float] = None
    pesos: Optional[dict] = None
    # Telegram
    telegram_activo: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    base_url: Optional[str] = None