Write-Host "==> Building Dantive RegBot stack..."

# Rebuild all services
docker compose build

# Install deps in API container
docker compose up -d api
docker compose exec api pip install --quiet qdrant-client pypdf tqdm requests

# Pull models into Ollama
docker compose up -d ollama
docker compose exec ollama ollama pull mistral:7b-instruct
docker compose exec ollama ollama pull nomic-embed-text

Write-Host "==> Build complete!"