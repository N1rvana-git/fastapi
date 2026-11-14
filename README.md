# 闲小宝二手交易平台 · FastAPI 工业级后端

一个带 AI 导购（LLM + 工具调用 + SSE 流式 + 人工审批）与飞书机器人的二手交易后端。
2026-11 按《FastAPI 工业级后端架构与落地建议》完成了一轮架构重构：从「能跑的练手项目」
升级为「模块化单体 + 全链路异步 + 强类型契约 + 可观测 + 可部署」的工程化后端。

- 重构说明与对照表：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 重构报告（含验证记录与面试讲述要点）：[docs/REFACTOR_REPORT.md](docs/REFACTOR_REPORT.md)
- 真实环境联调（PG+pgvector、Redis、独立 worker）：[docs/REAL-ENV-VERIFICATION.md](docs/REAL-ENV-VERIFICATION.md)
- 破坏性变更与旧代码清理：[docs/MIGRATION.md](docs/MIGRATION.md)
- 上线/运维手册：[docs/RUNBOOK.md](docs/RUNBOOK.md)
- 原始 PDF 已逐条落到代码：见 [架构对照](#与-pdf-建议的逐条对照)

---

## 1. 这次重构到底改了什么

| 维度 | 重构前 | 现在 |
| --- | --- | --- |
| 结构 | `src/{auth,posts,users,feishu}` 平铺，`posts/router.py` 932 行上帝文件 | `src/app/{core,shared,modules,api}`，按业务域垂直切分，router 只做参数与响应 |
| 分层 | 路由里直接写 SQL、`user` 表和商品表混在 `posts/models.py` | router → service → repository → models 单向依赖，领域层不依赖 FastAPI/HTTP |
| 启动 | 无 lifespan；import `src.posts` 即加载 600MB CN-CLIP 模型；无优雅停机 | `create_app()` + `lifespan` 统一管理 DB/Redis/httpx/Agent/任务；模型懒加载 |
| 异步纯度 | 同步 `openai`/`zhipuai` SDK 写在 `async def` 里阻塞事件循环；`requests` 风格阻塞写文件 | LLM/Embedding/飞书/爬虫全部 `httpx.AsyncClient` + 信号量 + 超时 + 退避重试；磁盘 IO `to_thread` |
| 中间件 | `@app.middleware("http")`（BaseHTTPMiddleware）+ print 日志 | 纯 ASGI：RequestContext / AccessLog / SecurityHeaders / BodyLimit，JSON 结构化日志 + `trace_id` |
| 错误 | 到处 `raise HTTPException`，错误体不统一 | 领域异常体系 + 全局 handler + 统一 error envelope（含 `code`/`trace_id`） |
| 幂等 | 无 | `X-Idempotency-Key` 两阶段（SET NX → 完成写回 → 重放），SSE 与下单均复用 |
| 并发安全 | `SELECT FOR UPDATE`（SQLite 下无效）+ 超卖风险 | 原子 `UPDATE ... WHERE inventory >= qty`，DB 唯一幂等键兜底 |
| 流式 | SSE 裸生成器，无心跳/重连/缓冲控制，长事务持有 DB 连接 | Redis Stream 事件缓冲 + `Last-Event-ID` 续传 + 心跳 + 断线策略 + 短会话 |
| 异步任务 | Celery（同步 worker，与 async 应用割裂） | 自研 async 任务队列（Redis Stream consumer group + 重试/死信/优雅停机） |
| 安全 | 匿名可注册为 `admin`；JWT 密钥默认空；上传用原始文件名（路径穿越） | 角色提升受控；密钥启动强校验；uuid 文件名 + 魔数校验 + 大小限制；CORS 白名单 |
| 质量 | flake8 且 `\|\| true`，测试互相覆盖、断言错 | 113 个测试（unit + integration），ruff/mypy/pre-commit/CI 门禁，迁移双向验证 |

> 说明：`pytest`（113 passed / 1 skipped）、`ruff check`、`ruff format --check`、`mypy src/app`、真实 uvicorn 冒烟、
> `alembic upgrade/downgrade` 与 `uv lock` 均已在本机实测通过；覆盖率约 70%（CI 门禁 60%）。
> Docker 镜像构建需要可用的 Docker daemon，尚未在本机完成。

---

## 2. 架构总览

```text
                       ┌──────────────────────────────────────────┐
 HTTP / SSE / Webhook  │  pure-ASGI middleware                     │
 ────────────────────► │  RequestContext → AccessLog → SecHeaders  │
                       │  → BodyLimit → CORS                        │
                       └───────────────────┬──────────────────────┘
                                           │
                       ┌───────────────────▼──────────────────────┐
                       │  modules/<domain>/router.py  (thin)        │
                       │  validation · auth · idempotency guard     │
                       └───────────────────┬──────────────────────┘
                                           │
                       ┌───────────────────▼──────────────────────┐
                       │  service.py  业务编排 / 事务边界 / 策略     │
                       └───┬───────────────┬──────────────────┬───┘
                           │               │                  │
                 repository.py       shared gateways      async task queue
                 (SQLAlchemy 2.0)   (LLM/Embedding/       (Redis Streams)
                                     Feishu/Storage)
                           │               │                  │
                       ┌───▼───┐     ┌─────▼──────┐      ┌────▼────┐
                       │  DB   │     │  upstream  │      │ worker  │
                       └───────┘     └────────────┘      └─────────┘

 cross-cutting (src/app/core): config · logging/trace · errors · db · redis ·
 cache · idempotency · ratelimit · tasks · middleware · security · retry
```

依赖方向严格单向：`modules → shared/core`，`core` 不 import 任何业务模块；
`src/app/container.py` 是唯一的组合根（进程级资源都在这里创建、注入、关闭）。

完整目录树：

```text
src/
├── app/
│   ├── main.py                # create_app() + lifespan
│   ├── container.py           # 组合根：DB/Redis/HTTP/LLM/Agent/任务
│   ├── task_registry.py       # 注册后台任务
│   ├── api/
│   │   ├── router.py          # 路由总装
│   │   └── health.py          # /health/live、/health/ready
│   ├── core/                  # 基础设施，无业务规则
│   │   ├── config.py          # 强校验配置
│   │   ├── logging.py         # JSON 日志 + contextvars trace
│   │   ├── context.py         # trace_id / request_id / user_id
│   │   ├── exceptions.py      # 领域异常 + 统一 error envelope
│   │   ├── middleware.py      # 纯 ASGI 中间件
│   │   ├── database.py        # AsyncEngine / Session 工厂
│   │   ├── redis.py           # 可降级的 Redis 生命周期
│   │   ├── cache.py           # 本地 TTL + Redis 两级缓存
│   │   ├── idempotency.py     # Redis/内存两种实现
│   │   ├── ratelimit.py       # Lua 原子计数 / 内存实现
│   │   ├── tasks.py           # async 任务队列 + worker
│   │   ├── security.py        # bcrypt/argon2 + PyJWT
│   │   ├── retry.py           # 指数退避
│   │   └── pagination.py
│   ├── shared/                # 跨模块复用
│   │   ├── deps.py            # 认证、限流、幂等依赖
│   │   ├── embeddings.py      # 异步 embedding 网关 + 缓存
│   │   └── schemas.py         # error / health 契约
│   └── modules/
│       ├── auth/              # /token、/auth/refresh、/auth/me
│       ├── users/             # 注册、资料、RBAC
│       ├── items/             # 商品、标签、收藏、图片、搜索
│       ├── orders/            # 下单（原子扣减、价格快照、幂等）
│       ├── knowledge/         # 平台规则知识库（RAG）
│       ├── chat/              # LLM 网关、Agent 运行时、SSE、审批
│       │   ├── llm_gateway.py     # 流式解析 + 信号量 + 重试
│       │   ├── stream_runtime.py  # 有界工具调用循环
│       │   ├── stream.py          # StreamBuffer / 线程锁 / SSE 帧
│       │   ├── service.py         # 幂等运行、后台 worker、断线续传
│       │   ├── approvals.py       # HITL 状态机
│       │   └── tools.py           # 工具注册表（JSON Schema）
│       └── feishu/            # webhook / 绑定 / 发信 / 任务
├── worker.py                  # python -m src.worker
└── main.py                    # uvicorn src.main:app 兼容入口
```

---

## 3. 快速开始

### 3.1 本机最快路径（SQLite + 无 Redis，降级模式）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # 填入 SECRET_KEY（>=32 位）与可选的 LLM key
python -c "import secrets; print(secrets.token_urlsafe(48))"   # 生成 SECRET_KEY

alembic upgrade head          # 建表（独立于启动，生产同理）
uvicorn src.main:app --reload # http://127.0.0.1:8000/docs
```

无 Redis 时应用照常提供读写：幂等、限流、线程锁、SSE 回放自动退化为进程内实现
（只适用于单副本）。SSE 在无 `CHAT_API_KEY` 时会返回一个 `event: error` 帧，链路本身仍可用。

### 3.2 完整栈

```bash
cp .env.example .env
docker compose up -d --build       # db → redis → migrate → web + worker
docker compose logs -f web worker
```

`migrate` 是一次性服务，`web` 依赖它成功退出后才启动；迁移永远不会在应用启动命令里执行。

本机没有 Docker 时，也可以用 `scripts/dev_pg_redis.ps1` 拉起独立的 PG(pgvector)+Redis 容器，
再以三个进程（API / worker / `scripts/dev_llm_stub.py`）完成真实验证，步骤见
[docs/REAL-ENV-VERIFICATION.md](docs/REAL-ENV-VERIFICATION.md)。

### 3.3 常用命令

```bash
make test        # pytest（113 项）
make lint        # ruff check
make format      # ruff format
make typecheck   # mypy（CI 硬门禁）
make migrate     # alembic upgrade head
make worker      # 启动异步 worker
make admin EMAIL=you@example.com   # 把已有账号提升为管理员
```

可选能力：

```bash
pip install -r requirements-langgraph.txt   # LangGraph 运行时 + PG checkpointer
# .env: AGENT_RUNTIME=langgraph
#       POSTGRES_RAW_DSN=postgresql://user:pass@host:5432/db   (psycopg3 DSN)
pip install -r requirements-ai.txt          # CN-CLIP 视觉 + Playwright 比价
```

---

## 4. API 一览

| Method | Path | 认证 | 说明 |
| --- | --- | --- | --- |
| POST | `/token` | — | OAuth2 password 换 JWT（限流 10/min/IP） |
| POST | `/auth/refresh` | ✅ | 轮换 access token |
| GET | `/auth/me` | ✅ | 当前用户 |
| POST | `/users/register` | — | 注册（`role` 默认 user，禁止匿名提权） |
| GET | `/users/me` | ✅ | 资料 |
| GET | `/users/{id}` | — | 公开资料 |
| GET | `/users/admin/all` | ✅ admin | 分页用户列表 |
| PATCH | `/users/{id}/role` | ✅ admin | 角色变更（立即生效） |
| POST | `/items` | ✅ | 创建商品（支持 `X-Idempotency-Key`） |
| GET | `/items` | — | 分页 / 搜索 / 求购过滤 |
| GET | `/items/{id}` | — | 详情 |
| PUT | `/items/{id}` | ✅ owner/admin | 更新（库存驱动 `is_sold`） |
| DELETE | `/items/{id}` | ✅ owner/admin | 删除 |
| POST | `/items/{id}/buy` | ✅ | 下单（幂等 + 原子扣库存 + 价格快照） |
| POST | `/items/{id}/favorite` | ✅ | 收藏/取消 |
| GET/POST | `/items/tags` | GET 公开 / POST ✅ | 标签（两级缓存 + 写时失效） |
| DELETE | `/items/tags/{id}` | ✅ admin | 删除标签 |
| POST | `/items/upload-image` | ✅ | 上传图片（扩展名 + 魔数 + 大小校验，uuid 文件名） |
| POST | `/items/search-by-image` | — | 以图搜图（无视觉依赖时 503） |
| POST | `/items/search-by-text` | — | pgvector → CLIP → 词法 三级降级 |
| POST | `/items/analyze-upload` | ✅ | 上传前标签建议 |
| GET | `/items/dashboard/me` | ✅ | 个人看板聚合 |
| POST | `/items/ai/agent/stream` | ✅ | **SSE** 对话（旧路径 `/items/ai/agent` 保留） |
| GET | `/items/ai/history` | 可选 | 会话历史（匿名返回空数组，不 401） |
| DELETE | `/items/ai/history` | ✅ | 清空历史 |
| GET | `/items/ai/threads/{id}/status` | ✅ | 线程状态 + 待审批 |
| POST | `/items/ai/threads/{id}/resume` | ✅ | 人工审批通过/驳回并执行 |
| GET | `/items/ai/approvals` | ✅ | 我的待审批列表 |
| POST | `/feishu/webhook` | token | 飞书事件回调（先 ACK，任务队列处理） |
| POST | `/feishu/bind` | ✅ | 绑定飞书 open_id |
| GET | `/health/live` | — | 存活（不碰任何依赖） |
| GET | `/health/ready` | — | 就绪（DB 必须可用；Redis 视配置） |
| GET | `/health` | — | 兼容旧探针 |

统一错误体：

```json
{"error": {"code": "OUT_OF_STOCK", "message": "商品库存不足，下单失败",
           "trace_id": "d3f...", "details": {"item_id": 1}},
 "detail": "商品库存不足，下单失败"}
```

---

## 5. SSE 契约（前端必读）

请求：

```http
POST /items/ai/agent/stream
Authorization: Bearer <jwt>
Content-Type: application/json
X-Idempotency-Key: 6f1c...        # 前端为每条消息生成一次（重试复用）
X-Thread-ID: u12-main             # 会话 ID；不传则由后端生成
Last-Event-ID: 42-0               # 断线重连时带上最后收到的事件 id

{"message": "有什么一千以内的相机？"}
```

事件（标准 SSE，`id:` 可用于浏览器原生重连）：

| event | data | 说明 |
| --- | --- | --- |
| `token` | `{"text": "...", "content": "..."}` | 增量文本（`content` 兼容旧前端） |
| `tool_start` / `tool_end` | `{"name": "...", ...}` | 工具调用（前端可选择显示“正在查询”） |
| `interrupt_required` | `{"approval_id", "payload", "message"}` | 金额超阈值，已挂起等人工审批 |
| `done` | `{"steps": n}` / `{"replayed": true, ...}` | 结束 |
| `error` | `{"message", "code", "reason"}` | 失败（不泄露上游细节） |
| `aborted` | `{"reason": "client_disconnected"}` | 主动中止 |
| `: ping` | — | 每 15s 注释心跳，防网关 60s 空闲断连 |

行为保证：

1. **同一 `X-Idempotency-Key` + 同一消息**：重试不会重复调用 LLM，直接回放已生成事件；
2. **同一 key + 不同消息**：`409 CONFLICT`（客户端 bug，不是重试）；
3. **同一 `X-Thread-ID` 并发两条**：后到者收到 `THREAD_BUSY` 错误帧，不会破坏状态机；
4. **断线**：`AGENT_DISCONNECT_POLICY=continue` 时后台继续跑完并落库，重连带 `Last-Event-ID` 补齐；
   设为 `abort` 则立即取消上游流以省 token；
5. 反向代理必须关闭缓冲：`proxy_buffering off; proxy_read_timeout 300s;`（响应头已带
   `X-Accel-Buffering: no`）。

人工审批闭环：

```text
Agent 调用 create_order → 金额 >= AGENT_APPROVAL_THRESHOLD
  → 落库 agent_approvals(pending) → 前端收到 interrupt_required
  → 主管/用户 POST /items/ai/threads/{id}/resume {"approved": true, "approval_id": 7}
  → 条件 UPDATE 抢占 → 幂等下单（approval:{id}）→ 返回 order_id
  → 重复点击 / 已处理 → 409；超过 24h 未处理 → 定时任务置为 expired
```

---

## 6. 幂等、限流、任务

- **幂等**：Redis `SET NX EX` 占位 → 业务完成写回响应 → 相同 key 重放（`X-Idempotent-Replay: true`）。
  并发生成中重复请求返回 `409 IDEMPOTENCY_IN_PROGRESS`。DB 层 `orders.idempotency_key` 唯一索引兜底。
  `IDEMPOTENCY_HEADER_REQUIRED=true` 可强制所有受保护写接口必须带 key（生产推荐）。
- **限流**：Redis Lua 原子 `INCR+TTL`，按用户（已登录）或客户端 IP 计数；无 Redis 时进程内实现。
- **任务队列**：`@task("name")` 注册 async 函数；API 进程 `XADD`，worker 进程 `XREADGROUP` 消费；
  失败指数退避重试，超过次数进 `:dead` 死信流；`TASKS_EAGER=true` 时在进程内执行（测试/本地）。
  已注册任务：`items.embed_item`、`notifications.order_alert`、`feishu.process_event`、
  `chat.expire_approvals`。

---

## 7. 质量门禁

```bash
ruff check src/app tests          # lint
ruff format --check src/app tests # 格式
mypy src/app                      # 类型检查（0 errors，CI 硬门禁）
pytest --cov                      # 113 个测试 + 覆盖率（约 70%）
alembic upgrade head && alembic downgrade base   # 迁移可上可下
```

CI（`.github/workflows/ci.yml`）：lint/format/mypy/测试与覆盖率均为硬门禁 → 迁移双向验证 →
镜像构建推送（仅 push）。本机 0.2.1 实测：ruff 0 告警、mypy 0 错误、113 测试全绿、覆盖率约 70%。

---

## 8. 与 PDF 建议的逐条对照

| PDF 建议 | 落地位置 |
| --- | --- |
| 模块化单体 + 按域垂直切分 + 内部四层 | `src/app/modules/*`、`docs/ARCHITECTURE.md` |
| uv / Ruff / Mypy / structlog / OTel | `pyproject.toml`、自研结构化日志（structlog 不可安装）、`docs/ARCHITECTURE.md`「差距」 |
| 铁律 1：禁止事件循环阻塞 | 全链路 async；`docs/ARCHITECTURE.md` §4.1 有 grep 级清单 |
| 铁律 2：拒绝 BaseHTTPMiddleware | `core/middleware.py` 四个纯 ASGI 中间件 |
| 铁律 3：Schema 与 ORM 分离 + `expire_on_commit=False` | `modules/*/schemas.py`、`core/database.py` |
| 铁律 4：lifespan 统一资源与优雅停机 | `main.py`、`container.py` |
| 铁律 5：领域异常 + 防重幂等 | `core/exceptions.py`、`core/idempotency.py`、`shared/deps.py` |
| 铁律 6：迁移与容器启动解耦 | `docker-compose.yml` 的 `migrate` 服务、CI migrations job |
| SSE 幂等三态 + Redis Stream 续传 + Watchdog 锁 | `chat/service.py`、`chat/stream.py` |
| 三层背压（会话锁 / 用户配额 / 上游信号量） | `ThreadLockManager`、`rate_limit()`、`LLMGateway.Semaphore` |
| 断线策略 A/B | `AGENT_DISCONNECT_POLICY` + `chat/service.py` |
| Checkpointer 双池隔离 | `chat/checkpointer.py`：独立 psycopg3 池 + `AsyncPostgresSaver`；`AGENT_RUNTIME=langgraph` 启用 |
| 僵尸 HITL 清理 | `chat/tasks.expire_approvals` + 生命周期定时任务 |
| State 载荷瘦身 | 工具输出截断、历史窗口 `AGENT_CONTEXT_MESSAGES`、消息落库截断 8000 字符 |
| 5 条质量门禁 | `.github/workflows/ci.yml`、`pyproject.toml`、`tests/` |

取舍与未完成项（诚实清单）见 `docs/ARCHITECTURE.md` 第 7 节；破坏性变更见 `docs/MIGRATION.md`。
