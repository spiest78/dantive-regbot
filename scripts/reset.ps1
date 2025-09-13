# scripts/reset.ps1
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\reset.ps1

param(
  [string]$ComposeFile = "docker-compose.yml",
  [string]$ProjectName = "dantive-regbot"
)

$ErrorActionPreference = "Stop"
function Step([string]$msg){ Write-Host ""; Write-Host ("==> {0}" -f $msg) -ForegroundColor Cyan }

if (!(Test-Path $ComposeFile)) {
  if (Test-Path ("infra\" + $ComposeFile)) { Set-Location infra }
  else { throw "Cannot find $ComposeFile. Run from repo root or infra/." }
}

Step "Stopping and removing compose stack (images/volumes/orphans)"
docker compose -p $ProjectName -f $ComposeFile down -v --rmi all --remove-orphans

Step "Removing named volumes"
docker volume rm ($ProjectName + "_pgdata") -f | Out-Null
docker volume rm ($ProjectName + "_qdrant_storage") -f | Out-Null
docker volume rm ($ProjectName + "_models_cache") -f | Out-Null

Step "Pruning dangling artifacts"
docker system prune -f

Write-Host ""
Write-Host "Done. Now run:  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1" -ForegroundColor Yellow