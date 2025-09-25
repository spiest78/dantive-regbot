#!/usr/bin/env bash
set -euo pipefail

OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
MODEL_LIST_FILE="${MODEL_LIST_FILE:-/workspace/dantive-regbot/ops/model-list.txt}"
MARKER="${MARKER:-/workspace/markers/models_pulled.txt}"

mkdir -p /workspace/markers /workspace/logs

echo "[pull-models] waiting for Ollama at ${OLLAMA_URL}…"
for i in {1..60}; do
  if curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null; then
    break
  fi
  sleep 2
done

has_model() {
  curl -fsS "${OLLAMA_URL}/api/show" -d "{\"name\":\"$1\"}" >/dev/null
}

pull_model() {
  echo "[pull-models] pulling: $1"
  curl -fsS "${OLLAMA_URL}/api/pull" -d "{\"name\":\"$1\"}"
}

# Allow blank lines and comments beginning with '#'
while IFS= read -r line || [[ -n "${line:-}" ]]; do
  line="${line%%#*}"
  line="$(echo "${line}" | xargs || true)"
  [[ -z "${line}" ]] && continue

  name="${line}"
  echo "[pull-models] ensure: ${name}"
  if has_model "${name}"; then
    echo "[pull-models] present: ${name}"
    continue
  fi

  if ! pull_model "${name}"; then
    echo "[pull-models] WARN: failed to pull ${name}" >&2
  fi
done < "${MODEL_LIST_FILE}"

date -u +"%F %T UTC" > "${MARKER}"
echo "[pull-models] done."
