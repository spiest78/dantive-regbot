# scripts/reset.ps1
# Usage examples:
#   powershell -ExecutionPolicy Bypass -File scripts\reset.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\reset.ps1 -Seed

param(
  [string]$ComposeFile = "docker-compose.yml",
  [string]$ProjectName = "dantive-regbot",
  [switch]$Seed
)

$ErrorActionPreference = "Stop"
function Step([string]$msg){ Write-Host ""; Write-Host ("==> {0}" -f $msg) -ForegroundColor Cyan }
function Ok([string]$msg){ Write-Host ("OK  {0}" -f $msg) -ForegroundColor Green }
function Die([string]$msg){ Write-Host ("ERR {0}" -f $msg) -ForegroundColor Red; exit 1 }

if (!(Test-Path $ComposeFile)) {
  if (Test-Path ("infra\" + $ComposeFile)) { Set-Location infra }
  else { Die "Cannot find $ComposeFile. Run from repo root or infra/." }
}

# 1) Stop and wipe
Step "Stopping and removing compose stack (images/volumes/orphans)"
docker compose -p $ProjectName -f $ComposeFile down -v --rmi all --remove-orphans

Step "Removing named volumes"
docker volume rm ($ProjectName + "_pgdata") -f | Out-Null
docker volume rm ($ProjectName + "_qdrant_storage") -f | Out-Null
docker volume rm ($ProjectName + "_models_cache") -f | Out-Null

Step "Pruning dangling artifacts"
docker system prune -f
Ok "Clean slate ready"

# 2) Rebuild and restart
Step "Rebuilding stack"
docker compose -p $ProjectName -f $ComposeFile up -d --build
if ($LASTEXITCODE -ne 0) { Die "Compose build failed" }

# 3) Pull Ollama models (both mistral + nomic embed)
Step "Pulling models into ollama volume"
docker compose exec ollama ollama pull mistral:7b-instruct
docker compose exec ollama ollama pull nomic-embed-text
Ok "Model pull step completed"

# 4) Install Python deps in API
Step "Installing Python deps inside API container"
docker compose exec api pip install --quiet qdrant-client pypdf tqdm requests
Ok "Python deps installed"

# 5) Optional seeding
if ($Seed) {
  Step "Running Qdrant seeding from apps/data"
  docker compose exec `
    --env DATA_DIR=/workspace/apps/data `
    --env QDRANT_URL=http://qdrant:6333 `
    --env OLLAMA_URL=http://ollama:11434 `
    --env EMBED_MODEL=nomic-embed-text `
    --env QDRANT_COLLECTION=regdocs_v1 `
    api python /workspace/seed_qdrant.py
  if ($LASTEXITCODE -eq 0) { Ok "Seeding completed" } else { Die "Seeding failed" }
}

Ok "Reset finished. Stack rebuilt and ready."
Write-Host ""
Write-Host "API: http://localhost:8000    UI: http://localhost:8501" -ForegroundColor Cyan