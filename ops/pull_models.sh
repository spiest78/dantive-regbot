#!/usr/bin/env bash
set -euo pipefail

# Where Ollama listens and where models live
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
OLLAMA_MODELS="${OLLAMA_MODELS:-/workspace/ollama-store}"

# Absolute path to the binary to avoid PATH/dir confusion
OLLAMA_BIN="${OLLAMA_BIN:-/usr/local/bin/ollama}"

# Model sources: file takes precedence; env can override; final fallback list below
MODEL_LIST_FILE="${MODEL_LIST_FILE:-/workspace/dantive-regbot/ops/model-list.txt}"
DEFAULT_PULL_LIST="mistral:7b-instruct nomic-embed-text:latest llama3.1:8b-instruct llama3:8b-instruct llama3.2:3b-instruct"
READ_LIST=()

if [[ -f "$MODEL_LIST_FILE" ]]; then
  # Trim comments/blank lines
  mapfile -t READ_LIST < <(sed -e 's/#.*$//' -e 's/^[[:space:]]\+//' -e 's/[[:space:]]\+$//' "$MODEL_LIST_FILE" | awk 'NF>0')
fi

# Also allow OLLAMA_PULL_LIST="model1 model2" as an override
if [[ -n "${OLLAMA_PULL_LIST:-}" ]]; then
  # shellcheck disable=SC2206
  READ_LIST=(${OLLAMA_PULL_LIST})
fi

# Fallback if nothing specified
if [[ ${#READ_LIST[@]} -eq 0 ]]; then
  # shellcheck disable=SC2206
  READ_LIST=(${DEFAULT_PULL_LIST})
fi

MARKER_DIR="/workspace/markers"
mkdir -p "$MARKER_DIR" "$OLLAMA_MODELS"

# Wait for Ollama to be ready
echo "[pull-models] waiting for Ollama at ${OLLAMA_URL}…"
for i in {1..60}; do
  if curl -fsS "${OLLAMA_URL}/api/tags" > /dev/null; then
    break
  fi
  sleep 1
  if [[ $i -eq 60 ]]; then
    echo "Ollama not ready after ~60s, skipping model pull"
    exit 0
  fi
done

# Helper: true if model exists locally
have_model() {
  curl -fsS "${OLLAMA_URL}/api/show" -d "{\"name\":\"$1\"}" >/dev/null 2>&1
}

# Try to ensure each model once
for want in "${READ_LIST[@]}"; do
  # Some lists are written with commas; normalize
  want_clean="${want%,}"

  # Skip obvious empties
  [[ -z "$want_clean" ]] && continue

  # If this is a llama “family”, try a few alternatives automatically
  candidates=("$want_clean")
  case "$want_clean" in
    llama3:*|llama3.*:*|llama3|llama3.*)
      # Append common alternates in order
      candidates=("$want_clean" "llama3.1:8b-instruct" "llama3:8b-instruct" "llama3.2:3b-instruct")
      ;;
  esac

  pulled=false
  for tag in "${candidates[@]}"; do
    echo "[pull-models] ensure: ${tag}"
    if have_model "$tag"; then
      echo "[pull-models] present: ${tag}"
      pulled=true
      break
    fi
    # Not present → pull
    echo "[pull-models] pulling: ${tag}"
    if curl -fsS "${OLLAMA_URL}/api/pull" -d "{\"name\":\"${tag}\"}" | tee /dev/stderr | grep -q '"success"'; then
      pulled=true
      break
    else
      echo "[pull-models] note: ${tag} not available (yet); will try next candidate if any."
    fi
  done

  if ! $pulled; then
    echo "[pull-models] warn: none of the candidates for '${want_clean}' could be pulled."
  fi
done

echo "[pull-models] done."
