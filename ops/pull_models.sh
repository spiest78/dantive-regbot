#!/usr/bin/env bash
set -euo pipefail

: "${OLLAMA_HOST:=http://127.0.0.1:11434}"
: "${MARKER:=/workspace/markers/models_pulled.txt}"

# Preferred: explicit list of tags via env var
MODELS="${OLLAMA_PULL_LIST:-}"

if [[ -f "$MARKER" ]]; then
  echo "[pull-models] already done."
  exit 0
fi

# --- wait for ollama to come up ---
until curl -sf "${OLLAMA_HOST}/api/tags" >/dev/null; do
  echo "[pull-models] waiting for ollama..."
  sleep 2
done

# --- build list of models ---
if [[ -n "$MODELS" ]]; then
  IFS=',' read -r -a tags <<<"$MODELS"
else
  echo "[pull-models] reading models from ops/model-list.txt"
  mapfile -t tags < /workspace/dantive-regbot/ops/model-list.txt
fi

# --- pull each model ---
for M in "${tags[@]}"; do
  M="$(echo "$M" | xargs)"   # trim spaces
  [[ -z "$M" ]] && continue
  echo "[pull-models] ensure model: $M"

  # Only pull if show fails
  curl -sf "${OLLAMA_HOST}/api/show" \
       -d "{\"name\":\"$M\"}" >/dev/null || \
  curl -sf "${OLLAMA_HOST}/api/pull" \
       -d "{\"name\":\"$M\"}"
done

date > "$MARKER"
echo "[pull-models] done."
