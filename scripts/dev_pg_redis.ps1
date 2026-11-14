#!/usr/bin/env pwsh
# Start throw-away PostgreSQL (pgvector) + Redis containers for real end-to-end
# verification, then print the environment block to use.
#
#   ./scripts/dev_pg_redis.ps1
#   # in another shell, with the printed env vars:
#   alembic upgrade head
#   python -m uvicorn src.main:app --port 8000
#   python -m src.worker
#   python scripts/dev_llm_stub.py --port 8125
#
# The containers are named xjb-pg / xjb-redis and are safe to remove with
#   docker rm -f xjb-pg xjb-redis

param(
    [int]$PgPort = 55432,
    [int]$RedisPort = 56379,
    [string]$PgUser = "xjb",
    [string]$PgPassword = "xjbpass",
    [string]$PgDatabase = "xjbdb"
)

$ErrorActionPreference = "Stop"

Write-Host "==> removing previous xjb containers (if any)"
docker rm -f xjb-pg xjb-redis 2>$null | Out-Null

Write-Host "==> starting PostgreSQL 15 + pgvector on port $PgPort"
docker run -d --name xjb-pg `
    -e "POSTGRES_USER=$PgUser" -e "POSTGRES_PASSWORD=$PgPassword" -e "POSTGRES_DB=$PgDatabase" `
    -p "${PgPort}:5432" pgvector/pgvector:pg15 | Out-Null

Write-Host "==> starting Redis on port $RedisPort"
docker run -d --name xjb-redis -p "${RedisPort}:6379" redis:alpine | Out-Null

Write-Host "==> waiting for PostgreSQL to accept connections"
for ($i = 0; $i -lt 60; $i++) {
    docker exec xjb-pg pg_isready -U $PgUser -d $PgDatabase *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Milliseconds 500
}

Write-Host "==> enabling the vector extension"
docker exec xjb-pg psql -U $PgUser -d $PgDatabase -c "CREATE EXTENSION IF NOT EXISTS vector;" | Out-Null

$databaseUrl = "postgresql+asyncpg://${PgUser}:${PgPassword}@127.0.0.1:${PgPort}/${PgDatabase}"
$redisUrl = "redis://127.0.0.1:${RedisPort}/0"

Write-Host ""
Write-Host "Container status:"
docker ps --filter "name=xjb-" --format "  {{.Names}}  {{.Status}}  {{.Ports}}"
Write-Host ""
Write-Host "Use these environment variables (PowerShell):"
Write-Host "  `$env:DATABASE_URL = `"$databaseUrl`""
Write-Host "  `$env:REDIS_URL = `"$redisUrl`""
Write-Host "  `$env:REDIS_REQUIRED = `"true`""
Write-Host "  `$env:TASKS_EAGER = `"false`""
Write-Host "  `$env:CHAT_BASE_URL = `"http://127.0.0.1:8125/v1`"   # optional: python scripts/dev_llm_stub.py"
Write-Host "  `$env:CHAT_API_KEY = `"stub`""
Write-Host ""
Write-Host "Then: alembic upgrade head"
