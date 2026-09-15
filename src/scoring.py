"""
Motor de scoring inmobiliario.
Implementa estrictamente las directrices de inversión especificadas:
umbrals, sistema de 100 puntos, banderas rojas y veredictos automáticos.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from . import config as cfg
from .config import CONFIG
from .models import AnuncioBase, Inmueble, Veredicto

# ---------------------------------------------------------------------------
# Parsing de campos numéricos desde texto libre
# ---------------------------------------------------------------------------

def extraer_precio(texto: str) -> Optional[float]:
    """Busca un precio: '120.000 €', '120000', 'precio: 95k'..."""
    if not texto:
        return None
    t = texto.lower()
    m = re.search(r"(\d{1,3}(?:[.,\s]\d{3})+|\d+)\s*(?:€|eur|euros)", t)
    if m:
        return _a_numero(m.group(1))
    m = re.search(r"(\d{2,3})k\b", t)
    if m:
        return float(m.group(1)) * 1000
    return None


def extraer_m2(texto: str) -> Optional[float]:
    """Busca metros cuadrados: '75 m²', '75m2', '75 mts'."""
    if not texto:
        return None
    t = texto.lower()
    m = re.search(r"(\d{2,4})\s*(?:m2|m²|mts|metros?2?)", t)
    if m:
        return _a_numero(m.group(1))
    return None


def extraer_zona(texto: str) -> Optional[str]:
    """Intenta inferir zona a partir de palabras clave de barrios."""
    t = texto.lower()
    for z in ["jerez centro", "casco antiguo", "santiago", "san miguel", "el puerto", "la granja"]:
        if z in t:
            return z.title()
    if "jerez" in t:
        return "Jerez de la Frontera"
    return None


def _a_numero(s: str) -> float:
    return float(s.replace(".", "").replace(",", ".").replace(" ", ""))


# ---------------------------------------------------------------------------
# Análisis de texto: riesgo, reforma, ubicación, liquidez
# ---------------------------------------------------------------------------

def detectar_banderas_rojas(texto: str) -> list:
    """Bandera roja crítica => el inmueble se DESCARTARÁ directamente."""
    t = (texto or "").lower()
    encontradas = []
    for flag in cfg.RED_FLAGS:
        if flag in t:
            encontradas.append(flag)
    return encontradas


def analizar_reforma(texto: str) -> tuple[int, int]:
    """
    Devuelve (nivel, puntos). Nivel 0 = no mencionado (mejor caso),
    ligera/media suman bien, estructural resta puntos.
    """
    t = (texto or "").lower()
    if any(p in t for p in cfg.REFORMA_ESTRUCTURAL):
        return 3, 3        # estructural: costosa, se penaliza
    if any(p in t for p in cfg.REFORMA_MEDIA):
        return 2, 6
    if any(p in t for p in cfg.REFORMA_LIGERA):
        return 1, 8
    if re.search(r"\breformad[oa]\b|\ren perfecto estado\b|\ren buen estado\b", t):
        return 0, 10
    # No menciona reforma: asumimos ligera/media asumible (neutral positivo)
    return 1, 8


def analizar_ubicacion(texto: str, zona: Optional[str]) -> int:
    """Puntos de calidad de microzona (máx 15)."""
    t = f"{texto or ''} {zona or ''}".lower()
    pts = 0
    for kw in cfg.UBICACION_POSITIVA:
        if kw in t:
            pts += 3
    if "jerez centro" in t or "casco antiguo" in t:
        pts += 4
    if "jerez" in t and "centro" not in t:
        pts += 2
    return min(pts, 15)


def analizar_liquidez(texto: str) -> int:
    """Facilidad de alquiler/reventa (máx 10)."""
    t = (texto or "").lower()
    pts = 5  # base neutra
    for kw in cfg.LIQUIDEZ_POSITIVA:
        if kw in t and pts < 10:
            pts += 1
    return min(pts, 10)


def analizar_documentacion(anuncio: AnuncioBase) -> tuple[int, list]:
    """Anuncio reciente y con buena documentación (máx 5 + motivos)."""
    pts = 0
    motivos = []
    if anuncio.texto and len(anuncio.texto) > 120:
        pts += 2
        motivos.append("Descripción detallada")
    elif anuncio.texto and len(anuncio.texto) > 40:
        pts += 1
    else:
        motivos.append("Descripción escueta")

    if anuncio.url:
        pts += 1
    if anuncio.precio and anuncio.m2:
        pts += 1
        motivos.append("Precio y metros cuadrados disponibles")
    if anuncio.fecha_publicacion:
        pts += 1
        motivos.append("Fecha de publicación registrada")
    return min(pts, 5), motivos


# ---------------------------------------------------------------------------
# Motor principal
# ---------------------------------------------------------------------------

def evaluar(anuncio: AnuncioBase) -> Inmueble:
    """
    Dado un anuncio (con o sin datos estructurados), lo evalúa
    y devuelve un Inmueble con puntuación, veredicto, motivos y riesgo.
    """
    cfg_local = CONFIG
    texto = (anuncio.texto or "") + " " + (anuncio.titulo or "")

    # --- Datos numéricos (los proporcionados prevalecen sobre el parseo)
    precio = anuncio.precio if anuncio.precio is not None else extraer_precio(texto)
    m2 = anuncio.m2 if anuncio.m2 is not None else extraer_m2(texto)
    zona = anuncio.zona or extraer_zona(texto) or cfg_local.zona_objetivo

    # Precio medio por m² de la zona (rent de referencia por microzona si existe)
    alquiler_ref = cfg_local.alquiler_por_zona.get(
        zona.lower(), cfg_local.alquiler_estimado_eur_m2_mes
    )

    inm = Inmueble(
        titulo=(anuncio.titulo or texto[:80]).strip(),
        url=anuncio.url,
        precio=precio,
        m2=m2,
        zona=zona,
        texto=anuncio.texto,
        fuente=anuncio.fuente,
        fecha_publicacion=anuncio.fecha_publicacion,
    )
    # Si el origen ya era un registro persistido (p. ej. dedup por texto),
    # conservamos su id para que el guardado actualice en vez de duplicar.
    if getattr(anuncio, "id", 0):
        inm.id = anuncio.id

    # --- Banderas rojas críticas => DESCARTAR sin más
    banderas = detectar_banderas_rojas(texto)
    inm.banderas_rojas = banderas
    datos_completos = precio is not None and m2 is not None
    inm.datos_completos = datos_completos

    if banderas:
        inm.puntuacion = 0.0
        inm.veredicto = Veredicto.DESCARTAR
        inm.motivos.append("🚩 Riesgo crítico: " + ", ".join(banderas))
        inm.motivos.append("Descartado por bandera roja de seguridad")
        return inm

    # --- Si no tenemos precio o m2, no podemos puntuar: REVISAR
    if not datos_completos:
        inm.veredicto = Veredicto.REVISAR
        inm.motivos = ["Datos incompletos: falta precio, m² o ambos"]
        inm.motivos.append("Revisar rastreador o anuncio manualmente")
        return inm

    # --- Métricas derivadas
    precio_m2 = precio / m2
    alquiler_mes = alquiler_ref * m2
    rentabilidad = ((alquiler_ref * m2 * 12) / precio) * 100
    descuento_pct = (1 - precio_m2 / cfg_local.precio_max_eur_m2) * 100

    inm.precio_eur_m2 = round(precio_m2, 2)
    inm.alquiler_estimado_mes = round(alquiler_mes, 2)
    inm.rentabilidad_bruta = round(rentabilidad, 2)

    # --- Precio de compra recomendado:
    # Objetivo: lograr rentabilidad >= rentabilidad_min sin bajar de m2_referencia.
    # precio_obj = rent_mes*12 / rent_min%  (lo que pagaríamos para cumplir el mínimo)
    precio_obj = (alquiler_ref * m2 * 12) / (cfg_local.rentabilidad_min / 100)
    # Además no pagar más de 1.600 €/m²:
    precio_techo = cfg_local.precio_max_eur_m2 * m2
    precio_recomendado = min(precio_obj, precio_techo)
    # Suelo mínimo (evitar precios absurdamente bajos si ya está por debajo)
    inm.precio_compra_recomendado = round(max(precio_recomendado, precio * 0.7), 0)

    # --- Desglose de puntos usando los PESOS CONFIGURABLES (por defecto suma 100).
    # Cada bloque puntúa primero su escala nativa (0..punt. máx) y después se
    # normaliza a 0..1 y se multiplica por el peso configurado en config.py:
    # con los pesos por defecto los resultados son idénticos a la versión fija.
    desglose = {}

    w_desc = cfg_local.pesos.get("descuento", 35)
    w_rent = cfg_local.pesos.get("rentabilidad", 25)
    w_ubic = cfg_local.pesos.get("ubicacion", 15)
    w_ref = cfg_local.pesos.get("reforma", 10)
    w_liq = cfg_local.pesos.get("liquidez", 10)
    w_doc = cfg_local.pesos.get("documentacion", 5)

    # 1) Descuento frente al tope de 1600 €/m².
    #    Puntuación completa a partir de un 45% de descuento (~880 €/m²).
    frac_desc = max(0.0, min(1.0, descuento_pct / 45.0))
    desglose["descuento"] = round(w_desc * frac_desc, 1)

    # 2) Rentabilidad bruta estimada. 100% del peso al superar rentabilidad_min*1.15.
    frac_rent = max(0.0, min(1.0, rentabilidad / (cfg_local.rentabilidad_min * 1.15)))
    desglose["rentabilidad"] = round(w_rent * frac_rent, 1)

    # 3) Calidad de la microzona (escala nativa 0..15)
    desglose["ubicacion"] = round(w_ubic * min(1.0, analizar_ubicacion(texto, zona) / 15.0), 1)

    # 4) Nivel de reforma asumible (escala nativa 0..10)
    _, pts_ref_raw = analizar_reforma(texto)
    desglose["reforma"] = round(w_ref * min(1.0, pts_ref_raw / 10.0), 1)

    # 5) Facilidad de alquiler o reventa (escala nativa 0..10)
    desglose["liquidez"] = round(w_liq * min(1.0, analizar_liquidez(texto) / 10.0), 1)

    # 6) Documentación y anuncio reciente (escala nativa 0..5)
    pts_doc, motivos_doc = analizar_documentacion(anuncio)
    desglose["documentacion"] = round(w_doc * min(1.0, pts_doc / 5.0), 1)

    inm.desglose_puntos = desglose
    puntuacion = sum(desglose.values())
    inm.puntuacion = round(puntuacion, 1)

    # --- Veredicto automático
    motivos = []
    if descuento_pct > 0:
        motivos.append(f"Descuento ≈ {descuento_pct:.0f}% frente a {cfg_local.precio_max_eur_m2:.0f} €/m²")
    else:
        motivos.append(f"A {precio_m2:.0f} €/m² → sin descuento, sobre el tope")
    motivos.append(f"Rentabilidad bruta {rentabilidad:.2f}% (mín. {cfg_local.rentabilidad_min:.0f}%)")
    motivos.append(f"Precio compra recomendado ≈ {inm.precio_compra_recomendado:,.0f} €".replace(",", "."))
    motivos += motivos_doc
    inm.motivos = motivos

    # Umbral de LLAMAR HOY configurable (en el panel de Ajustes)
    if puntuacion >= cfg_local.umbral_llamar_hoy:
        inm.veredicto = Veredicto.LLAMAR_HOY
        inm.motivos.append("📞 Acción: contactar hoy, alta prioridad")
    elif puntuacion >= 55 or not datos_completos:
        inm.veredicto = Veredicto.REVISAR
        if not inm.motivos or "Datos incompletos" not in str(inm.motivos):
            inm.motivos.append("👀 Acción: revisar a fondo antes de decidir")
    else:
        inm.veredicto = Veredicto.DESCARTAR
        inm.motivos.append("❌ Baja puntuación: no cumple objetivos de inversión")

    return inm


def normalizar_url(url: str) -> str:
    """Limpia la URL para comparar deduplicaciones (sin tracking)."""
    if not url:
        return url
    url = url.strip()
    url = re.sub(r"\?.*$", "", url)   # quitar query string
    url = re.sub(r"#.*$", "", url)    # quitar anclas
    return url


def similitud_texto(a: str, b: str) -> float:
    """
    Ratio de similitud robusto para detectar duplicados sin URL.

    Tolera ruido al final del anuncio (firmas, alertas de n8n, tracking):
    - Si un texto contiene el otro completo → duplicado claro (0.95).
    - Si no, mide el solapamiento de caracteres comunes sobre la cadena
      MÁS CORTA, de modo que un anuncio re-pegado con recortes no pierda
      puntuación por la diferencia de longitud.
    """
    a = " ".join((a or "").lower().split())
    b = " ".join((b or "").lower().split())
    if not a or not b:
        return 0.0
    if (len(a) >= 30 and a in b) or (len(b) >= 30 and b in a):
        return 0.95  # contención total → mismo anuncio
    s = SequenceMatcher(None, a, b)
    coincidencias = sum(blk.size for blk in s.get_matching_blocks())
    return coincidencias / min(len(a), len(b))