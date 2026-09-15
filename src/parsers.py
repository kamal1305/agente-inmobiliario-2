"""
Parsers de archivos de entrada.
Detecta la estructura de cualquier JSON/CSV/TXT en /inputs (exports de n8n,
historial de Google Sheets, notas) y extrae anuncios evaluables.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import List

from .models import AnuncioBase
from .scoring import extraer_m2, extraer_precio, extraer_zona

INPUTS_DIR = Path(__file__).resolve().parent.parent / "inputs"

# Nombres de columna comunes que pueden aparecer en exports de Sheets/n8n.
MAPEO_CAMPOS = {
    "url": ["url", "link", "enlace", "href", "source_url", "anuncio", "link_anuncio"],
    "precio": ["precio", "price", "precio de venta", "precio_venta", "importe", "valor", "precio (€)"],
    "m2": ["m2", "m²", "metros", "metros2", "superficie", "mts", "area", "area m2"],
    "zona": ["zona", "zona_barrio", "barrio", "distrito", "ciudad", "ubicacion"],
    "titulo": ["titulo", "title", "nombre", "nombre_anuncio", "asunto", "subject"],
    "texto": ["texto", "descripcion", "descripción", "description", "body", "cuerpo", "html", "contenido", "text"],
}


def _normalizar_clave(c: str) -> str:
    """Búsqueda por clave normalizada dentro del mapeo."""
    k = c.strip().lower().replace("_", " ").replace("'", "")
    for campo, alias in MAPEO_CAMPOS.items():
        if k in alias:
            return campo
    return c.strip().lower()


def _filtrar_registro(d: dict) -> dict:
    """Renombra columnas/tildes a campos canónicos y excluye ruido."""
    limpio = {}
    for clave, valor in d.items():
        campo = _normalizar_clave(str(clave))
        if campo not in {"url", "precio", "m2", "zona", "titulo", "texto"}:
            continue
        if valor is None:
            continue
        limpio[campo] = valor
    return limpio


def _valor_a_precio(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return extraer_precio(str(v))


def _valor_a_m2(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return extraer_m2(str(v))


def _fila_a_anuncio(fila: dict, fuente: str) -> AnuncioBase | None:
    limpio = _filtrar_registro(fila)
    if not limpio:
        return None

    # El 'texto' a veces viene como JSON anidado (n8n con html vue)
    cuerpo = limpio.get("texto")
    if isinstance(cuerpo, (dict, list)):
        cuerpo = json.dumps(cuerpo, ensure_ascii=False)
    elif cuerpo is not None:
        cuerpo = str(cuerpo)

    titulo = limpio.get("titulo")
    if isinstance(titulo, (dict, list)):
        titulo = json.dumps(titulo, ensure_ascii=False)
    elif titulo is not None:
        titulo = str(titulo)

    url = str(limpio["url"]).strip() if limpio.get("url") else None

    # Un anuncio sin url ni texto tampoco sirve
    t = (cuerpo or "") + " " + (titulo or "")
    if not url and not t.strip():
        return None

    return AnuncioBase(
        titulo=titulo or (t[:80] if t else ""),
        url=url,
        precio=_valor_a_precio(limpio.get("precio")),
        m2=_valor_a_m2(limpio.get("m2")),
        zona=str(limpio["zona"]) if limpio.get("zona") else None,
        texto=cuerpo or "",
        fuente=fuente,
    )


def parse_json(path: Path) -> List[AnuncioBase]:
    """JSON simple, o JSON-lines (una fila por línea), o array de objetos."""
    try:
        contenido = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        contenido = path.read_text(encoding="latin-1")

    contenido = contenido.strip()
    anuncios = []

    # Variante JSONL: varias líneas, cada una un objeto JSON
    es_jsonl = contenido.startswith("{") and "\n" in contenido
    if es_jsonl:
        for linea in contenido.splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            try:
                obj = json.loads(linea)
            except json.JSONDecodeError:
                continue
            registros = obj if isinstance(obj, list) else [obj]
            for reg in registros:
                if isinstance(reg, dict):
                    a = _fila_a_anuncio(reg, f"json:{path.name}")
                    if a:
                        anuncios.append(a)
        return anuncios

    dato = json.loads(contenido)

    if isinstance(dato, dict):
        # Puede ser un objeto con lista de anuncios o una sola alerta
        for v in dato.values():
            if isinstance(v, list):
                dado = v
                break
        else:
            dato = [dato]
    if isinstance(dato, list):
        for reg in dato:
            if isinstance(reg, dict):
                a = _fila_a_anuncio(reg, f"json:{path.name}")
                if a:
                    anuncios.append(a)
    return anuncios


def parse_csv(path: Path) -> List[AnuncioBase]:
    """CSV con cabecera. Detecta separador (; , tab) automáticamente."""
    try:
        texto = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        texto = path.read_text(encoding="latin-1")

    muestra = texto[:400]
    sep = ";"
    if muestra.count("\t") > muestra.count(";"):
        sep = "\t"
    elif muestra.count(",") > muestra.count(";") and "," in muestra:
        sep = ","

    reader = csv.DictReader(texto.splitlines(), delimiter=sep)
    anuncios = []
    for fila in reader:
        a = _fila_a_anuncio(fila, f"csv:{path.name}")
        if a:
            anuncios.append(a)
    return anuncios


def parse_txt(path: Path) -> List[AnuncioBase]:
    """
    Texto plano: puede contener varios anuncios separados por líneas en blanco
    o marcadores tipo '---' / 'NUEVO ANUNCIO'. Cada bloque se trata como anuncio.
    """
    try:
        contenido = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        contenido = path.read_text(encoding="latin-1")

    bloques = re.split(r"\n\s*(?:---+|###+|===+)\s*\n|\n\s*nuevo anuncio\s*\n", contenido, flags=re.I)
    anuncios = []
    for bloque in bloques:
        bloque = bloque.strip()
        if not bloque:
            continue
        a = AnuncioBase(
            texto=bloque,
            url=None,
            precio=extraer_precio(bloque),
            m2=extraer_m2(bloque),
            zona=extraer_zona(bloque),
            fuente=f"txt:{path.name}",
        )
        anuncios.append(a)
    return anuncios


def parse_archivo(path: Path) -> List[AnuncioBase]:
    """Despacha según extensión."""
    ext = path.suffix.lower()
    if ext == ".json":
        return parse_json(path)
    if ext == ".csv":
        return parse_csv(path)
    if ext in (".txt", ".md", ".eml"):
        return parse_txt(path)
    if ext == ".html":
        return parse_txt(path)  # tratamiento como texto simple
    return []


def listar_archivos_inputs() -> List[Path]:
    """Todos los archivos soportados presentes en /inputs."""
    if not INPUTS_DIR.exists():
        return []
    return sorted(
        p for p in INPUTS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in {".json", ".csv", ".txt", ".md", ".eml", ".html"}
    )