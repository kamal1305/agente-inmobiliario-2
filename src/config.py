"""
Configuración del agente inmobiliario.

Todas las directrices de inversión y umbrales se pueden ajustar desde un solo
lugar: o bien editando los valores por defecto de InvestmentConfig, o (mejor)
desde el panel ⚙️ del dashboard, que persiste los cambios en data/config.json.

IMPORTANTE: `CONFIG` es un único objeto que NUNCA se rebinda. cargar_config() /
actualizar() mutan sus atributos in place, porque los módulos (`scoring`,
`analizador`, `telegram`) guardan una referencia a él al importar
(`from .config import CONFIG`) y deben ver los cambios en caliente.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Persistencia de la configuración editable desde el panel (data/config.json)
CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "config.json"


@dataclass
class InvestmentConfig:
    """Variables y umbrales por defecto del análisis."""

    zona_objetivo: str = "Jerez de la Frontera"
    precio_min: float = 75_000.0
    precio_max: float = 120_000.0
    precio_max_eur_m2: float = 1_600.0          # tope €/m²
    alquiler_estimado_eur_m2_mes: float = 9.0   # €/m²/mes promedio de la zona
    rentabilidad_min: float = 7.0               # % bruto anual mínimo exigido
    precio_min_compra: float = 0.0              # suelo de precio medio - protección
    deduplicacion_por_url: bool = True
    umbral_llamar_hoy: float = 75.0             # puntuación para veredicto LLAMAR HOY

    # Peso de cada variable en el scoring (total = 100 pts)
    pesos: dict = field(default_factory=lambda: {
        "descuento": 35,
        "rentabilidad": 25,
        "ubicacion": 15,
        "reforma": 10,
        "liquidez": 10,
        "documentacion": 5,
    })

    # Alquiler por microzona (€/m2/mes) - opcional, rompe el valor global
    alquiler_por_zona: dict = field(default_factory=lambda: {
        "centro": 10.5,
        "jerez centro": 10.5,
        "santiago": 9.5,
        "san miguel": 9.0,
        "el puerto": 8.5,
        "la granja": 7.0,
    })

    # ---- Telegram (configurable desde el panel y/o variables de entorno) ----
    telegram_activo: bool = False                # ¿auto-notificar al detectar LLAMAR HOY?
    telegram_bot_token: str = ""                # token del bot creado en @BotFather
    telegram_chat_id: str = ""                 # varios IDs separados por comas o ID de grupo (-100…)
    base_url: str = ""                          # URL pública del panel (para enlazar desde Telegram)


# Claves sensibles que pueden inyectarse por variable de entorno en lugar de
# guardarse en config.json. La ENV PREVALEce sobre el archivo en cada reinicio
# y después de cada guardado: útil en despliegues cloud (Docker/systemd) donde
# el secreto lo gestiona el orquestador, no el panel.
ENV_KEYS = {
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "BASE_URL": "base_url",
}


# Instancia global única (se reconfigura en runtime mutando atributos)
CONFIG = InvestmentConfig()


# ---------------------------------------------------------------------------
# Serialización <-> JSON
# ---------------------------------------------------------------------------

def to_dict(cfg) -> dict:
    """Representación JSON del estado actual (todos los campos editables)."""
    return {
        "zona_objetivo": cfg.zona_objetivo,
        "precio_min": cfg.precio_min,
        "precio_max": cfg.precio_max,
        "precio_max_eur_m2": cfg.precio_max_eur_m2,
        "alquiler_estimado_eur_m2_mes": cfg.alquiler_estimado_eur_m2_mes,
        "rentabilidad_min": cfg.rentabilidad_min,
        "precio_min_compra": cfg.precio_min_compra,
        "deduplicacion_por_url": cfg.deduplicacion_por_url,
        "umbral_llamar_hoy": cfg.umbral_llamar_hoy,
        "pesos": dict(cfg.pesos),
        "alquiler_por_zona": dict(cfg.alquiler_por_zona),
        "telegram_activo": cfg.telegram_activo,
        "telegram_bot_token": cfg.telegram_bot_token,
        "telegram_chat_id": cfg.telegram_chat_id,
        "base_url": cfg.base_url,
    }


def config_publica() -> dict:
    """Estado completo que consume el panel de Ajustes (GET /api/config)."""
    return to_dict(CONFIG)


def guardar_config(cfg) -> None:
    """Persiste el estado actual en data/config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(to_dict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _aplicar(datos: dict) -> None:
    """
    Aplica un payload (parcial) sobre el CONFIG global MUTÁNDOLO in place.
    - "pesos" se fusiona con los por defecto para no dejar sumas rotas.
    - Claves desconocidas o valores None se ignoran (futuro-proof).
    """
    for clave, valor in (datos or {}).items():
        if valor is None:
            continue
        if clave == "pesos" and isinstance(valor, dict):
            merged = InvestmentConfig().pesos
            merged.update({k: float(v) for k, v in valor.items() if v is not None})
            CONFIG.pesos = merged
        elif hasattr(CONFIG, clave):
            setattr(CONFIG, clave, valor)


def _aplicar_env() -> None:
    """
    Sobrescribe en CONFIG los campos sensibles definidos por variables de
    entorno (si existen). La env manda sobre config.json y sobre el panel.
    Si hay token por env, la auto-alerta se activa (entrega lista para usar).
    """
    for env_var, attr in ENV_KEYS.items():
        valor = os.getenv(env_var)
        if valor:
            setattr(CONFIG, attr, valor.strip())
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        CONFIG.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN").strip()
        CONFIG.telegram_activo = True


def cargar_config() -> None:
    """
    Carga data/config.json sobre el CONFIG global. Si no existe el archivo,
    lo crea con los valores por defecto. Se llama en el startup del servidor.
    Después, las variables de entorno (si existen) sobrescriben las claves
    sensibles: así un despliegue en la nube inyecta el token sin guardarlo.
    """
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                datos = json.load(f)
            if isinstance(datos, dict):
                _aplicar(datos)
        except Exception:  # noqa: BLE001 - un config corrupto no debe tumbar la app
            pass
    else:
        guardar_config(CONFIG)
    _aplicar_env()


def actualizar(datos: dict) -> None:
    """
    Aplica un cambio desde el panel y lo persiste en data/config.json.
    Las claves sensibles gestionadas por entorno se vuelven a reaplicar para
    que el operador del despliegue siga mandando sobre el panel.
    """
    _aplicar(datos)
    guardar_config(CONFIG)          # persiste lo del panel (sin secretos de env)
    _aplicar_env()                  # reaplica env DESPUÉS del save → secrets no se escriben a disco


# Banderas rojas: si el texto del anuncio contiene cualquiera de estas
# claves, el inmueble se marca DESCARTAR de forma automática.
RED_FLAGS = [
    "ocupado",
    "ocupada",
    "sin posesión",
    "sin posesion",
    "no visitable",
    "no se puede visitar",
    "subasta",
    "problemas de cédula",
    "problemas de cedula",
    "sin cédula",
    "sin cedula",
    "derramas pendientes",
    "bajo interior oscuro",
    "okupa",
]

# Palabras clave de facilidad de alquiler/reventa (liquidez)
LIQUIDEZ_POSITIVA = [
    "amueblado",
    "amueblada",
    "vistas",
    "luminoso",
    "exterior",
    "balcón",
    "balcon",
    "terraza",
    "ascensor",
    "parking",
    "garaje",
    "aire acondicionado",
    "climatizado",
    "restaurado",
]

# Palabras clave de calidad de microzona/ubicación
UBICACION_POSITIVA = [
    "centro",
    "casco antiguo",
    "plaza",
    "avenida",
    "cerca del centro",
    "junto a",
    "zona comercial",
    "estación",
    "universidad",
    "mercado",
    "santiago",
    "san miguel",
]

# Niveles de reforma
REFORMA_LIGERA = ["a reformar ligero", "ligera reforma", "actualizar", "mínima reforma", "mínima", "a pintar", "a retocar"]
REFORMA_MEDIA = ["a reformar", "reforma media", "modernizar", "a renovar", "a actualizar"]
REFORMA_ESTRUCTURAL = ["reforma integral", "a reformar entero", "obras", "reforma estructural", "a estructura", "sin reformar", "ruinas", "ruina"]