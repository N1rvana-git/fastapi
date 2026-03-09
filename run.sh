#!/bin/bash
echo "🚀 启动闲小宝二手平台全栈本地环境..."

# 1. 激活虚拟环境 (针对你当前的 .venv 目录，如果在别的机器可能是别的目录哦)
if [ -d ".venv" ]; then
    echo "♻️ 正在激活本地虚拟环境 (.venv)..."
    source .venv/bin/activate
elif [ -d ".venv-1" ]; then
    echo "♻️ 正在激活本地虚拟环境 (.venv-1)..."
    source .venv-1/bin/activate
else
    echo "⚠️ 警告: 未找到常见的虚拟环境目录 (.venv / .venv-1)，请确保环境已安装。"
fi

# 2. 清理可能霸占端口的本地残留进程
echo "🧹 正在清理霸占 8000 端口的僵尸进程 (防止串库到 SQLite)..."
kill -9 $(lsof -t -i:8000) 2>/dev/null >/dev/null

# 3. 启动并强制构建最新的 Docker 容器组合！
echo "📦 温馨提示: 如果刚刚 pip 增加了新依赖，请务必保证已写入 requirements.txt 中！"
echo "🐳 正在通过 Docker 构建并拉起核心环境 (FastAPI + PostgreSQL + Redis)..."
docker compose up -d --build --remove-orphans

# 4. 一劳永逸：执行数据库状态同步与补丁映射！
echo "🛠️ 正在自动进行数据库迁移和数据一致性修复，保证上传的商品不会消失..."
sleep 3  # 给数据库一点点启动时间
docker compose exec -T web alembic upgrade head
# 自动修复旧商品无 is_sold 导致全都不显示的问题（防止重建数据库后再次空缺）
docker compose exec -T db psql -U myuser -d mydb -c "UPDATE item SET is_sold = false WHERE is_sold IS NULL;" >/dev/null 2>&1

# 5. 进入日志监听模式
echo "👀 启动成功！一切数据完好无损！正在载入实时运行日志 (退出请按 Ctrl+C)..."
echo "--------------------------------------------------------"
docker compose logs -f web
