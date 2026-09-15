# ---- Agente Analizador Inmobiliario · imagen de producción ----
# Imagen ligera (Debian slim) sin build tools: la app es Python puro.
# Compatible con Docker Compose local y con Render (escucha en $PORT).
FROM python:3.11-slim

# Evita archivos .pyc y buffering de logs (visibles con `docker logs -f`)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=Europe/Madrid

WORKDIR /app

# 1) Primero SOLO requirements: aprovecha la caché de capas de Docker.
#    Si solo cambias el código, la instalación de deps no se repite.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 2) Código de la aplicación (sin datos locales: data/ e inputs/ NO se
#    copian a la imagen — se crean vacíos y van por volumen o por la
#    persistencia del host, nunca 'bakeados' en el contenedor).
COPY run.py ./
COPY src ./src
COPY templates ./templates
COPY static ./static

# 3) Directorios persistentes: existen al arrancar y pertenecen al usuario
#    no privilegiado para que la app pueda escribir config.json e inmuebles.db
#    sin ser root (también /tmp, donde uvicorn puede escribir).
RUN mkdir -p /app/data /app/inputs /tmp && \
    chown -R 1000:1000 /app /tmp

# Seguridad: run como usuario sin privilegios (mejor práctica en cloud)
USER 1000

# Render asigna el puerto vía $PORT (p. ej. 10000); local cae a 8000.
EXPOSE 8000

# Un worker: suficiente para el dashboard y ajustado a la RAM del plan
# gratis de Render (~512 MB); escala subiendo WEB_CONCURRENCY si hiciera falta.
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}"]