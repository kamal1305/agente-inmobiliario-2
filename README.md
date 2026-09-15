# 🏠 Agente Analizador Inmobiliario — Jerez de la Frontera

Herramienta para detectar oportunidades de inversión inmobiliaria a partir de
anuncios sueltos (pegados a mano) o archivos exportados (n8n, Google Sheets, CSV).
Analiza, puntúa de 0 a 100, marca riesgos y prioriza con quién llamar hoy.

## ⚡ Arranque rápido

```bash
# (ya configurado) entorno virtual + dependencias:
python -m venv venv
venv\\Scripts\\activate
pip install -r requirements.txt

# Lanzar el servidor local:
python run.py            # uvicorn en http://127.0.0.1:8000
```

Abre **http://127.0.0.1:8000** en el navegador.

## 🗂 Estructura

```
agente_inmobiliario/
├── data/           # SQLite inmuebles.db (se crea solo) + WAL
├── inputs/         # 🛑 AQUÍ dejas los CSV/JSON/TXT a importar
├── src/
│   ├── config.py       # Umbrales y pesos del scoring (edita aquí)
│   ├── scoring.py      # Motor: parseo, puntuación, veredictos, red flags
│   ├── parsers.py      # Detecta y parsea cualquier archivo de /inputs
│   ├── analizador.py   # Orquestación + deduplicación
│   ├── database.py     # SQLite: inventario, resumen, importados
│   ├── main.py         # API FastAPI
│   └── models.py       # Modelos Pydantic
├── templates/index.html  # Dashboard (Tailwind zinc)
├── static/
└── run.py
```

## 🎯 Reglas de inversión (configurables en `src/config.py`)

| Variable | Valor |
|---|---|
| Zona objetivo | Jerez de la Frontera |
| Precio | 75.000 – 120.000 € |
| Tope €/m² | 1.600 € |
| Alquiler zona | 9 €/m²/mes (microzonas afinan) |
| Rentabilidad bruta mín. | 7 % |

**Puntuación (100 pts):** descuento 35 · rentabilidad 25 · ubicación 15 ·
reforma 10 · liquidez 10 · documentación 5.

**Veredictos:** 🟢 Llamar hoy (≥75) · 🟡 Revisar (55–74) · 🔴 Descartar (<55).

**Banderas rojas → DESCARTAR inmediato:** ocupado/a, sin posesión, no visitable,
subasta, problemas/sin cédula, derramas pendientes, bajo interior oscuro, okupa.

## 📥 Importar datos

1. Coloca tu export (JSON/JSONL, CSV, TXT/MD/HTML) en `inputs/`.
2. En el dashboard pulsa **«Importar /inputs»** (o sube un archivo suelto con
   **«Subir archivo»**).
3. El parser autodetecta columnas (`url`, `precio`, `m²`, `zona`, `titulo`, `descripcion`)
   y deduplica por URL, por similitud de texto o por precio+m²+zona.

## 🔌 API

- `GET /api/resumen` — KPIs
- `GET /api/inmuebles?texto=&veredicto=&rentabilidad_min=&orden=` — listar/filtrar
- `POST /api/analizar` — analizar un anuncio pegado
- `POST /api/importar` — escanear `/inputs`
- `POST /api/upload` — subir archivo
- `PATCH /api/inmuebles/{id}/estado` — CRM (nuevo/analizado/contactado/descartado)
- `DELETE /api/inmuebles/{id}` — eliminar

Docs interactivas en `http://127.0.0.1:8000/docs`.