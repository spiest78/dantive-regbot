#!/usr/bin/env bash
set -euo pipefail

echo "[bootstrap] ensuring base tools…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y curl ca-certificates jq

# Supervisor (safety; your start script already installs it, but keep it here too)
if ! command -v supervisord >/dev/null 2>&1; then
  apt-get install -y supervisor
fi

# Postgres server (binary provides `postgres` and `initdb`)
if ! command -v postgres >/dev/null 2>&1; then
  apt-get install -y postgresql
fi

# Ollama (installs to /usr/local/bin/ollama)
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

# Qdrant (static binary)
if ! command -v qdrant >/dev/null 2>&1; then
  QD_VER="v1.11.0"   # stable and matches your earlier server logs
  TMP="/tmp/qdrant.tar.gz"
  curl -L "https://github.com/qdrant/qdrant/releases/download/${QD_VER}/qdrant-${QD_VER}-x86_64-unknown-linux-gnu.tar.gz" -o "$TMP"
  tar -xzf "$TMP" -C /usr/local/bin --strip-components=1 qdrant-${QD_VER}-x86_64-unknown-linux-gnu/qdrant
  chmod +x /usr/local/bin/qdrant
fi

# Ensure runtime dirs (NV mounted)
mkdir -p /workspace/{postgres,qdrant,ollama,datasets,markers,logs}

# Initialize Postgres data dir if empty (only once)
if [ -z "$(ls -A /workspace/postgres 2>/dev/null || true)" ]; then
  echo "[bootstrap] initializing postgres data dir…"
  # Prefer initdb if present; otherwise postgres -D will initialize automatically on first run
  if command -v initdb >/dev/null 2>&1; then
    initdb -D /workspace/postgres
  fi
fi

# Minimal qdrant config if missing
if [ ! -f /workspace/qdrant/config.yaml ]; then
  cat > /workspace/qdrant/config.yaml <<YAML
storage:
  path: "/workspace/qdrant"
service:
  host: "0.0.0.0"
  http_port: 6333
  grpc_port: 6334
YAML
fi

echo "[bootstrap] done."
