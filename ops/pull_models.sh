#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/workspace/dantive-regbot"
LOG_DIR="/workspace/logs"
mkdir -p "$LOG_DIR"

export OLLAMA_HOST="127.0.0.1:11434"
export OLLAMA_MODELS="${OLLAMA_MODELS:-/workspace/ollama}"
mkdir -p "$OLLAMA_MODELS"

JQ_BIN="$(command -v jq || true)"

log() { echo "[pull_models] $*" | tee -a "$LOG_DIR/ollama-pull.log" >&2; }

wait_for_ollama() {
  local i
  for i in $(seq 1 90); do
    if curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  log "ERROR: Ollama API not reachable at ${OLLAMA_HOST} after 90s"
  return 1
}

have_model() {
  local tag="$1"
  # If jq is present, use it; otherwise a grep fallback.
  if [ -n "$JQ_BIN" ]; then
    curl -fsS "http://${OLLAMA_HOST}/api/tags" \
    | jq -e --arg n "$tag" '.models[].name | select(. == $n)' >/dev/null 2>&1
  else
    curl -fsS "http://${OLLAMA_HOST}/api/tags" \
    | grep -q "\"name\":\"${tag}\""
  fi
}

pull_if_missing() {
  local tag="$1"
  if have_model "$tag"; then
    log "✓ already present: ${tag}"
    return 0
  fi
  log "→ pulling ${tag}"
  if /usr/local/bin/ollama pull "$tag"; then
    log "✓ pulled: ${tag}"
    return 0
  fi

  # Common benign failure when a community tag is unavailable on the host registry.
  log "⚠️  could not pull ${tag}; skipping"
  return 0
}

# ---- build desired tag list ----
declare -a TAGS=()

# 1) repo-provided list if present
if [ -f "${REPO_DIR}/ops/model-list.txt" ]; then
  # remove comments and blanks
  while IFS= read -r line; do
    line="${line%%#*}"
    line="$(echo "$line" | xargs || true)"
    [ -n "${line}" ] && TAGS+=("$line")
  done < "${REPO_DIR}/ops/model-list.txt"
fi

# 2) sane defaults (include fallbacks for llama)
TAGS+=(
  "llama3.1:8b-instruct"
  "llama3:8b-instruct"
  "mistral:7b-instruct"
  "nomic-embed-text:latest"
)

# de-dup while preserving order
declare -A seen=()
declare -a uniq=()
for t in "${TAGS[@]}"; do
  if [ -z "${seen[$t]+x}" ]; then
    uniq+=("$t")
    seen[$t]=1
  fi
done
TAGS=("${uniq[@]}")

# ---- do the work ----
wait_for_ollama

for tag in "${TAGS[@]}"; do
  pull_if_missing "$tag"
done

log "done."
