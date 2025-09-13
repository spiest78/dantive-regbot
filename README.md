# Dantive Regulatory Bot

Dantive Regulatory Bot (RegBot) is a minimal retrieval‑augmented generation stack for exploring regulatory documents.  It wires together a FastAPI backend, a Streamlit UI, and an Ollama‑powered embedding and language model pipeline backed by Qdrant and PostgreSQL.

## Repository layout

- `apps/api` – FastAPI service exposing `/health`, `/ask`, and `/ask_stream` endpoints.
- `apps/ui` – Streamlit front‑end for chatting with the API.
- `apps/data` – sample PDFs that can be embedded into Qdrant.
- `infra` – Docker Compose stack for PostgreSQL, Qdrant, Ollama, the API, and the UI.
- `services` – lightweight Docker build contexts used by the compose file.
- `scripts` – PowerShell helpers for bootstrapping, building, and seeding.
- `seed_qdrant.py` – embeds local documents with Ollama and upserts them into Qdrant.

## Getting started

1. **Install prerequisites**: Docker and Docker Compose. Windows users can run the PowerShell scripts in `scripts/`.
2. **Bootstrap the stack**:
   ```powershell
   # from the repo root
   powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
   ```
   The script pulls base images, builds the API/UI images, starts PostgreSQL, Qdrant, and Ollama, then launches the API and UI.
3. **Access the services**:
   - API: `http://localhost:8000` – health check at `/health`, text generation at `/ask` and `/ask_stream`.
   - UI: `http://localhost:8501` – Streamlit interface for querying models.

## Seeding Qdrant with local documents

Place PDFs or text files under `apps/data` and run the seeding script inside the API container:

```bash
# inside the repo root or API container
python seed_qdrant.py
```

The script chunks each document, generates embeddings through Ollama, and stores them in the Qdrant collection `regdocs_v1`.

## Development notes

The API and UI are written in Python 3.11.  The Docker Compose file under `infra/` defines the development environment and mounts the repository so code changes are picked up immediately.

