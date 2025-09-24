Diagnostics snapshot (Runpod):
- Startup script: /workspace/startup_pod.sh (bypass with /workspace/.disable_startup)
- Supervisor config used on pod: /workspace/supervisord.conf (copied to infra/supervisor/supervisord.conf)
- Persistent dirs on NV: /workspace/{ollama,qdrant,postgres,datasets,markers}
- One-shots: ops/pull_models.sh, ops/ingest_once.sh (markers under /workspace/markers)
