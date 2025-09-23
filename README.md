# Dantive Regulatory Bot

Dantive Regulatory Bot (RegBot) is a minimal retrieval‑augmented generation stack for exploring regulatory documents.  It wires together a FastAPI backend, a Streamlit UI, and an Ollama‑powered embedding and language model pipeline backed by Qdrant and PostgreSQL.

## Repository layout

- `apps/api` – FastAPI service exposing `/health`, `/ask`, and `/ask_stream` endpoints.
- `apps/ui` – Streamlit front‑end for chatting with the API.
- `apps/data` – sample PDFs that can be embedded into Qdrant.
- `infra` – Docker Compose stack for PostgreSQL, Qdrant, Ollama, the API, and the UI.
- `services` – lightweight Docker build contexts used by the compose file.
- `scripts` – PowerShell helpers for bootstrapping, building, and seeding.
- `seed_qdrant.py` – embeds local documents with Ollama and upserts them into Qdrant.

## Getting started

1. **Install prerequisites**: Docker and Docker Compose. Windows users can run the PowerShell scripts in `scripts/`.
2. **Bootstrap the stack**:
   ```powershell
   # from the repo root
   powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
   ```
   The script pulls base images, builds the API/UI images, starts PostgreSQL, Qdrant, and Ollama, then launches the API and UI.
3. **Access the services**:
   - API: `http://localhost:8000` – health check at `/health`, text generation at `/ask` and `/ask_stream`.
   - UI: `http://localhost:8501` – Streamlit interface for querying models.

## Seeding Qdrant with local documents

Place PDFs or text files under `apps/data` and run the seeding script inside the API container:

```bash
# inside the repo root or API container
python seed_qdrant.py
```

The script chunks each document, generates embeddings through Ollama, and stores them in the Qdrant collection `regdocs_v1`.

## Development notes

The API and UI are written in Python 3.11.  The Docker Compose file under `infra/` defines the development environment and mounts the repository so code changes are picked up immediately.

## RunPod startup instructions

Follow these steps to launch the stack on a fresh RunPod workspace.

1. **Container startup command** – configure the pod with SSH access and a startup hook. In the RunPod UI paste the following into the startup command field:

   ```bash
   bash -lc 'set -euo pipefail
   export DEBIAN_FRONTEND=noninteractive

   # --- packages (idempotent) ---
   apt-get update -y || true
   command -v nano >/dev/null 2>&1 || apt-get install -y nano
   dpkg -s openssh-server >/dev/null 2>&1 || apt-get install -y openssh-server

   # --- sshd prep & hardening ---
   mkdir -p /var/run/sshd
   [ -f /etc/ssh/ssh_host_rsa_key ] || ssh-keygen -A
   sed -i "s/^#\?PermitRootLogin .*/PermitRootLogin prohibit-password/" /etc/ssh/sshd_config || true
   sed -i "s/^#\?PasswordAuthentication .*/PasswordAuthentication no/" /etc/ssh/sshd_config || true
   sed -i "s/^#\?PubkeyAuthentication .*/PubkeyAuthentication yes/" /etc/ssh/sshd_config || true

   # --- authorized key (yours) ---
   mkdir -p /root/.ssh && chmod 700 /root/.ssh
   PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKKC83QoqQ+ysPCx75nQXtR4KinE2rjk73sN/3svGgM1 macbook"
   grep -qxF "$PUBKEY" /root/.ssh/authorized_keys 2>/dev/null || echo "$PUBKEY" >> /root/.ssh/authorized_keys
   chmod 600 /root/.ssh/authorized_keys

   # --- start sshd if not running ---
   pgrep -x sshd >/dev/null 2>&1 || /usr/sbin/sshd
   ( ss -lntp 2>/dev/null || netstat -lntp 2>/dev/null ) | grep -q ":22" || echo "WARN: sshd may not be listening on :22"

   # --- run your startup script, fallback to sleep for debug ---
   if [ -x /workspace/startup_pod.sh ]; then
     /workspace/startup_pod.sh || { echo "startup_pod.sh failed — sleeping forever for debug"; sleep infinity; }
   else
     echo "No /workspace/startup_pod.sh — sleeping forever for debug"
     sleep infinity
   fi
   '
   ```

2. **Update the SSH config on macOS** – edit your local SSH configuration to match the RunPod pod by running:

   ```bash
   nano ~/.ssh/config
   ```

3. **Create `/workspace/startup_pod.sh`** – after connecting through VS Code over SSH, create the startup script with the following contents:

   ```bash
   #!/usr/bin/env bash
   set -euxo pipefail

   # ========= config =========
   APP_DIR=/workspace/dantive-regbot
   PGDATA=/workspace/postgres
   QDRANT_DIR=/workspace/qdrant
   OLLAMA_DIR=/workspace/ollama
   BIN_DIR=/workspace/bin

   API_PORT=${API_PORT:-8000}
   UI_PORT=${UI_PORT:-8501}
   QDRANT_PORT=${QDRANT_PORT:-6333}
   OLLAMA_PORT=${OLLAMA_PORT:-11434}

   POSTGRES_USER=${POSTGRES_USER:-rag}
   POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-ragpwd}
   POSTGRES_DB=${POSTGRES_DB:-ragdb}

   # Models that should be present in Ollama cache
   export OLLAMA_MODELS=${OLLAMA_MODELS:-mistral:7b-instruct,nomic-embed-text}

   # Qdrant collection the API expects
   QDRANT_COLLECTION=${QDRANT_COLLECTION:-regdocs_v1}
   QDRANT_VECTOR_SIZE=${QDRANT_VECTOR_SIZE:-768}
   QDRANT_DISTANCE=${QDRANT_DISTANCE:-Cosine}

   # Optional: API proxy host for UI; otherwise UI hits 127.0.0.1
   if [ -n "${API_PROXY_HOST:-}" ]; then
     UI_API_URL="https://${API_PROXY_HOST}"
   else
     UI_API_URL="http://127.0.0.1:${API_PORT}"
   fi
   # ========= end config =========

   apt-get update
   DEBIAN_FRONTEND=noninteractive apt-get install -y \
     curl git build-essential python3-pip python3-venv supervisor \
     postgresql postgresql-contrib libpq-dev ca-certificates jq \
     pciutils lshw

   # --- Qdrant (static binary) ---
   if ! command -v qdrant >/dev/null 2>&1; then
     QV=${QV:-v1.12.3}
     TMP="$(mktemp -d)"
     (
       cd "$TMP"
       curl -fsSL "https://github.com/qdrant/qdrant/releases/download/${QV}/qdrant-x86_64-unknown-linux-gnu.tar.gz" | tar xz
       if [ -f qdrant ]; then
         install -m 0755 qdrant /usr/local/bin/qdrant
       else
         install -m 0755 */qdrant /usr/local/bin/qdrant
       fi
     )
     rm -rf "$TMP"
   fi

   # --- Ollama ---
   if ! command -v ollama >/dev/null 2>&1; then
     curl -fsSL https://ollama.com/install.sh | sh
   fi

   # Dirs & perms
   mkdir -p "$PGDATA" "$QDRANT_DIR" "$OLLAMA_DIR" "$BIN_DIR" \
            /var/log/supervisor /var/run/postgresql /var/run/supervisor
   chown -R postgres:postgres /var/run/postgresql "$PGDATA"
   chmod 2775 /var/run/postgresql

   # --- Postgres init (first boot) ---
   if [ ! -f "$PGDATA/PG_VERSION" ]; then
     chown -R postgres:postgres "$PGDATA"
     runuser -u postgres -- /usr/lib/postgresql/*/bin/initdb -D "$PGDATA"
     echo "listen_addresses='*'" >> "$PGDATA/postgresql.conf"
     echo "port=5432" >> "$PGDATA/postgresql.conf"
     echo "host all all 0.0.0.0/0 trust" >> "$PGDATA/pg_hba.conf"
   fi

   # --- Bootstrap PG user/db exactly once ---
   BOOTSTRAP_FLAG="$PGDATA/.bootstrapped"
   if [ ! -f "$BOOTSTRAP_FLAG" ]; then
     echo "Bootstrapping Postgres user/db..."
     # stale PID guard
     if [ -f "$PGDATA/postmaster.pid" ] && ! pgrep -u postgres -f "postgres.*-D $PGDATA" >/dev/null; then
       rm -f "$PGDATA/postmaster.pid"
     fi
     runuser -u postgres -- /usr/lib/postgresql/*/bin/pg_ctl -D "$PGDATA" -l "$PGDATA/postgres.log" -w start

     psql -U postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'" | grep -q 1 \
       || psql -U postgres -c "CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}';"

     psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'" | grep -q 1 \
       || psql -U postgres -c "CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};"

     runuser -u postgres -- /usr/lib/postgresql/*/bin/pg_ctl -D "$PGDATA" -w stop
     touch "$BOOTSTRAP_FLAG"
   else
     echo "Postgres bootstrap already done; skipping."
   fi

   # --- Fetch app code (clone or pull) ---
   if [ ! -d "$APP_DIR/.git" ]; then
     git clone --branch main https://github.com/spiest78/dantive-regbot.git "$APP_DIR"
   else
     (cd "$APP_DIR" && git fetch --all && git reset --hard origin/main)
   fi

   # --- Python envs (split: API and UI) ---
   # API: allow protobuf 6.x (for grpcio-tools 1.75.0)
   python3 -m venv "${APP_DIR}/.venv_api"
   . "${APP_DIR}/.venv_api/bin/activate"
   pip install -U pip
   if [ -f "${APP_DIR}/apps/api/requirements.txt" ]; then
     # If your API reqs file doesn’t pin protobuf, this line enforces a compatible one.
     pip install -r "${APP_DIR}/apps/api/requirements.txt" "protobuf>=6.31.1,<7"
   fi
   deactivate

   # UI: keep protobuf <6 (Streamlit 1.38 constraint)
   python3 -m venv "${APP_DIR}/.venv_ui"
   . "${APP_DIR}/.venv_ui/bin/activate"
   pip install -U pip
   if [ -f "${APP_DIR}/apps/ui/requirements.txt" ]; then
     # Force protobuf into a <6 version; choose a stable, recent 5.x
     pip install -r "${APP_DIR}/apps/ui/requirements.txt" "protobuf>=5.29.0,<6"
   fi
   deactivate

   # --- One-shot helper: wait for Qdrant then ensure the collection exists ---
   cat >"${BIN_DIR}/qdrant_init.sh" <<'SH'
   #!/usr/bin/env bash
   set -euo pipefail
   QPORT="${QDRANT_PORT:-6333}"
   CNAME="${QDRANT_COLLECTION:-regdocs_v1}"
   VSIZE="${QDRANT_VECTOR_SIZE:-768}"
   DIST="${QDRANT_DISTANCE:-Cosine}"

   # Wait for Qdrant readiness (up to ~60s)
   for i in {1..60}; do
     if curl -fsS "http://127.0.0.1:${QPORT}/collections" >/dev/null 2>&1; then
       break
     fi
     sleep 1
   done

   # Create collection if missing
   if ! curl -fsS "http://127.0.0.1:${QPORT}/collections/${CNAME}" >/dev/null 2>&1; then
     echo "Creating Qdrant collection '${CNAME}'..."
     curl -fsS -X PUT "http://127.0.0.1:${QPORT}/collections/${CNAME}" \
       -H 'Content-Type: application/json' \
       -d "{\"vectors\":{\"size\":${VSIZE},\"distance\":\"${DIST}\"}}"
   fi
   SH
   chmod +x "${BIN_DIR}/qdrant_init.sh"

   # --- One-shot helper: Ollama model pull (Option B) ---
   cat >"${BIN_DIR}/ollama_pull.sh" <<'SH'
   #!/usr/bin/env bash
   set -euo pipefail
   PORT="${OLLAMA_PORT:-11434}"

   # Wait up to ~60s for Ollama to respond, then pull requested models
   for i in {1..30}; do
     if curl -fsS "http://127.0.0.1:${PORT}/api/tags" >/dev/null 2>&1; then
       IFS=, read -ra MODELS <<< "${OLLAMA_MODELS:-mistral:7b-instruct,nomic-embed-text}"
       for m in "${MODELS[@]}"; do
         ollama pull "$(echo "$m" | xargs)" || true
       done
       exit 0
     fi
     sleep 2
   done
   echo "Ollama not ready after ~60s, skipping model pull"
   SH
   chmod +x "${BIN_DIR}/ollama_pull.sh"

   # --- Supervisord config ---
   POSTGRES_BIN="$(ls /usr/lib/postgresql/*/bin/postgres 2>/dev/null | head -n1)"

   cat >/workspace/supervisord.conf <<SUP
   [supervisord]
   nodaemon=true
   logfile=/var/log/supervisor/supervisord.log

   [unix_http_server]
   file=/var/run/supervisor.sock
   chmod=0700
   chown=root:root

   [supervisorctl]
   serverurl=unix:///var/run/supervisor.sock

   [rpcinterface:supervisor]
   supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

   ; Lower priority numbers start first
   [program:postgres]
   priority=50
   command=${POSTGRES_BIN} -D ${PGDATA}
   user=postgres
   autorestart=true
   stdout_logfile=/var/log/supervisor/postgres.out
   stderr_logfile=/var/log/supervisor/postgres.err

   [program:qdrant]
   priority=100
   command=/bin/bash -lc "QDRANT__STORAGE__STORAGE_PATH=${QDRANT_DIR} QDRANT__SERVICE__HTTP_PORT=${QDRANT_PORT} qdrant"
   autorestart=true
   stdout_logfile=/var/log/supervisor/qdrant.out
   stderr_logfile=/var/log/supervisor/qdrant.err

   [program:qdrant-init]
   priority=110
   command=/bin/bash -lc "${BIN_DIR}/qdrant_init.sh"
   autorestart=false
   startretries=0
   stdout_logfile=/var/log/supervisor/qdrant-init.out
   stderr_logfile=/var/log/supervisor/qdrant-init.err

   [program:ollama]
   priority=120
   command=/bin/bash -lc "OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=30m OLLAMA_HOST=0.0.0.0:${OLLAMA_PORT} ollama serve"
   autorestart=true
   stdout_logfile=/var/log/supervisor/ollama.out
   stderr_logfile=/var/log/supervisor/ollama.err
   environment=\
   NVIDIA_VISIBLE_DEVICES="all",\
   NVIDIA_DRIVER_CAPABILITIES="compute,utility"

   [program:ollama-pull]
   priority=130
   command=/bin/bash -lc "/workspace/bin/ollama_pull.sh"
   autorestart=false
   startretries=0
   stdout_logfile=/var/log/supervisor/ollama-pull.out
   stderr_logfile=/var/log/supervisor/ollama-pull.err
   environment=OLLAMA_MODELS="${OLLAMA_MODELS}"

   [program:api]
   priority=200
   directory=${APP_DIR}/apps/api
   command=/bin/bash -lc ". ${APP_DIR}/.venv_api/bin/activate; uvicorn main:app --host 0.0.0.0 --port ${API_PORT} --proxy-headers --forwarded-allow-ips='*'"
   autorestart=true
   stdout_logfile=/var/log/supervisor/api.out
   stderr_logfile=/var/log/supervisor/api.err
   environment=DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}",QDRANT_URL="http://127.0.0.1:${QDRANT_PORT}",OLLAMA_URL="http://127.0.0.1:${OLLAMA_PORT}",QDRANT_COLLECTION="${QDRANT_COLLECTION}",OLLAMA_DEFAULT_MODEL="mistral:7b-instruct",OLLAMA_CONNECT_TIMEOUT="10",OLLAMA_READ_TIMEOUT="600"

   [program:ui]
   priority=300
   directory=${APP_DIR}/apps/ui
   command=/bin/bash -lc ". ${APP_DIR}/.venv_ui/bin/activate; streamlit run streamlit_app.py --server.port ${UI_PORT} --server.address 0.0.0.0 --server.headless=true --server.enableCORS=false --server.enableXsrfProtection=false --server.enableWebsocketCompression=false --browser.gatherUsageStats=false"
   autorestart=true
   stdout_logfile=/var/log/supervisor/ui.out
   stderr_logfile=/var/log/supervisor/ui.err
   environment=API_URL=${UI_API_URL}
   SUP

   # Hand off to supervisord
   exec supervisord -c /workspace/supervisord.conf
   ```

4. **Make the startup script executable** – run the following command inside the pod:

   ```bash
   chmod +x /workspace/startup_pod.sh
   ```

5. **Configure the proxy URL** – update the Streamlit UI to reach the API through the RunPod proxy:

   ```bash
   API_PROXY_HOST="iqgqaneuchztq5-8000.proxy.runpod.net"
   API_URL_VAL="https://${API_PROXY_HOST}"
   CONF="/workspace/supervisord.conf"

   # Update or insert the environment line inside [program:ui]
   if awk '
     BEGIN{in=0; found=0}
     /^\[program:ui\]/{in=1}
     in && /^environment=API_URL=/{found=1}
     in && (/^\[program:/ && $0 !~ /^\[program:ui\]/){in=0}
     END{exit(found?0:1)}
   ' "$CONF"; then
     # Already present → replace the line
     sed -i "/\[program:ui\]/,/^\[program:/ s#^\s*environment=API_URL=.*#environment=API_URL=${API_URL_VAL}#" "$CONF"
   else
     # Not present → add after autorestart=true
     sed -i "/\[program:ui\]/,/^\[program:/ {/^[[:space:]]*autorestart=true/a environment=API_URL=${API_URL_VAL}/}" "$CONF"
   fi

   # Tell supervisord to reload just the UI section
   supervisorctl -c "$CONF" reread
   supervisorctl -c "$CONF" update
   supervisorctl -c "$CONF" restart ui
   ```

### Required RunPod ports

Expose the following ports in the RunPod UI so each service is reachable:

- HTTP: `8501`, `8000`
- TCP: `11434`, `6333`, `5432`, `22`

