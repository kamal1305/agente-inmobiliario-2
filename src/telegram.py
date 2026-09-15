"""
Módulo de notificaciones por Telegram.

Usa la Bot API oficial de Telegram vía `requests`. Soporta:
- Varios destinatarios a la vez (ids separados por comas o espacios).
- El ID de un grupo/canal (números negativos que empiezan por -100…).

Nunca lanza excepciones hacia el flujo principal: si Telegram no está
configurado o falla, devuelve un dict de resultado y todo sigue funcionando.
"""

from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import quote

import requests

from . import config as cfg
from .models import Inmueble

# Endpoint oficial de la Bot API (sendMessage)
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_TIMEOUT = 10  # segundos — una notificación no debe bloquear la app


# ---------------------------------------------------------------------------
# Destinatarios
# ---------------------------------------------------------------------------

def _normalizar_chat_ids(chat_id: Optional[str]) -> list:
    """
    '12345678, 87654321'  o  '12345678 -1002345678901'
    -> ['12345678', '87654321', '-1002345678901']
    Acepta chats individuales (enteros positivos) y grupos (-100…).
    """
    if not chat_id:
        return []
    partes = re.split(r"[,\s;]+", str(chat_id).strip())
    return [p for p in partes if p]


def configurado() -> bool:
    """True si hay token de bot y al menos un chat/grupo configurado."""
    return bool(cfg.CONFIG.telegram_bot_token) and bool(_normalizar_chat_ids(cfg.CONFIG.telegram_chat_id))


# ---------------------------------------------------------------------------
# Envío (bucle de destinatarios)
# ---------------------------------------------------------------------------

def enviar_texto(texto: str) -> dict:
    """
    Envía `texto` a TODOS los destinatarios configurados (loop).
    Devuelve {"enviados": int, "errores": [..]}. Nunca lanza.
    """
    ids = _normalizar_chat_ids(cfg.CONFIG.telegram_chat_id)
    if not cfg.CONFIG.telegram_bot_token or not ids:
        return {"enviados": 0, "errores": ["Telegram no configurado (token o chat_id)"]}

    enviados = 0
    errores = []
    for chat_id in ids:
        try:
            r = requests.post(
                TELEGRAM_API.format(token=cfg.CONFIG.telegram_bot_token),
                data={
                    "chat_id": chat_id,
                    "text": texto,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=_TIMEOUT,
            )
            ok = r.status_code == 200 and r.json().get("ok")
            if ok:
                enviados += 1
            else:
                # Telegram devuelve 400 con una descripción útil (p. ej. chat no encontrado)
                errores.append(f"{chat_id}: {r.text[:200]}")
        except Exception as e:  # noqa: BLE001 - red caída etc.
            errores.append(f"{chat_id}: {type(e).__name__}")
    return {"enviados": enviados, "errores": errores}


# ---------------------------------------------------------------------------
# Construcción del mensaje
# ---------------------------------------------------------------------------

def _esc(s) -> str:
    """Escape HTML mínimo para parse_mode='HTML' (los enlaces se pasan aparte)."""
    return html.escape(str(s or ""), quote=False)


def url_maps(zona: Optional[str]) -> str:
    """Enlace a Google Maps con la búsqueda de la zona detectada."""
    q = quote(zona or cfg.CONFIG.zona_objetivo)
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def mensaje_inmueble(inm: Inmueble) -> str:
    """Resumen telegram-friendly de una oportunidad (HTML)."""
    precio = f"{inm.precio:,.0f} €".replace(",", ".") if inm.precio else "—"
    m2 = f"{inm.m2:,.0f}".replace(",", ".") if inm.m2 else "—"
    eur_m2 = f"{inm.precio_eur_m2:,.0f}".replace(",", ".") if inm.precio_eur_m2 else "—"
    rent = f"{inm.rentabilidad_bruta:.1f}%" if inm.rentabilidad_bruta is not None else "—"
    objetivo = f"{inm.precio_compra_recomendado:,.0f} €".replace(",", ".") if inm.precio_compra_recomendado else "—"

    lines = [
        "🏠 <b>OPORTUNIDAD · LLAMAR HOY</b>",
        f"📋 {_esc(inm.titulo)}",
        f"📍 <b>{_esc(inm.zona) or cfg.CONFIG.zona_objetivo}</b>",
        f"💶 {precio} · {m2} m² · {eur_m2} €/m²",
        f"📈 Rentabilidad bruta: <b>{rent}</b>",
        f"🎯 Precio compra recomendado: {objetivo}",
    ]
    # Enlace a Google Maps con la zona detectada
    lines.append(f"🧭 <a href=\"{url_maps(inm.zona)}\">Ver ubicación en Google Maps</a>")
    # Enlace al anuncio original si hay URL
    if inm.url:
        lines.append(f"🔗 <a href=\"{_esc(inm.url)}\">Ver anuncio original</a>")
    else:
        lines.append("🔗 Anuncio sin enlace (pegado manual)")
    # Enlace de vuelta al panel si hay BASE_URL configurada (entorno o config.json)
    if cfg.CONFIG.base_url:
        base = str(cfg.CONFIG.base_url).rstrip("/")
        lines.append(f"💻 <a href=\"{_esc(base)}\">Abrir panel del agente</a>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API de alto nivel
# ---------------------------------------------------------------------------

def notificar_inmueble(inm: Inmueble) -> dict:
    """Envía la ficha de un inmueble. Si no hay config de Telegram, no-op."""
    if not configurado():
        return {"telegram": False, "enviados": 0, "errores": ["Telegram no configurado"]}
    resultado = enviar_texto(mensaje_inmueble(inm))
    return {"telegram": True, **resultado}