cd /workspace/dantive-regbot

cat > infra/bootstrap_deps.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

echo "[bootstrap] ensuring base tools…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y curl ca-certificates jq tar xz-utils gzip coreutils

# Supervisor (needed by startup)
if ! command -v supervisord >/dev/null 2>&1; then
  apt-get install -y supervisor
fi

# Postgres server (provides postgres/initdb). Some Debian images don't add it to PATH.
if ! command -v postgres >/dev/null 2>&1; then
  apt-get install -y postgresql
fi
# Ensure postgres is on PATH (symlink the real binary if necessary)
if ! command -v postgres >/dev/null 2>&1; then
  PG_BIN="$(find /usr/lib/postgresql -type f -name postgres 2>/dev/null | head -n1 || true)"
  if [ -n "${PG_BIN:-}" ]; then
    ln -sf "$PG_BIN" /usr/local/bin/postgres
  fi
fi

# Ollama (skip systemd in containers)
if ! command -v ollama >/dev/null 2>&1; then
  echo "[bootstrap] installing ollama (no systemd)…"
  OLLAMA_SKIP_SYSTEMD=1 curl -fsSL https://ollama.com/install.sh | sh
fi

# Qdrant (static binary). Use "latest/download" to avoid fragile version URLs.
if ! command -v qdrant >/dev/null 2>&1; then
  echo "[bootstrap] installing qdrant binary…"
  TMP="/tmp/qdrant.tar.gz"
  URL="https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz"
  # Retry logic
  for i in 1 2 3; do
    curl -fL "$URL" -o "$TMP" && break || sleep 2
  done
  # Quick sanity check: ensure it's a gzip tar
  if ! gzip -t "$TMP" >/dev/null 2>&1; then
    echo "[bootstrap] ERROR: downloaded Qdrant archive is not gzip; aborting."
    ls -l "$TMP" || true
    file "$TMP" || true
    exit 1
  fi
  # Extract only the 'qdrant' binary from the archive (strip leading dirs)
  TMPDIR="$(mktemp -d)"
  tar -xzf "$TMP" -C "$TMPDIR"
  QD_BIN="$(find "$TMPDIR" -type f -name qdrant | head -n1 || true)"
  if [ -z "${QD_BIN:-}" ]; then
    echo "[bootstrap] ERROR: qdrant binary not found in archive."
    find "$TMPDIR" -maxdepth 3 -type f | sed 's/^/[bootstrap]   /'
    exit 1
  fi
  install -m 0755 "$QD_BIN" /usr/local/bin/qdrant
  rm -rf "$TMPDIR" "$TMP"
fi

# Ensure runtime dirs (persist on NV)
mkdir -p /workspace/{postgres,qdrant,ollama,datasets,markers,logs}

# Initialize Postgres data dir if empty (only once)
if [ -z "$(ls -A /workspace/postgres 2>/dev/null || true)" ]; then
  echo "[bootstrap] initializing postgres data dir…"
  if command -v initdb >/dev/null 2>&1; then
    initdb -D /workspace/postgres
  else
    echo "[bootstrap] initdb not found; postgres will auto-init on first run if supported."
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
EOF

chmod +x infra/bootstrap_deps.sh
