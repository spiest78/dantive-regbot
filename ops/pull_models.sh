#!/usr/bin/env bash
set -euo pipefail
export OLLAMA_MODELS=/workspace/ollama
MARKER="/workspace/markers/models_pulled.txt"

if [[ -f "$MARKER" ]]; then
  echo "[pull-models] already done."
  exit 0
fi

# wait for ollama
until curl -sf http://127.0.0.1:11434/api/tags >/dev/null; do
  echo "waiting for ollama..."
  sleep 2
done

while read -r M || [[ -n "${M:-}" ]]; do
  [[ -z "$M" || "$M" =~ ^# ]] && continue
  echo "ensure model: $M"
  curl -sf http://127.0.0.1:11434/api/show -d "{\"name\":\"$M\"}" >/dev/null || \
    curl -sf http://127.0.0.1:11434/api/pull -d "{\"name\":\"$M\"}"
done < /workspace/dantive-regbot/ops/model-list.txt

date > "$MARKER"
echo "[pull-models] done."
