#!/usr/bin/env bash
set -euo pipefail

COLLECTION_NAME=${COLLECTION_NAME:-regdocs_v1}
EMBED_MODEL=${EMBED_MODEL:-nomic-embed-text:latest}
DATASET_DIR=${DATASET_DIR:-/workspace/datasets/regdocs}
QDRANT_URL=${QDRANT_URL:-http://127.0.0.1:6333}
MARKER="/workspace/markers/ingest_done_${COLLECTION_NAME}.txt"

if [[ -f "$MARKER" ]]; then
  echo "[ingest] already done for ${COLLECTION_NAME}."
  exit 0
fi

# wait for qdrant + ollama
until curl -sf ${QDRANT_URL}/collections >/dev/null; do
  echo "waiting for qdrant..."
  sleep 2
done
until curl -sf http://127.0.0.1:11434/api/tags >/dev/null; do
  echo "waiting for ollama..."
  sleep 2
done

# run seed.py in venv
source /workspace/venv/bin/activate
python /workspace/dantive-regbot/services/ingest/seed.py \
  --src "${DATASET_DIR}" \
  --collection "${COLLECTION_NAME}" \
  --embed-model "${EMBED_MODEL}" \
  --qdrant-url "${QDRANT_URL}"
deactivate

date > "$MARKER"
echo "[ingest] done."
