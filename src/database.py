"""
Gestor de datos local en SQLite.
Responsable de persistir anuncios, deduplicar por URL y consultar el inventario.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from .models import Inmueble, Veredicto

# Estados CRM válidos (expuesto para control de la API)
ESTADOS_CRM = {"nuevo", "analizado", "contactado", "descartado"}

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "inmuebles.db"


_INITIALIZADO = False


def _conexion() -> sqlite3.Connection:
    """Conexión preparada; inicializa las tablas la primera vez (lazy init)."""
    global _INITIALIZADO
    if not _INITIALIZADO:
        init_db()
        _INITIALIZADO = True
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL;")
    return con


def init_db() -> None:
    """Crea las tablas si no existen (idempotente)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)  # conexión cruda para evitar recursión
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS inmuebles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT DEFAULT '',
                url TEXT UNIQUE,
                precio REAL,
                m2 REAL,
                zona TEXT,
                texto TEXT DEFAULT '',
                fuente TEXT DEFAULT 'manual',
                fecha_publicacion TEXT,
                precio_eur_m2 REAL,
                alquiler_estimado_mes REAL,
                rentabilidad_bruta REAL,
                precio_compra_recomendado REAL,
                puntuacion REAL DEFAULT 0,
                veredicto TEXT DEFAULT 'REVISAR',
                estado_crm TEXT DEFAULT 'nuevo',
                banderas_rojas TEXT DEFAULT '[]',
                motivos TEXT DEFAULT '[]',
                desglose_puntos TEXT DEFAULT '{}',
                datos_completos INTEGER DEFAULT 1,
                fecha_analisis TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS archivados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT,
                ruta TEXT,
                inmuebles_importados INTEGER,
                fecha TEXT
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _fila_a_modelo(row: sqlite3.Row) -> Inmueble:
    """Convierte una fila SQLite en un modelo Inmueble."""
    return Inmueble(
        id=row["id"],
        titulo=row["titulo"] or "",
        url=row["url"],
        precio=row["precio"],
        m2=row["m2"],
        zona=row["zona"],
        texto=row["texto"] or "",
        fuente=row["fuente"] or "manual",
        fecha_publicacion=row["fecha_publicacion"],
        precio_eur_m2=row["precio_eur_m2"],
        alquiler_estimado_mes=row["alquiler_estimado_mes"],
        rentabilidad_bruta=row["rentabilidad_bruta"],
        precio_compra_recomendado=row["precio_compra_recomendado"],
        puntuacion=row["puntuacion"] or 0.0,
        veredicto=Veredicto(row["veredicto"]),
        estado_crm=row["estado_crm"],
        banderas_rojas=json.loads(row["banderas_rojas"] or "[]"),
        motivos=json.loads(row["motivos"] or "[]"),
        desglose_puntos=json.loads(row["desglose_puntos"] or "{}"),
        datos_completos=bool(row["datos_completos"]),
    )


def _valor_veredicto(v) -> str:
    """Normaliza el veredicto a string (acepta enum de Pydantic o str)."""
    return v.value if hasattr(v, "value") else v


def guardar_inmueble(inm: Inmueble) -> Inmueble:
    """
    Inserta un inmueble o actualiza el existente.
    Deduplicación: por URL normalizada o por id si el registro ya vino de la BD
    (caso de anuncios sin URL que coinciden por similitud de texto).
    """
    with _conexion() as con:
        existe = None
        if inm.url:
            cur = con.execute("SELECT id FROM inmuebles WHERE url = ?", (inm.url,))
            existe = cur.fetchone()
        if not existe and inm.id:
            cur = con.execute("SELECT id FROM inmuebles WHERE id = ?", (inm.id,))
            existe = cur.fetchone()

        payload = (
            inm.titulo, inm.url, inm.precio, inm.m2, inm.zona, inm.texto, inm.fuente,
            inm.fecha_publicacion.isoformat() if inm.fecha_publicacion else None,
            inm.precio_eur_m2, inm.alquiler_estimado_mes, inm.rentabilidad_bruta,
            inm.precio_compra_recomendado, inm.puntuacion, _valor_veredicto(inm.veredicto),
            _valor_veredicto(inm.estado_crm), json.dumps(inm.banderas_rojas, ensure_ascii=False),
            json.dumps(inm.motivos, ensure_ascii=False),
            json.dumps(inm.desglose_puntos, ensure_ascii=False),
            int(inm.datos_completos), inm.fecha_analisis.isoformat(),
        )

        if existe:
            con.execute(
                """
                UPDATE inmuebles SET titulo=?, url=?, precio=?, m2=?, zona=?, texto=?,
                    fuente=?, fecha_publicacion=?, precio_eur_m2=?, alquiler_estimado_mes=?,
                    rentabilidad_bruta=?, precio_compra_recomendado=?, puntuacion=?,
                    veredicto=?, estado_crm=?, banderas_rojas=?, motivos=?,
                    desglose_puntos=?, datos_completos=?, fecha_analisis=?
                WHERE id=?
                """,
                payload + (existe["id"],),
            )
            inm.id = existe["id"]
        else:
            cur = con.execute(
                """
                INSERT INTO inmuebles (
                    titulo, url, precio, m2, zona, texto, fuente, fecha_publicacion,
                    precio_eur_m2, alquiler_estimado_mes, rentabilidad_bruta,
                    precio_compra_recomendado, puntuacion, veredicto, estado_crm,
                    banderas_rojas, motivos, desglose_puntos, datos_completos, fecha_analisis
                ) VALUES (?...)
                """.replace("?...", "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?"),
                payload,
            )
            inm.id = cur.lastrowid
    return inm


def listar_inmuebles(filtros=None) -> List[Inmueble]:
    """Consulta el inventario aplicando filtros y orden por puntuación."""
    f = filtros or {}
    sql = "SELECT * FROM inmuebles WHERE 1=1"
    params: list = []

    texto = (f.get("texto") or "").strip()
    if texto:
        sql += " AND (titulo LIKE ? OR zona LIKE ? OR texto LIKE ?)"
        like = f"%{texto}%"
        params += [like, like, like]

    if f.get("veredicto"):
        sql += " AND veredicto = ?"
        params.append(f["veredicto"])

    if f.get("rentabilidad_min") is not None:
        sql += " AND rentabilidad_bruta >= ?"
        params.append(f["rentabilidad_min"])

    if f.get("zona"):
        sql += " AND zona LIKE ?"
        params.append(f"%{f['zona']}%")

    orden = f.get("orden") or "puntuacion_desc"
    map_orden = {
        "puntuacion_desc": "puntuacion DESC",
        "puntuacion_asc": "puntuacion ASC",
        "precio_asc": "precio ASC",
        "precio_desc": "precio DESC",
        "rentabilidad_desc": "rentabilidad_bruta DESC",
        "fecha_desc": "fecha_analisis DESC",
    }
    sql += f" ORDER BY {map_orden.get(orden, 'puntuacion DESC')}"
    sql += " LIMIT ?"
    params.append(int(f.get("limite") or 50))

    with _conexion() as con:
        rows = con.execute(sql, params).fetchall()
    return [_fila_a_modelo(r) for r in rows]


def obtener_inmueble(inmueble_id: int) -> Optional[Inmueble]:
    with _conexion() as con:
        row = con.execute("SELECT * FROM inmuebles WHERE id=?", (inmueble_id,)).fetchone()
    return _fila_a_modelo(row) if row else None


def actualizar_estado_crm(inmueble_id: int, estado: str) -> None:
    with _conexion() as con:
        con.execute("UPDATE inmuebles SET estado_crm=? WHERE id=?", (estado, inmueble_id))


def eliminar_inmueble(inmueble_id: int) -> None:
    with _conexion() as con:
        con.execute("DELETE FROM inmuebles WHERE id=?", (inmueble_id,))


def existe_url(url: str) -> bool:
    if not url:
        return False
    with _conexion() as con:
        row = con.execute("SELECT 1 FROM inmuebles WHERE url=?", (url,)).fetchone()
    return row is not None


def resumen() -> dict:
    """Estadísticas agregadas para la cabecera del dashboard."""
    with _conexion() as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN veredicto='LLAMAR HOY' THEN 1 ELSE 0 END) AS llamar_hoy,
                   SUM(CASE WHEN veredicto='REVISAR' THEN 1 ELSE 0 END) AS revisar,
                   SUM(CASE WHEN veredicto='DESCARTAR' THEN 1 ELSE 0 END) AS descartar,
                   AVG(rentabilidad_bruta) AS rent_media,
                   AVG(precio) AS precio_medio
            FROM inmuebles
            """
        ).fetchone()

    mejor = None
    with _conexion() as con2:
        row_mejor = con2.execute(
            "SELECT * FROM inmuebles WHERE veredicto='LLAMAR HOY' "
            "ORDER BY puntuacion DESC LIMIT 1"
        ).fetchone()
        if row_mejor:
            mejor = _fila_a_modelo(row_mejor)

    return {
        "total": row["total"] or 0,
        "llamar_hoy": row["llamar_hoy"] or 0,
        "revisar": row["revisar"] or 0,
        "descartar": row["descartar"] or 0,
        "rentabilidad_media": round(row["rent_media"] or 0.0, 1),
        "precio_medio": round(row["precio_medio"] or 0.0, 1),
        "mejor_oportunidad": mejor.model_dump() if mejor else None,
    }


def registrar_importacion(nombre: str, ruta: str, n: int) -> None:
    from datetime import datetime
    with _conexion() as con:
        con.execute(
            "INSERT INTO archivados (nombre, ruta, inmuebles_importados, fecha) VALUES (?,?,?,?)",
            (nombre, ruta, n, datetime.now().isoformat()),
        )


def historial_importaciones() -> list:
    with _conexion() as con:
        rows = con.execute(
            "SELECT * FROM archivados ORDER BY fecha DESC LIMIT 20"
        ).fetchall()
    return [dict(r) for r in rows]


def purge_all() -> None:
    """Vacía el inventario (usado en modo pruebas)."""
    with _conexion() as con:
        con.execute("DELETE FROM inmuebles")