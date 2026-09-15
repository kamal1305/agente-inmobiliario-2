"""
API del Agente Analizador Inmobiliario — FastAPI.
Sirve el dashboard y expone endpoints para analizar, importar y gestionar inmuebles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from . import config as cfg
from . import database as db
from . import telegram
from .analizador import (  # lógica de orquestación (ver analizador.py)
    analizar_anuncio_vuelo,
    importar_desde_inputs,
    recalcular_todo,
)
from .models import CambioEstado, ConfigUpdate, Filtros, Inmueble, Veredicto
from .scoring import normalizar_url

BASE_DIR = Path(__file__).resolve().parent.parent
app = FastAPI(title="Agente Analizador Inmobiliario", version="1.0.0")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# El template es un SPA puro (sin sintaxis Jinja2), se sirve como HTML crudo
_HTML_CACHE: str | None = None


def _leer_html() -> str:
    global _HTML_CACHE
    if _HTML_CACHE is None:
        _HTML_CACHE = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    return _HTML_CACHE


@app.on_event("startup")
def arranque() -> None:
    db.init_db()
    cfg.cargar_config()  # carga/crea data/config.json al arrancar


# ---------------------------------------------------------------------------
# Página web
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return HTMLResponse(content=_leer_html())


@app.get("/api/resumen")
def api_resumen():
    r = db.resumen()
    r["mejor_oportunidad"] = _json_safe(r["mejor_oportunidad"])
    return r


@app.get("/api/inmuebles")
def api_inmuebles(
    texto: str = "",
    veredicto: Optional[str] = None,
    rentabilidad_min: Optional[float] = None,
    orden: str = "puntuacion_desc",
    limite: int = 50,
):
    filtros = Filtros(texto=texto, veredicto=veredicto, rentabilidad_min=rentabilidad_min, orden=orden, limite=limite)
    inmuebles = db.listar_inmuebles(filtros.model_dump())
    return [_json_safe(i.model_dump(), con_id=True) for i in inmuebles]


@app.post("/api/analizar")
def api_analizar(anuncio: Inmueble):
    """Analiza un inmueble al vuelo (pegado desde el dashboard)."""
    if not (anuncio.texto or anuncio.titulo or anuncio.url):
        raise HTTPException(400, "Aporta un texto, título o URL del anuncio")
    if anuncio.url:
        anuncio.url = normalizar_url(anuncio.url)
    inm = analizar_anuncio_vuelo(anuncio)
    return _json_safe(inm.model_dump(), con_id=True)


@app.post("/api/importar")
def api_importar():
    """Escanea /inputs, parsea archivos e importa con deduplicación por URL."""
    resultado = importar_desde_inputs()
    return resultado


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    """Subida manual de un archivo al directorio /inputs."""
    nombre = Path(file.filename or "input.dat").name
    destino = BASE_DIR / "inputs" / nombre
    destino.write_bytes(await file.read())
    resultado = importar_desde_inputs(archivos=[destino])
    return {**{"archivo_guardado": nombre}, **resultado}


@app.patch("/api/inmuebles/{inmueble_id}/estado")
def api_cambiar_estado(inmueble_id: int, cambio: CambioEstado):
    if cambio.estado not in db.ESTADOS_CRM:
        raise HTTPException(400, "Estado CRM no válido")
    if not db.obtener_inmueble(inmueble_id):
        raise HTTPException(404, "Inmueble no encontrado")
    db.actualizar_estado_crm(inmueble_id, cambio.estado)
    return {"ok": True}


@app.delete("/api/inmuebles/{inmueble_id}")
def api_eliminar(inmueble_id: int):
    db.eliminar_inmueble(inmueble_id)
    return {"ok": True}


@app.delete("/api/limpiar")
def api_limpiar():
    """Borra todo el inventario (útil para pruebas). Requiere confirmación query."""
    db.purge_all()
    return {"ok": True}


@app.get("/api/historial")
def api_historial():
    return db.historial_importaciones()


# ---------------------------------------------------------------------------
# Configuración (panel ⚙️)
# ---------------------------------------------------------------------------

@app.get("/api/config")
def api_get_config():
    """Estado completo de la configuración para rellenar el panel de Ajustes."""
    return cfg.config_publica()


@app.post("/api/config")
def api_save_config(cambio: ConfigUpdate):
    """
    Aplica los cambios enviados desde el panel, persiste data/config.json y
    recalcula TODAS las oportunidades con los nuevos umbrales/pesos.
    Solo se aplican los campos presentes en el body.
    """
    cambios = cambio.model_dump(exclude_none=True)
    if not cambios:
        raise HTTPException(400, "No hay campos que guardar")
    cfg.actualizar(cambios)
    resultado = recalcular_todo()
    return {"config": cfg.config_publica(), **resultado}


# ---------------------------------------------------------------------------
# Telegram (botón 📲 de cada tarjeta)
# ---------------------------------------------------------------------------

@app.post("/api/inmuebles/{inmueble_id}/telegram")
def api_enviar_telegram(inmueble_id: int):
    """Reenvío manual a Telegram de un inmueble concreto."""
    inm = db.obtener_inmueble(inmueble_id)
    if not inm:
        raise HTTPException(404, "Inmueble no encontrado")
    resultado = telegram.notificar_inmueble(inm)
    if resultado.get("errores"):
        # Se informa igualmente, no es un 5xx: Telegram puede fallar por red.
        return {**resultado, "titulo": inm.titulo}
    return {**resultado, "titulo": inm.titulo}


# ---------------------------------------------------------------------------
# Helpers de serialización segura
# ---------------------------------------------------------------------------

def _json_safe(d: Optional[dict], con_id: bool = False) -> Optional[dict]:
    if not d:
        return d if d is None else {}
    keys = [
        "id", "titulo", "url", "precio", "m2", "zona", "texto", "fuente",
        "fecha_publicacion", "precio_eur_m2", "alquiler_estimado_mes",
        "rentabilidad_bruta", "precio_compra_recomendado", "puntuacion",
        "veredicto", "estado_crm", "banderas_rojas", "motivos",
        "desglose_puntos", "datos_completos", "fecha_analisis",
    ]
    out = {}
    for k in keys:
        if k in d and d[k] is not None:
            v = d[k]
            if isinstance(v, Veredicto):
                v = v.value
            out[k] = v
    return out