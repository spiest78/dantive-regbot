#!/usr/bin/env bash
set -euo pipefail
MARKER="/markers/models_pulled.txt"

if [[ -f "$MARKER" ]]; then
  echo "[pull-models] already done."
  exit 0
fi

# wait for Ollama to be reachable
until curl -sf http://ollama:11434/api/tags > /dev/null; do
  echo "Waiting for Ollama..."
  sleep 2
done

while read -r M || [[ -n "$M" ]]; do
  [[ -z "$M" || "$M" =~ ^# ]] && continue
  echo "Ensuring model: $M"
  curl -sf http://ollama:11434/api/show -d "{\"name\":\"$M\"}" >/dev/null || \
    curl -sf http://ollama:11434/api/pull -d "{\"name\":\"$M\"}"
done < /models.txt

date > "$MARKER"
echo "[pull-models] done."
