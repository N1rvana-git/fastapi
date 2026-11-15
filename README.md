# 闲小宝 · 智能二手交易平台

> 一个以 **AI Agent 为核心体验**、以 **FastAPI 后端**为支撑的二手交易平台。
> 不只是商品 CRUD：它会理解需求、拆解预算、混合检索真实库存、查平台规则、在超额度时请求人工审批，
> 并在长对话中记住你的预算、地址和偏好。

项目采用模块化单体（modular monolith）结构，代码位于 `src/app`。

**智能层**负责意图理解、RAG 检索、工具调用、反思与记忆；**平台层**负责交易、库存、订单、鉴权、
幂等、任务队列与可观测性。两条主线都按可测试、可部署、可演进的标准实现。

---

## 1. 项目定位

闲小宝不是“给 CRUD 接口套一个聊天框”，而是把 Agent 做成交易流程的一等公民：

- 用户说“两千左右想买一台打 CS2 的显示器”，Agent 会拆成 `query + category + max_price`，
  用**混合检索（语义 + 关键词 + RRF）**查真实在售库存，而不是编造商品；
- 用户问“退换货怎么规定的”，Agent 路由到**规则 RAG**，只挂载知识库工具；
- 用户要下单，Agent 先确认地址，再调用 `create_order`；金额超过阈值自动进入 **HITL 人工审批**，
  审批通过后才真正扣库存，且重复请求幂等；
- 检索为空或参数不合法时，Agent 会收到结构化的 **Reflection Hint**，自行放宽预算或修正参数，
  最多重试一次，而不是直接“没找到”；
- 长对话会把早期信息压缩成 `BuyerMemory`（预算、类目、地址、拒绝过的商品），
  在用户换话题后仍然记得关键约束。

同时，平台层保证这些能力不是 Demo 玩具：库存扣减是原子 SQL、写接口有幂等键、SSE 支持断线续传、
Redis 故障可降级、数据库迁移可上可下、CI 有覆盖率门禁。

---

## 2. 核心能力

### 2.1 Agent 智能层

| 能力 | 实现 |
| --- | --- |
| **意图分流** | 规则化识别 `chitchat / policy_qa / shopping_search / order_action`，按意图裁剪工具集；规则咨询不会挂 `create_order`，降低幻觉与 token 消耗 |
| **混合检索 RAG** | `pgvector` 语义 Top-K + 关键词/结构化过滤 Top-K，用 **RRF（k=60）** 融合；结果标注 `semantic / lexical / hybrid` |
| **查询改写** | `search_items` 支持 `query / keyword / category / min_price / max_price / sort_by`，把口语拆成结构化条件 |
| **自愈反思** | 空结果/参数错误注入 `reflection_hint`（放宽价格 20%、上位词、修正字段），最多重试 1 次 |
| **短期记忆** | 早期消息压缩为 `BuyerMemory`（预算、偏好类目、收货地址、拒绝商品），写入 System Prompt 固定槽位，保持前缀稳定以命中 Prefix Cache |
| **双运行时** | Native 工具循环 + 可选 LangGraph 状态机；两者共用同一套 SSE 契约、工具与 HITL 审批表 |
| **人工审批 HITL** | 高额订单 `interrupt` / 挂起，审批通过后由审批服务唯一执行一次下单，避免双写扣库存 |
| **离线评测** | 12 条 Golden Cases，5 项指标（工具选择、Schema 合法率、HITL 拦截、零结果自愈、幂等），CI 门禁 100% |

### 2.2 交易与平台后端

- 用户注册、登录、JWT 认证、角色管理；
- 商品发布、查询、更新、删除、标签、收藏；
- **原子库存扣减**（`UPDATE ... WHERE inventory >= qty`），订单价格快照；
- 订单幂等键，重复请求重放已有订单，不重复扣库存；
- 图片上传、图片分析、文本/图片搜索；
- 飞书 Webhook、账号绑定、事件去重与消息通知；
- 健康检查、结构化日志、请求追踪、限流、优雅停机。

### 2.3 工程化与可靠性

- **架构边界**：`service` 不依赖 FastAPI；HTTP 只做参数校验与 SSE 包装；
- **异步全链路**：SQLAlchemy 2.0 async、httpx、Redis asyncio，工具内部不阻塞事件循环；
- **Redis 可选降级**：无 Redis 时幂等/限流/锁退化为进程内实现，单副本仍可用；
- **SSE 可靠性**：事件缓冲、`Last-Event-ID` 续传、心跳、断线策略、任务 watchdog；
- **任务队列**：Redis Streams + 消费组 + 重试 + 死信，API 与 worker 分离；
- **迁移与部署**：Alembic 双向迁移、Docker Compose、K8s 探针、独立迁移 Job；
- **质量门禁**：ruff / mypy / pytest / 覆盖率 80% / pre-commit / GitHub Actions。

---

## 3. Agent 工作流

```text
用户消息
   │
   ├─► 历史压缩 ──► BuyerMemory（预算 / 类目 / 地址 / 拒绝商品）
   │
   ├─► 意图分类 ──► 工具白名单（policy_qa 只给规则检索；order_action 才给下单）
   │
   ├─► 主模型循环
   │      │
   │      ├─► search_items ──► 语义 Top-K ─┐
   │      │                    关键词/过滤 Top-K ─┴─► RRF 融合 ──► match_reason
   │      │
   │      ├─► search_platform_policy ──► 规则 RAG
   │      │
   │      └─► create_order ──► 金额 >= 阈值 ──► HITL 挂起 ──► /resume 审批后执行一次
   │
   └─► 工具结果为空/参数错误 ──► reflection_hint ──► 模型自主重试（最多 1 次）
```

SSE 会先发送 `intent` 事件，再发送 `token / tool_start / tool_end / interrupt_required / done`，
前端可以据此显示“正在查规则 / 正在比价 / 等待审批”。

---

## 4. 技术栈

- Python 3.11+
- FastAPI、Pydantic 2
- SQLAlchemy 2.0（async）、Alembic
- SQLite（本地）或 PostgreSQL + pgvector（生产 / 完整环境）
- Redis（缓存、限流、幂等、SSE 缓冲、任务队列，可选）
- OpenAI 兼容 LLM 网关（DeepSeek / GLM 等）
- 智谱 `embedding-2`（1024 维，语义检索；无 key 时退化为关键词）
- LangGraph（可选运行时）、psycopg3 checkpointer
- pytest、Ruff、Mypy、Locust（压测）

---

## 5. 项目结构

```text
.
├── src/
│   ├── app/
│   │   ├── api/              # 路由总装与健康检查
│   │   ├── core/             # 配置、数据库、Redis、安全、中间件
│   │   ├── modules/
│   │   │   ├── chat/         # Agent 运行时、意图、反思、记忆、评测、SSE
│   │   │   ├── items/        # 商品、库存、搜索
│   │   │   ├── orders/       # 下单、审批
│   │   │   ├── users/        # 用户与鉴权
│   │   │   └── feishu/       # 飞书机器人
│   │   ├── shared/           # 依赖、embedding、RRF 融合
│   │   └── main.py           # 应用工厂与生命周期
│   ├── main.py               # 兼容入口
│   └── worker.py             # 任务 worker 入口
├── alembic/                  # 数据库迁移
├── tests/
│   ├── unit/                 # 单元测试（含 Agent 评测门禁）
│   └── integration/          # 集成测试（HTTP + 真实 SQLite/PG）
├── docs/                     # 架构、迁移、运维、压测、验证
├── scripts/                  # 开发、压测、评测辅助脚本
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── uv.lock
```

---

## 6. 本地运行

### 6.1 创建环境并安装依赖

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
```

或者使用 `uv`：

```bash
uv sync
```

可选依赖：

```bash
pip install -r requirements-ai.txt          # 视觉模型 / 浏览器能力
pip install -r requirements-langgraph.txt   # LangGraph 运行时 + PG checkpointer
```

### 6.2 配置环境变量

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

至少设置一个随机 `SECRET_KEY`：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

常用配置：

```env
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///./test.db
VISION_ENABLED=false
AGENT_DISCONNECT_POLICY=continue
AGENT_APPROVAL_THRESHOLD=1000
AGENT_MEMORY_ENABLED=true
AGENT_MEMORY_LOOKBACK=24
```

### 6.3 配置 AI 能力

`CHAT_*` 与 `DEEPSEEK_*` 等价，二选一即可：

```env
CHAT_API_KEY=sk-...
CHAT_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-flash
```

语义检索需要单独的 embedding key（DeepSeek / GLM 网关没有 embedding 接口）：

```env
ZHIPUAI_API_KEY=...
ZHIPU_EMBEDDING_MODEL=embedding-2
EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4
EMBEDDING_DIMENSION=1024
EMBEDDING_ENABLED=true
```

没有 embedding key 时设置 `EMBEDDING_ENABLED=false`，检索自动退化为关键词匹配。
请不要将 `.env` 或真实密钥提交到 Git。

### 6.4 迁移并启动

```bash
alembic upgrade head
uvicorn src.main:app --reload
```

访问：

- API 文档：<http://127.0.0.1:8000/docs>
- 存活检查：<http://127.0.0.1:8000/health/live>
- 就绪检查：<http://127.0.0.1:8000/health/ready>

### 6.5 Docker Compose

```bash
docker compose up -d --build
docker compose logs -f web worker
```

Compose 包含 PostgreSQL、Redis、迁移服务、API 与 worker。生产环境请单独管理数据库、密钥和外部 API 配置。

---

## 7. 评测与质量

### 7.1 运行 Agent 离线评测

```bash
python -m src.app.modules.chat.eval_harness --format markdown
python -m src.app.modules.chat.eval_harness --format json --output eval-report.json
```

当前 Golden Dataset：12 条用例，核心指标全部 100%：

```text
tool_selection_accuracy   = 100%
schema_valid_rate         = 100%
hitl_guardrail_pass_rate  = 100%
fallback_recovery_rate    = 100%
idempotency_pass_rate     = 100%
```

### 7.2 运行测试与门禁

```bash
make test
make lint
make format
make typecheck
make migrate
make worker
```

直接运行：

```bash
pytest tests -q
pytest tests --cov=src/app --cov-report=term-missing
ruff check src tests
mypy src/app
```

当前基线（本机实测）：

| 项 | 值 |
| --- | --- |
| 测试 | **209 passed / 1 skipped** |
| 行覆盖率 | **82.66%**（CI 门禁 80%） |
| ruff / format / mypy | 全部 0 报错 |
| 迁移 | `alembic upgrade/downgrade` 双向通过 |
| 压测 | 100 并发抢 5 件库存：5 单 / 5 买家 / 零超卖 |

---

## 8. API 示例

```text
POST /token
POST /auth/refresh
GET  /auth/me
POST /users/register
GET  /users/me
GET  /items
POST /items
POST /items/{id}/buy
POST /items/search-by-text
POST /items/ai/agent/stream
POST /items/ai/threads/{id}/resume
POST /feishu/webhook
GET  /health/live
GET  /health/ready
```

具体请求参数与响应结构以 `/docs` 中的 OpenAPI 文档为准；SSE 事件类型见
[架构说明 §5.7](docs/ARCHITECTURE.md)。

---

## 9. 相关文档

- [架构说明](docs/ARCHITECTURE.md)：分层、Agent 认知链路、混合检索、SSE、HITL、双运行时
- [重构记录](docs/REFACTOR_REPORT.md)：0.2.0 → 0.4.0 的演进、指标与取舍
- [迁移指南](docs/MIGRATION.md)
- [运行手册](docs/RUNBOOK.md)
- [真实环境验证](docs/REAL-ENV-VERIFICATION.md)
- [压测记录](docs/LOAD-TEST-REPORT.md)

---

## 10. 开发说明

- 数据库结构变更请通过 Alembic migration 提交；
- 本地上传文件、数据库文件、日志和环境变量文件不应提交到 Git；
- 没有 Redis 或可选 AI 服务时，部分功能会按配置降级；
- 修改 API、数据库或运行配置时，请同步更新相关文档和测试；
- Agent 的意图、反思、记忆、RRF 都是纯函数模块，新增策略时优先补单元测试与 Golden Case。
