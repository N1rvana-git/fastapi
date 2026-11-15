# 闲小宝 FastAPI 后端

这是一个用于二手商品交易场景的 FastAPI 后端示例项目，提供用户、商品、订单、图片处理、AI 对话和飞书机器人等功能。

项目当前采用模块化单体结构。应用代码位于 `src/app`，数据库使用 SQLAlchemy 和 Alembic 管理，Redis 用于缓存、限流、幂等和异步任务等可选能力。

## 功能概览

- 用户注册、登录、JWT 认证和角色管理
- 商品发布、查询、更新、删除、标签和收藏
- 下单、库存扣减、订单价格快照和幂等处理
- 图片上传、图片分析和文本/图片搜索
- 基于 OpenAI 兼容接口的 AI 对话和 SSE 流式响应
- 可选的人工审批流程和 LangGraph 运行时
- 飞书 Webhook、账号绑定和消息发送
- 健康检查、结构化日志、限流和请求追踪

## 技术栈

- Python 3.11+
- FastAPI
- SQLAlchemy 2.0
- SQLite（本地开发）或 PostgreSQL + pgvector（生产/完整环境）
- Redis（缓存、任务和流式事件，可选）
- Alembic
- pytest、Ruff、Mypy

## 项目结构

```text
.
├── src/
│   ├── app/
│   │   ├── api/              # 路由总装和健康检查
│   │   ├── core/             # 配置、数据库、Redis、安全和中间件
│   │   ├── modules/          # auth、users、items、orders、chat、feishu
│   │   ├── shared/           # 公共依赖、Schema 和 embedding 客户端
│   │   └── main.py           # 应用工厂和生命周期管理
│   ├── main.py               # 兼容入口
│   └── worker.py             # 异步任务 worker 入口
├── alembic/                  # 数据库迁移
├── tests/
│   ├── unit/                 # 单元测试
│   └── integration/          # 集成测试
├── docs/                     # 架构、迁移、运维和验证文档
├── scripts/                  # 开发和压测辅助脚本
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── uv.lock
```

## 本地运行

### 1. 创建环境并安装依赖

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
```

也可以使用 `uv`：

```bash
uv sync
```

视觉模型和浏览器相关能力是可选依赖：

```bash
pip install -r requirements-ai.txt
```

LangGraph 运行时也是可选依赖：

```bash
pip install -r requirements-langgraph.txt
```

### 2. 配置环境变量

复制示例配置：

```bash
cp .env.example .env
```

Windows PowerShell 可以使用：

```powershell
Copy-Item .env.example .env
```

本地开发至少需要设置一个随机的 `SECRET_KEY`：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

将生成的值填入 `.env`。常用配置包括：

```env
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///./test.db
VISION_ENABLED=false
AGENT_DISCONNECT_POLICY=continue
AGENT_APPROVAL_THRESHOLD=1000
```

AI 对话、embedding 和飞书功能还需要分别配置对应的 API 密钥。请不要将 `.env` 或真实密钥提交到 Git。

### 3. 执行数据库迁移并启动

```bash
alembic upgrade head
uvicorn src.main:app --reload
```

启动后可以访问：

- API 文档：http://127.0.0.1:8000/docs
- 存活检查：http://127.0.0.1:8000/health/live
- 就绪检查：http://127.0.0.1:8000/health/ready

### 使用 Docker Compose

完整环境可以使用：

```bash
docker compose up -d --build
docker compose logs -f web worker
```

Compose 配置包含 PostgreSQL、Redis、迁移服务、API 服务和 worker。生产环境请单独管理数据库、密钥和外部 API 配置。

## 常用命令

```bash
make test
make lint
make format
make typecheck
make migrate
make worker
```

直接运行测试：

```bash
pytest tests -q
pytest tests --cov=src/app --cov-report=term-missing
```

## API 示例

主要路由包括：

```text
POST /token
POST /auth/refresh
GET  /auth/me
POST /users/register
GET  /users/me
GET  /items
POST /items
POST /items/{id}/buy
POST /items/ai/agent/stream
POST /feishu/webhook
GET  /health/live
GET  /health/ready
```

具体请求参数和响应结构以 `/docs` 中生成的 OpenAPI 文档为准。

## 相关文档

- [架构说明](docs/ARCHITECTURE.md)
- [迁移指南](docs/MIGRATION.md)
- [运行手册](docs/RUNBOOK.md)
- [重构记录](docs/REFACTOR_REPORT.md)
- [真实环境验证](docs/REAL-ENV-VERIFICATION.md)
- [压测记录](docs/LOAD-TEST-REPORT.md)

## 开发说明

- 数据库结构变更请通过 Alembic migration 提交。
- 本地上传文件、数据库文件、日志和环境变量文件不应提交到 Git。
- 没有 Redis 或可选 AI 服务时，部分功能会按配置降级或不可用。
- 修改 API、数据库或运行配置时，请同步更新相关文档和测试。
