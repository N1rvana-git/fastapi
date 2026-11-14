# 迁移指南（旧版 → 0.2.0）

本次重构是**有意的破坏性升级**。下面按"必须改、建议改、可忽略"分层，最后给出旧代码的清理命令。

---

## 1. 一分钟版本

```bash
# 1) 重新安装依赖（依赖清单已重写，不再是从开发机导出的 pip freeze）
pip install -r requirements-dev.txt

# 2) 更新 .env：至少设置 SECRET_KEY（>= 32 字符）
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 3) 备份数据库，然后执行迁移（单独一步，不要在应用启动时执行）
pg_dump ... > backup.sql
alembic upgrade head

# 4) 后端需要同步改造的：注册路径、登录响应、错误体、SSE 请求头
# 5) 删除旧代码（重构工具所在的沙箱禁止删除文件，所以旧包暂时是"导入即报错"的守卫）
git rm -r src/posts src/auth src/users health
git rm src/feishu/router.py
git rm tests/test_main.py tests/test_user.py tests/test_feishu.py
git rm -r tests/test_unit
rm -f tests/test_analyze_upload.py            # 未跟踪的占位文件
git commit -m "refactor: modular monolith architecture (0.2.0)"
```

> `src/config.py` / `src/database.py` / `src/llm_policy.py` 已被替换为**兼容 shim**，
> 旧脚本仍可 import；确定无人使用后再 `git rm`。
> `src/posts` / `src/auth` / `src/users` / `src/feishu` / `health` 的 `__init__.py`
> 现在是守卫：import 会抛出带迁移指引的 `ImportError`。执行上面的 `git rm` 后自然消失。
> 你自己的学习笔记（`FastApi-practice.md`、`FastAPI项目重读笔记.md`）不属于代码，
> 是否保留由你决定。

---

## 2. 接口变更

### 2.1 路径映射

| 旧 | 新 | 备注 |
| --- | --- | --- |
| `POST /items/register` | `POST /users/register` | 旧路径已移除；注册归属于 users 域 |
| `POST /users/register`（body 含 username/age/phone） | `POST /users/register`（email + password，username 可选） | `role` 默认 user |
| `GET /users/{id}` | 不变 | 响应去掉 age/phone（管理员列表仍可看） |
| `GET /health` | `GET /health/live` + `GET /health/ready` | `/health` 保留，语义=存活 |
| `POST /items/ai/agent` | `POST /items/ai/agent/stream` | 旧路径保留（别名），推荐新路径 |
| `GET/DELETE /items/ai/history/` | `/items/ai/history` | 末尾斜杠仍可用（307） |
| `GET /items/tags/`、`POST /items/tags/` | `/items/tags` | 末尾斜杠仍可用 |
| 其它商品/订单接口 | 不变 | 下单仍为 `POST /items/{id}/buy` |

### 2.2 响应变化

- 创建商品/注册：`200` → **`201 Created`**；
- 删除商品/标签：`200` → **`204 No Content`**（无 body）；
- 商品列表：`{"total", "items"}` → `{"total", "items", "skip", "limit"}`（新增字段，向后兼容）；
- 商品对象新增 `tags`、`created_at`；**绝不**返回 `embedding`;
- 错误体统一为：

```json
{"error": {"code": "NOT_FOUND", "message": "...", "trace_id": "...", "details": {}},
 "detail": "..."}
```

`detail` 字段保留，旧的 `response.json()["detail"]` 读取仍可工作；新代码请用 `error.code` 做分支。

- 分页参数：`limit` 上限 100（超过 422），`skip <= 100000`。

### 2.3 认证变化

- JWT 的 `sub` 从 **email** 改为 **user id**，并新增 `iss/aud/jti/nbf`：**旧 token 全部失效**，需重新登录；
- `POST /token` 响应新增 `expires_in/role/user_id/email`；
- 新增 `POST /auth/refresh`、`GET /auth/me`；
- 密码策略：8–72 字节；注册时 `role=admin` 仅在 `ALLOW_PUBLIC_ROLE_SELECTION=true`
  或调用者是管理员时生效，否则强制为 `user`；
- 管理员接口：`GET /users/admin/all`、`PATCH /users/{id}/role`、`DELETE /items/tags/{id}`。

### 2.4 SSE 契约

前端需要发送：

- `X-Idempotency-Key`：每条用户消息一个（重试时复用同一个）；
- `X-Thread-ID`：会话 ID（可省略，由后端生成并回传响应头）；
- 重连带 `Last-Event-ID`（浏览器 `EventSource` 自动带；`fetch` 需手动保存 `id:`）。

事件名从"只有 data 内容"升级为命名事件 `token/tool_start/tool_end/interrupt_required/done/error/aborted`。
`token` 的 data 同时包含 `text` 与 `content`，旧前端读 `content` 仍可工作。

新增：`GET /items/ai/threads/{id}/status`、`POST /items/ai/threads/{id}/resume`、
`GET /items/ai/approvals`（人工审批闭环）。

### 2.5 移除 Celery

- `src/worker.py` 现在是 **async 任务 worker**：`python -m src.worker`；
- 业务里 `inject_embedding_task.delay(...)` → `dispatcher.enqueue("items.embed_item", item_id=...)`；
- `docker-compose.yml` 的 `celery_worker` 服务改为 `worker`（`command: python -m src.worker`）；
- 依赖中删除 `celery/kombu/billiard/amqp/vine`。

---

## 3. 数据库迁移

新增迁移：`alembic/versions/b2f4c7d91a30_core_architecture_refactor.py`

| 表 | 变更 |
| --- | --- |
| `users` | `+ created_at`, `+ updated_at` |
| `item` | `+ created_at`, `+ updated_at`, `is_sold` 回填并改为 NOT NULL，`+ owner_id` 索引 |
| `favourites` | **新表**（旧路由引用了不存在的表，收藏接口必然 500） |
| `orders` | `+ quantity`, `+ price`（从 item 回填）, `+ address`, `+ idempotency_key`（唯一索引）, `+ updated_at`, `+ buyer/item` 索引 |
| `ai_chat_records` | `+ thread_id`（回填 `'u{user_id}:main'`）, `+ user_id/thread_id` 索引 |
| `agent_approvals` | **新表**（HITL 队列，唯一幂等键 + 过期时间） |
| `knowledge_base` | `+ created_at` |

执行：

```bash
pg_dump -Fc "$DATABASE_URL" > backup.dump        # 必须先备份
alembic upgrade head
# 验证
psql "$DATABASE_URL" -c "\d orders" | grep idempotency_key
```

回滚：

```bash
alembic downgrade -1          # 回到 c924f1debfb5
# 注意：downgrade 会丢失新增列的数据（thread_id、订单价格快照等）
```

顺带修复：旧初始迁移用 `server_default=text("now()")`，在 SQLite 上建表失败；已改为
`sa.func.now()`，因此 `alembic upgrade head` 现在也能在 SQLite 上跑通（CI 会验证 up/down）。

---

## 4. 配置变更

必须新增/修改的键（详见 `.env.example`）：

| 键 | 说明 |
| --- | --- |
| `SECRET_KEY` | **必填**（>=32），生产缺失/过短会启动失败 |
| `ENVIRONMENT` | `development/test/staging/production`，影响安全校验与 CORS |
| `REDIS_REQUIRED` | `true` 时 Redis 不可用会让 `/health/ready` 返回 503 |
| `AGENT_APPROVAL_THRESHOLD` | 超过该金额的下单需人工审批（默认 1000） |
| `AGENT_DISCONNECT_POLICY` | `continue`（默认，跑完落库）或 `abort`（立即省 token） |
| `IDEMPOTENCY_HEADER_REQUIRED` | 生产建议 `true`：写接口强制带幂等键 |
| `CHAT_API_KEY` | LLM key；旧的 `API_KEY` 仍兼容（`API_KEy` 拼写别名已在 0.2.1 移除） |
| `VISION_ENABLED` | 不需要以图搜图时设 `false`，省掉模型加载 |
| `UPLOAD_DIR` | 上传目录（可为绝对路径） |

旧的 `ZHIPU_EMBEDDING_MODEL`/`ALLOWED_*` 校验保留，但**启动时**就会校验，
模型不在白名单直接失败（之前是请求时 500）。

---

## 5. 依赖与运行方式

- `requirements.txt` 从"pip freeze 全量导出（含 torch/CUDA/Jupyter）"改为**分层清单**：
  - `requirements.txt`：运行时基线（无 torch）
  - `requirements-ai.txt`：可选 AI/浏览器
  - `requirements-dev.txt`：测试与 lint
- Dockerfile：多阶段构建、非 root、`HEALTHCHECK`、**不在 CMD 里跑迁移**；
  AI 依赖通过 `--build-arg INSTALL_AI=1` 可选安装。
- compose：新增一次性 `migrate` 服务；`web` 依赖它成功完成；新增 `worker`。
- 新增 `pyproject.toml`（依赖元数据 + ruff/mypy/coverage 配置）、`Makefile`、
  `.pre-commit-config.yaml`。

> 若继续用旧 `requirements.txt` 安装，会得到与代码不匹配的环境（缺少
> `aiosqlite` 之外的新依赖数量不多，但含大量无关包，镜像 ~5GB）。

---

## 6. 行为变更（可能影响业务）

1. **不能购买自己发布的商品**（返回 400）；
2. **求购贴（`is_offer=false`）不可下单**（返回 400）；
3. **库存扣减改为原子 UPDATE**：并发下第二个请求得到 `OUT_OF_STOCK`，而不是 409 锁冲突；
4. **注册不再自动成为卖家/管理员**；
5. **上传接口需要登录**，且只接受 `jpg/jpeg/png/webp/gif` 且内容魔数匹配；
6. **AI 历史匿名访问返回 `[]`** 而不是 401（保持前端首屏不刷 401）；
7. **Feishu webhook 立即 ACK**，LLM 回复走任务队列（重试 3 次），不再在请求内阻塞；
8. 价格快照：订单记录下单时的单价，之后卖家改价不影响历史订单。

---

## 7. 未来工作（与本文档相邻）

- 生成并提交 `uv.lock`（本机离线无法生成）；
- 覆盖率从 60% 门槛逐步提高到核心模块 80%（当前约 67%）；
- 接入 OpenTelemetry（保留 `trace_id` 上下文即可低成本挂载）；
- 如需完整 LangGraph 状态机：安装 `langgraph` + `langgraph-checkpoint-postgres`，
  实现 `AgentRuntime` 协议，并在 lifespan 中按"双池隔离"建 checkpointer 连接池。
