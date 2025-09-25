#!/usr/bin/env bash
set -euo pipefail

# Config (env overridable)
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
MODEL_LIST_FILE="${MODEL_LIST_FILE:-/workspace/dantive-regbot/ops/model-list.txt}"
MARKER="${MARKER:-/workspace/markers/models_pulled.txt}"

mkdir -p "$(dirname "$MARKER")"

# If we already completed a run, skip
if [[ -f "$MARKER" ]]; then
  echo "[pull-models] already done."
  exit 0
fi

# Wait for Ollama to be reachable
echo "[pull-models] waiting for Ollama at $OLLAMA_URL …"
until curl -fsS "$OLLAMA_URL/api/tags" >/dev/null; do
  sleep 2
done

# Fallbacks for legacy/retired tags (extend as needed)
fallbacks_for() {
  case "$1" in
    "llama3:8b-instruct")
      # Try newer public tags in descending preference
      echo "llama3.1:8b-instruct"
      echo "llama3.2:3b-instruct"
      ;;
    "llama3.1:8b-instruct")
      echo "llama3.2:3b-instruct"
      ;;
    *)
      ;;
  esac
}

trim() { sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }

pull_one() {
  local name="$1"
  # already present?
  if curl -fsS "$OLLAMA_URL/api/show" -H 'Content-Type: application/json' \
       -d "{\"name\":\"$name\"}" >/dev/null 2>&1; then
    echo "[pull-models] present: $name (skip)"
    return 0
  fi

  echo "[pull-models] pulling: $name"
  if out="$(curl -sS -w '\n%{http_code}\n' "$OLLAMA_URL/api/pull" \
            -H 'Content-Type: application/json' \
            -d "{\"name\":\"$name\"}")"; then
    code="$(printf '%s' "$out" | tail -n1)"
    if [[ "$code" == "200" || "$code" == "201" ]]; then
      echo "[pull-models] success: $name"
      return 0
    fi
    # non-2xx: keep going below for fallback handling
  else
    # network/transport error — try fallbacks
    code="curl_error"
  fi

  # Try fallbacks on invalid/retired tags
  if [[ "$code" == "400" || "$code" == "404" || "$code" == "curl_error" ]]; then
    local fb
    while read -r fb; do
      [[ -z "$fb" ]] && continue
      echo "[pull-models] '$name' failed (code=$code), trying fallback: $fb"
      if pull_one "$fb"; then
        echo "[pull-models] mapped '$name' → '$fb' (ok)"
        return 0
      fi
    done < <(fallbacks_for "$name")
  fi

  echo "[pull-models] WARNING: could not pull '$name' (status=$code); continuing."
  return 1
}

# Read desired models and process
if [[ ! -s "$MODEL_LIST_FILE" ]]; then
  echo "[pull-models] WARNING: model list file missing/empty: $MODEL_LIST_FILE"
else
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    line="$(printf '%s' "$raw" | trim)"
    [[ -z "$line" || "$line" =~ ^# ]] && continue
    pull_one "$line" || true
  done < "$MODEL_LIST_FILE"
fi

# Done marker
date > "$MARKER"
echo "[pull-models] done."
