param(
  [string]$ComposeFile = "infra\docker-compose.yml",
  [string]$ProjectName = "dantive-regbot",
  [int]$ApiPort    = 8000,
  [int]$UiPort     = 8501,
  [int]$QdrantPort = 6333,
  [int]$OllamaPort = 11434
)

$ErrorActionPreference = "Continue"

function Row($name,$url,$status){
  [PSCustomObject]@{ Name = $name; Url = $url; Status = $status }
}

function Ping-Http($name,$url){
  try {
    $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
    if ($resp.StatusCode -eq 200) { return Row $name $url "OK" }
    else                           { return Row $name $url ("HTTP " + $resp.StatusCode) }
  } catch {
    return Row $name $url ("DOWN: " + $_.Exception.Message.Split("`n")[0])
  }
}

function Ping-Cmd($name,[scriptblock]$cmd){
  try {
    & $cmd | Out-Null
    if ($LASTEXITCODE -eq 0) { return Row $name "<exec>" "OK" }
    else                     { return Row $name "<exec>" ("EXIT " + $LASTEXITCODE) }
  } catch {
    return Row $name "<exec>" ("DOWN: " + $_.Exception.Message.Split("`n")[0])
  }
}

Write-Host "`n==> Containers" -ForegroundColor Cyan
docker compose -f $ComposeFile -p $ProjectName ps

# Brief warm-up wait for Qdrant
$checks = @()
$checks += Ping-Cmd  "postgres(pg_isready)" { docker compose -f $ComposeFile -p $ProjectName exec db pg_isready -U $env:POSTGRES_USER -d $env:POSTGRES_DB }

# Qdrant: try /readyz up to 6 times (~12s)
$qdr = $null
for ($i=0; $i -lt 6; $i++) {
  $qdr = Ping-Http "qdrant(/readyz)" ("http://localhost:{0}/readyz" -f $QdrantPort)
  if ($qdr.Status -eq "OK") { break }
  Start-Sleep -Seconds 2
}
$checks += $qdr
$checks += Ping-Http "qdrant(/collections)" ("http://localhost:{0}/collections" -f $QdrantPort)

# Ollama
$checks += Ping-Cmd  "ollama(list)" { docker compose -f $ComposeFile -p $ProjectName exec ollama ollama list }
$checks += Ping-Http "ollama(/api/tags)" ("http://localhost:{0}/api/tags" -f $OllamaPort)

# API
$checks += Ping-Http "api(/health)" ("http://localhost:{0}/health" -f $ApiPort)

# UI
$checks += Ping-Http "ui(/_stcore/health)" ("http://localhost:{0}/_stcore/health" -f $UiPort)

Write-Host "`n==> Service health" -ForegroundColor Cyan
$checks | Format-Table Name, Url, Status -AutoSize

$bad = $checks | Where-Object { $_.Status -ne "OK" }
if ($bad.Count -gt 0){
  Write-Host "`nSome checks failed:" -ForegroundColor Yellow
  $bad | Format-Table Name, Status, Url -AutoSize
  Write-Host "`nHelpful logs:" -ForegroundColor Yellow
  Write-Host "  docker compose -f $ComposeFile -p $ProjectName logs --tail=200 db"
  Write-Host "  docker compose -f $ComposeFile -p $ProjectName logs --tail=200 qdrant"
  Write-Host "  docker compose -f $ComposeFile -p $ProjectName logs --tail=200 ollama"
  Write-Host "  docker compose -f $ComposeFile -p $ProjectName logs --tail=200 api"
  Write-Host "  docker compose -f $ComposeFile -p $ProjectName logs --tail=200 ui"
  exit 1
} else {
  Write-Host "`nAll healthy." -ForegroundColor Green
}