# scripts/bootstrap.ps1
# Usage examples:
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -IngestCELEX 32008R1272

param(
  [string]$ComposeFile = "docker-compose.yml",
  [string]$ProjectName = "dantive-regbot",
  [string]$EnvFile     = ".env",
  [string]$IngestCELEX = ""
)

$ErrorActionPreference = "Stop"

function Step([string]$msg){ Write-Host ""; Write-Host ("==> {0}" -f $msg) -ForegroundColor Cyan }
function Ok([string]$msg){ Write-Host ("OK  {0}" -f $msg) -ForegroundColor Green }
function Warn([string]$msg){ Write-Host ("WARN {0}" -f $msg) -ForegroundColor Yellow }
function Die([string]$msg){ Write-Host ("ERR {0}" -f $msg) -ForegroundColor Red; exit 1 }

# Ensure we are next to the compose file
if (!(Test-Path $ComposeFile)) {
  if (Test-Path ("infra\" + $ComposeFile)) { Set-Location infra }
  else { Die "Cannot find $ComposeFile. Run from repo root or infra/." }
}

# 0) Show basic env
Step ("Project: {0}" -f $ProjectName)
if (Test-Path $EnvFile) { Ok ("Found {0}" -f $EnvFile) } else { Warn ("No {0} found (compose defaults will be used)" -f $EnvFile) }

# 1) Create named volumes (idempotent)
Step "Creating named volumes"
docker volume create ($ProjectName + "_pgdata") | Out-Null
docker volume create ($ProjectName + "_qdrant_storage") | Out-Null
docker volume create ($ProjectName + "_models_cache") | Out-Null
Ok "Volumes ready"

# 2) Pull base infra images and build app images explicitly
Step "Pulling base images (db/qdrant/ollama)"
docker compose -p $ProjectName -f $ComposeFile pull db qdrant ollama | Out-Null

Step "Building API image"
docker compose -p $ProjectName -f $ComposeFile build --no-cache api
if ($LASTEXITCODE -ne 0) { Die "API build failed OR 'api' service is missing a build context" }

Step "Building UI image"
docker compose -p $ProjectName -f $ComposeFile build --no-cache ui
if ($LASTEXITCODE -ne 0) { Die "UI build failed OR 'ui' service is missing a build context" }
Ok "API/UI images built"

# 3) Start core services first
Step "Starting core services: db, qdrant, ollama"
docker compose -p $ProjectName -f $ComposeFile up -d db qdrant ollama

# Helpers
function Wait-HttpHealthy([string]$url, [int]$retries=60){
  for($i=1;$i -le $retries;$i++){
    try {
      $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
      if ($resp.StatusCode -eq 200) { return $true }
    } catch {}
    Start-Sleep -Seconds 2
  }
  return $false
}
function Wait-ContainerCmd([string]$svc, [string[]]$cmd, [int]$retries=60){
  for($i=1;$i -le $retries;$i++){
    try {
      docker compose exec -T $svc $cmd | Out-Null
      if ($LASTEXITCODE -eq 0) { return $true }
    } catch {}
    Start-Sleep -Seconds 2
  }
  return $false
}

# Resolve ports (env or defaults)
$QDRANT_PORT = if ($env:QDRANT_PORT) { $env:QDRANT_PORT } else { "6333" }
$API_PORT    = if ($env:API_PORT)    { $env:API_PORT }    else { "8000" }
$UI_PORT     = if ($env:UI_PORT)     { $env:UI_PORT }     else { "8501" }
$OLLAMA_PORT = if ($env:OLLAMA_PORT) { $env:OLLAMA_PORT } else { "11434" }

# 4) Health waits
Step "Waiting for Qdrant /readyz"
if (-not (Wait-HttpHealthy ("http://localhost:{0}/readyz" -f $QDRANT_PORT))) { Die "Qdrant not healthy in time" } else { Ok "Qdrant healthy" }

Step "Waiting for Ollama CLI to respond"
if (-not (Wait-ContainerCmd "ollama" @("ollama","list"))) { Die "Ollama not healthy in time" } else { Ok "Ollama healthy" }

# 5) Pull models (safe to re-run)
Step "Pulling models into ollama volume"
docker compose -p $ProjectName -f $ComposeFile up --no-deps ollama-init
Ok "Model pull step completed (or skipped)"

# 6) Start API & UI
Step "Starting API and UI"
docker compose -p $ProjectName -f $ComposeFile up -d api ui

Step "Waiting for API /health"
if (-not (Wait-HttpHealthy ("http://localhost:{0}/health" -f $API_PORT))) { Die "API not healthy in time" } else { Ok "API healthy" }

Step "Waiting for UI /_stcore/health"
if (-not (Wait-HttpHealthy ("http://localhost:{0}/_stcore/health" -f $UI_PORT))) { Die "UI not healthy in time" } else { Ok "UI healthy" }

# 7) Optional ingestion
if ($IngestCELEX -ne "") {
  Step ("Running ingestion for CELEX {0}" -f $IngestCELEX)
  docker compose -p $ProjectName -f $ComposeFile run --rm ingest --celex $IngestCELEX
  if ($LASTEXITCODE -eq 0) { Ok "Ingestion completed" } else { Die "Ingestion failed" }
}

Ok "Bootstrap finished. Services are up:"
docker compose -p $ProjectName -f $ComposeFile ps
Write-Host ""
Write-Host ("API: http://localhost:{0}    UI: http://localhost:{1}" -f $API_PORT, $UI_PORT) -ForegroundColor Cyan