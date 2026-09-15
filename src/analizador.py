"""
Orquestación: enlaza parsers, scoring y base de datos.
Incluye el flujo de análisis rápido y la importación desde /inputs con deduplicación.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from . import config as cfg
from . import database as db
from . import telegram
from .models import AnuncioBase, Inmueble, Veredicto
from .parsers import listar_archivos_inputs, parse_archivo
from .scoring import evaluar, normalizar_url, similitud_texto


def _guardar_y_notificar(inm: Inmueble, es_nuevo: bool = False) -> Inmueble:
    """
    Persiste un inmueble y, si es un registro NUEVO con veredicto LLAMAR HOY,
    notifica automáticamente por Telegram (solo si la auto-alerta está activa).
    Los duplicados/actualizaciones NO re-notifican, así una re-importación del
    mismo archivo no spamea el canal.
    """
    guardado = db.guardar_inmueble(inm)
    if (
        es_nuevo
        and cfg.CONFIG.telegram_activo
        and guardado.veredicto in (Veredicto.LLAMAR_HOY, "LLAMAR HOY")
    ):
        telegram.notificar_inmueble(guardado)
    return guardado


def analizar_anuncio_vuelo(anuncio: AnuncioBase) -> Inmueble:
    """
    Recibe un anuncio pegado/importado, lo evalúa, lo persiste y (si es una
    oportunidad nueva LLAMAR HOY) envía la alerta de Telegram.
    Deduplicación: por URL normalizada o, si no hay URL, por similitud de texto.
    """
    if anuncio.url:
        anuncio.url = normalizar_url(anuncio.url)

    # Si ya existe por URL, re-evaluamos y actualizamos en vez de duplicar
    if anuncio.url and db.existe_url(anuncio.url):
        inm = evaluar(anuncio)
        return _guardar_y_notificar(inm, es_nuevo=False)

    # Sin URL: comprobar por similitud de texto contra el inventario
    if not anuncio.url and (anuncio.texto or anuncio.titulo):
        nuevo_t = ((anuncio.texto or "") + " " + (anuncio.titulo or "")).lower().strip()
        existentes = db.listar_inmuebles({"limite": 300})
        for prev in existentes:
            prev_t = ((prev.texto or "") + " " + (prev.titulo or "")).lower().strip()
            coincide = False
            if nuevo_t and prev_t:
                coincide = similitud_texto(nuevo_t, prev_t) > 0.82
            # Dedup estructurado: mismo precio, m² y zona compatible = mismo piso
            if not coincide and anuncio.precio and prev.precio and anuncio.m2 and prev.m2:
                misma_zona = (not anuncio.zona) or (not prev.zona) or anuncio.zona.lower() == prev.zona.lower()
                coincide = (
                    abs(anuncio.precio - prev.precio) <= 1
                    and abs(anuncio.m2 - prev.m2) <= 1
                    and misma_zona
                )
            if coincide:
                # Duplicado detectado: actualizamos ese registro (fuente más nueva)
                prev.precio = anuncio.precio or prev.precio
                prev.m2 = anuncio.m2 or prev.m2
                prev.texto = anuncio.texto or prev.texto
                inm = evaluar(prev)
                return _guardar_y_notificar(inm, es_nuevo=False)

    inm = evaluar(anuncio)
    return _guardar_y_notificar(inm, es_nuevo=True)


def recalcular_todo() -> dict:
    """
    Re-evalúa TODOS los inmuebles del inventario con la configuración actual.
    Se usa al guardar Ajustes desde el panel para que las puntuaciones y
    veredictos reflejen los nuevos umbrales/pesos sin perder nada.
    """
    existentes = db.listar_inmuebles({"limite": 100_000})
    recalculados = 0
    for inm in existentes:
        # evaluar() conserva el id del registro -> guardar actualiza en sitio
        reevaluado = evaluar(inm)
        db.guardar_inmueble(reevaluado)
        recalculados += 1
    return {"recalculados": recalculados}


def importar_desde_inputs(archivos: Optional[List[Path]] = None) -> dict:
    """
    Escanea /inputs (o una lista concreta de archivos), parsea cada uno y
    analiza todos los anuncios encontrados. Devuelve un resumen.
    """
    if archivos is None:
        archivos = listar_archivos_inputs()

    total_encontrados = 0
    total_nuevos = 0
    total_duplicados = 0
    total_actualizados = 0
    total_vuelos = 0
    errores = []
    detalle_archivos = []

    for path in archivos:
        try:
            anuncios = parse_archivo(path)
        except Exception as e:  # noqa: BLE001
            errores.append(f"{path.name}: {type(e).__name__}: {e}")
            continue

        detalle_archivos.append({"archivo": path.name, "anuncios_encontrados": len(anuncios)})
        total_encontrados += len(anuncios)

        nuevos = 0
        duplicados = 0
        actualizados = 0
        for anuncio in anuncios:
            total_vuelos += 1
            if anuncio.url and db.existe_url(normalizar_url(anuncio.url)):
                duplicados += 1
                continue
            # analizar_anuncio_vuelo persiste internamente; comprobamos si
            # añadió fila o solo actualizó un duplicado detectado por texto.
            antes = db.resumen()["total"]
            analizar_anuncio_vuelo(anuncio)
            if db.resumen()["total"] > antes:
                nuevos += 1
            else:
                actualizados += 1

        total_nuevos += nuevos
        total_duplicados += duplicados
        total_actualizados += actualizados
        db.registrar_importacion(path.name, str(path), nuevos)

    return {
        "archivos_procesados": len(archivos),
        "archivos": detalle_archivos,
        "anuncios_parseados": total_encontrados,
        "nuevos_importados": total_nuevos,
        "duplicados_omitidos": total_duplicados,
        "duplicados_por_texto": total_actualizados,
        "errores": errores,
    }