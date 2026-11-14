#!/usr/bin/env bash
# One-command local startup.
#
# The database migration is a *one-shot* compose service (`migrate`), not a
# command in the API container: it runs once, then web/worker start. That is the
# behaviour this script just verifies.

set -euo pipefail

if [ -f ".env" ]; then
  echo "✅ 使用现有 .env"
else
  echo "⚠️  未找到 .env，正在从 .env.example 复制（请填写 SECRET_KEY 与 API key）"
  cp .env.example .env
fi

if [ ! -d ".venv" ] && [ ! -d ".venv-1" ]; then
  echo "⚠️  未找到虚拟环境；Docker 模式无需本地 venv，继续。"
fi

echo "🐳 构建并启动：db → redis → migrate（一次性） → web + worker"
docker compose up -d --build --remove-orphans

echo "⏳ 等待就绪探针通过..."
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/health/ready >/dev/null 2>&1; then
    echo "✅ 服务就绪：http://127.0.0.1:8000/docs"
    break
  fi
  sleep 2
done

docker compose ps
echo "--------------------------------------------------------------"
echo "查看日志： docker compose logs -f web worker"
echo "结束：     docker compose down"
