# 🚀 Despliegue 24/7 del Agente Analizador Inmobiliario

Guía rápida para dejar el agente corriendo **sin apagarse nunca** en la nube:
**Oracle Cloud Free Tier** (gratis de por vida) o un **VPS de Hetzner** (~3 €/mes).
Dos rutas, la que prefieras: **Docker** o **Systemd**.

---

## 1. Qué necesitas (1 hora total)

| Recurso | Para qué |
|---|---|
| Una cuenta en Oracle Cloud o Hetzner | El servidor donde vive la app |
| Puerto **8000** abierto | El dashboard (o usa un proxy/reverse con dominio) |
| Un bot de Telegram (opcional) | Crear con @BotFather → token + chat ID |
| Te reseñas: `data/`, `inputs/` | Son los volúmenes persistentes, no se pierden |

> **Dónde están tus datos**: `config.json` y `inmuebles.db` viven en `data/`.
> Los exports (JSON/CSV/TXT) van en `inputs/`. Ambos se montan por volumen y
> **sobreviven a reinicios, updates y apagones**.

---

## 2. Preparar los secretos (opcional, recomendado)

Copia el ejemplo y rellénalo **fuera del repo** (nunca se commitean):

```bash
cp .env.example .env
nano .env   # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BASE_URL
```

Si no tocas Telegram, deja `TELEGRAM_*` vacíos: la app usa `data/config.json`
como hasta ahora y el panel ⚙️ sigue funcionando para todo.

---

## 3. Ruta A — Docker Compose (la más cómoda)

```bash
# 1) Copia tu proyecto al servidor
scp -r -i ~/.ssh/llave.pem agente_inmobiliario ubuntu@<IP>:/opt/

# 2) Entra por SSH
ssh -i ~/.ssh/llave.pem ubuntu@<IP>
cd /opt/agente_inmobiliario

# 3) Instala Docker (si aún no está)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# cierra sesión y vuelve a entrar para que el grupo surta efecto

# 4) Prepara las carpetas de datos ANTES del primer arranque.
#    El contenedor corre como uid 1000; si las carpetas quedan en manos
#    de root (p. ej. en Hetzner, donde entras como root) el contenedor
#    no podría guardar config.json a partir de ahí.
mkdir -p data inputs
sudo chown -R 1000:1000 data inputs   # necesario solo si entras como root

# 5) Arranca (con .env si lo creaste)
docker compose up -d --build

# 6) Verifica
docker compose ps                 # Estado: Up, healthy
curl http://127.0.0.1:8000/api/resumen
docker compose logs -f app        # Ver logs en vivo
```

- **24/7 garantizado por `restart: unless-stopped`**: se levanta solo tras reinicios
  del sistema, crashes y hasta después de `docker stop`.
- **Update sin perder datos**:
  ```bash
  git pull || scp -r ...   # nuevas versiones del código
  docker compose up -d --build   # reconstruye y redepliega sin borrar data/
  ```

**Nota de seguridad**: si vas a exponerlo, pon delante un Caddy/NGINX con HTTPS y
cambia el mapeo a `127.0.0.1:8000:8000` (solo local, el proxy es el que sale a Internet).

---

## 4. Ruta B — Systemd (sin Docker, Python nativo)

Para un VPS pequeño donde no quieres Docker, con la misma persistencia.

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip
cd /opt/agente_inmobiliario          # copia aquí el proyecto

python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# Crea el .env con los secretos (los carga el servicio)
cp .env.example .env && nano .env
```

Crea el servicio:

```bash
sudo tee /etc/systemd/system/agente-inmobiliario.service > /dev/null <<'EOF'
[Unit]
Description=Agente Analizador Inmobiliario
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/agente_inmobiliario
EnvironmentFile=/opt/agente_inmobiliario/.env
ExecStart=/opt/agente_inmobiliario/venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
# Con el tiempo, amplía: --workers 2 cuando quieras
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now agente-inmobiliario   # arranca y queda activo tras reboot

# Comandos útiles
sudo systemctl status agente-inmobiliario   # estado
sudo journalctl -u agente-inmobiliario -f    # logs en vivo
sudo systemctl restart agente-inmobiliario   # tras una actualización del código
```

Con `Restart=always` el proceso se re-lanza solo si muere o se apaga la máquina.

---

## 5. Oracle Cloud Free Tier (gratis de por vida)

1. Crea la cuenta en https://www.oracle.com/cloud/free/ (pide tarjeta para
   verificar, **no te cobran** las instancias Free Tier).
2. **Compute → Instances → Create instance**:
   - Imagen: **Ubuntu 24.04** (arm64). 
   - Shape: **VM.Standard.A1.Flex** (ARM Ampere, **siempre gratis**, 4 OCPU/24 GB).
     ⚠️ A veces la A1 está agotada en tu región: cambia de región o usa **E2.1.Micro**
     (Intel, 1 OCPU/1 GB, también gratis) — suficiente para esta app.
   - SSH key: genera y descarga la `.pem` (la guardas tú).
   - Boot volume: deja el mínimo (50 GB) — con esto **no pagas nada**.
3. **Networking → Security List** de tu VCN: añade regla de entrada
   **TCP 8000** (source `0.0.0.0/0`); o no la añadas y usa el túnel SSH.
4. Conecta y despliega:
   ```bash
   ssh -i ~/.ssh/llave.pem ubuntu@<IP_del_servidor>
   # Ruta A (Docker) o Ruta B (Systemd), líneas de arriba
   ```
5. Abre `http://<IP>:8000` desde tu navegador.

> **Ahórrate el Caddy/HTTPS**: para uso personal (panel + bot), `http://IP:8000`
> basta. Si algún día lo expones a más gente, pon dominio + HTTPS.

---

## 6. Hetzner VPS (~3 €/mes)

1. Alta en https://www.hetzner.com/cloud → *CX22 ≈ 3 €/mes* (2 vCPU, 4 GB RAM; la
   serie ARM sale aún más barata). Elige **Ubuntu 24.04**.
2. Copia la clave SSH: **Settings → Security → SSH Keys** (pega tu `cat ~/.ssh/id_ed25519.pub`).
3. Crea la instancia y copia la IP. Conecta y despliega igual que en Oracle:
   ```bash
   ssh root@<IP>                    # Hetzner usa root por defecto
   # Ruta A (Docker) o Ruta B (Systemd)
   ```
4. Síguete los pasos de la Ruta A o B con `root` en vez de `ubuntu`
   (ajusta el `User=` del unit).

---

## 7. Verificación final (las 3 funciones)

```bash
curl http://<IP>:8000/api/config        # debe devolver JSON con los ajustes
curl -X POST http://<IP>:8000/api/config \
  -H 'Content-Type: application/json' \
  -d '{"zona_objetivo":"Jerez de la Frontera"}'   # guarda ajustes y recalcula

# 1) Telegram: crea un bot en @BotFather, consigue token + tu chat ID
#    (escribe a @userinfobot para conocer tu chat_id).
#    Pónlos en .env o en el panel ⚙️.

# 2 y 3) Panel y Maps: abre http://<IP>:8000 — cada tarjeta trae
#    "🧭 Mapa" (Google Maps por zona) y "📲 Telegram".
```

Después de probar, sube tu primer export a `inputs/` o pega un anuncio y verás
la alerta llegar a Telegram con el enlace «Abrir panel del agente».

---

## 8. Backups (no perder nada)

Los datos viven en `data/` y `inputs/`. Copia esas carpetas a otro sitio con cron:

```bash
# Snapshot diario comprimido de los datos, los 7 últimos
mkdir -p ~/backups
cat > /tmp/snapshot.sh <<'EOF'
#!/bin/bash
cd /opt/agente_inmobiliario
sudo tar czf ~/backups/agente-$(date +%F-%H).tar.gz data inputs
ls -t ~/backups/agente-*.tar.gz | tail -n +8 | xargs -r rm
EOF
chmod +x /tmp/snapshot.sh
sudo cp /tmp/snapshot.sh /usr/local/bin/snapshot-agente
sudo echo "17 3 * * * root /usr/local/bin/snapshot-agente" > /etc/cron.d/agente-backup
```

Descarga luego el `.tar.gz` desde tu máquina local (o súbelo a un bucket) si lo
quieres en otro sitio.

---

## TLC / preguntas frecuentes

- **¿Dónde toco los umbrales?** En el panel ⚙️ del dashboard (se guarda solo).
- **Quité el bot y sigue activo** → revisa `.env`: si `TELEGRAM_BOT_TOKEN` está
  definido, el despliegue manda sobre el panel. Vacíalo o cambia el secreto.
- **Puerto 8000 ocupado** → cambia el mapeo en `docker-compose.yml`
  (`"8080:8000"`) o el `--port` del unit de systemd.
- **App en ARM (Oracle)** → sin problema: Python y estas dependencias son
  multiplataforma; el `python:3.11-slim` de Docker ya soporta arm64.