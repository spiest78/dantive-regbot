#!/usr/bin/env bash
set -euo pipefail
MARKER="/markers/ingest_done_${COLLECTION_NAME}.txt"

if [[ -f "$MARKER" ]]; then
  echo "[ingest] already done for ${COLLECTION_NAME}."
  exit 0
fi

# small settle
sleep 2

python /app/seed.py \
  --src "${DATASET_DIR}" \
  --collection "${COLLECTION_NAME}" \
  --embed-model "${EMBED_MODEL}" \
  --qdrant-url "${QDRANT_URL}"

date > "$MARKER"
echo "[ingest] done."
