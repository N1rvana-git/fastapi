# 真实环境联调报告（PostgreSQL + Redis + 独立 Worker）

> 验证日期：2026-11-14 · 代码版本：`0e57e21` + 本轮修复
> 目的：证明架构亮点不是"只在 SQLite 内存降级模式下成立"，而是在真实 PG(vector)+Redis 上仍然成立。

---

## 1. 环境

| 组件 | 版本 / 形态 |
| --- | --- |
| PostgreSQL | 15 + `pgvector 0.8.6`（Docker `pgvector/pgvector:pg15`，端口 55432） |
| Redis | 7 (alpine)，端口 56379，AOF 未开启（临时验证库） |
| API | `uvicorn src.main:app`（独立进程，端口 8124） |
| Worker | `python -m src.worker`（独立进程，consumer group `workers`） |
| LLM | `scripts/dev_llm_stub.py`（本地 OpenAI 兼容 SSE stub，端口 8125） |
| Python | 3.11.8 / `.venv` |

启动方式见 `scripts/dev_pg_redis.ps1`。**未触碰用户已有的 `postgres_db` / `reactive_resume-*` 容器**。

---

## 2. 验证结果

| # | 检查项 | 命令 / 操作 | 结果 |
| --- | --- | --- | --- |
| 1 | 迁移在 PG 上可用 | `alembic upgrade head` | ✅ `b2f4c7d91a30`，10 张表，`item.embedding` 为 `vector` 类型 |
| 2 | 就绪探针 | `GET /health/ready` | ✅ DB 15ms、Redis 1.4ms，`status=ok` |
| 3 | 注册 / 登录 | `POST /users/register` → `POST /token` | ✅ 201 / 200 |
| 4 | 建商品 + 幂等 | `POST /items` | ✅ 201，写入任务队列 |
| 5 | 原子扣库存 | `POST /items/1/buy` | ✅ 200，库存 2→1，订单写入价格快照 `1500` |
| 6 | 任务队列消费 | `XLEN/XPENDING/XINFO GROUPS` | ✅ `entries-read=3, lag=0, pending=0`；worker 日志 `task completed` |
| 7 | 阻塞读稳定性 | 观察 worker 日志 | ✅ 修复后无 `TimeoutError` 刷屏（见 §3） |
| 8 | SSE 流式（Redis 缓冲） | `POST /items/ai/agent/stream` | ✅ 5 个 `token` + `done`，事件 id 来自 Redis Stream |
| 9 | 幂等重放 | 同一 `X-Idempotency-Key` 再请求 | ✅ 返回同一批事件，`XLEN` 前后均为 6（未重复生成） |
| 10 | 幂等键生命周期 | `TTL idem:chat:1:pg-ok-1` | ✅ 599s；失败运行会释放 key 以允许重试（设计如此） |
| 11 | 线程锁释放 | `SCAN chat:lock:*` | ✅ 运行结束后无残留 |
| 12 | 会话历史落库 | `GET /items/ai/history?thread_id=...` | ✅ user + assistant 两条 |
| 13 | HITL 挂起 | 审批表写入 pending | ✅ `/threads/u2:pg/status` → `is_interrupted=true` |
| 14 | HITL 通过并下单 | `POST .../resume {"approved":true}` | ✅ 订单 #2，库存 1→0，`is_sold=true`，审批 `resolved_order_id=2` |
| 15 | 重复审批 | 再次 `resume` | ✅ 409，未重复扣库存 |
| 16 | pgvector 语义检索 | 写入 1024 维向量后 `cosine_distance` 排序 | ✅ 相似向量排第一（1.0），正交向量 0.031 |
| 17 | 邮箱唯一索引（方向 2） | `alembic upgrade head` → `d4b7e2a9c1f0`，插入 `SELLER@example.com` | ✅ 索引 `users_email_lower_key` 生效，大小写重复被 PG 拒绝 |

数据库侧的最终状态（摘要）：

```sql
-- agent_approvals
 id |  status  | resolved_order_id
  1 | approved |                 2
-- item
 id | inventory | is_sold
  1 |         0 | t
-- orders
 id | buyer_id | item_id | price |         address
  1 |        2 |       1 |  1500 |
  2 |        2 |       1 |  1500 | 上海市浦东新区测试路1号
```

---

## 3. 真实环境暴露并修复的缺陷

**现象**：worker 每秒打印一次 `redis.exceptions.TimeoutError: Timeout reading from 127.0.0.1:56379`，
尽管任务最终仍被消费（`XREADGROUP BLOCK 1000` 与共享客户端 `socket_timeout=1.0` 相冲突）。

**根因**：`RedisManager` 的共享客户端 `socket_timeout` 默认为 1s，而 `XREADGROUP`/`XREAD` 的
`BLOCK` 参数是 1000ms —— 阻塞读天然会超过 socket 超时，于是每次读都被判超时。

**修复**（`src/app/core/redis.py`、`src/app/core/tasks.py`、`src/app/modules/chat/stream.py`）：

- 新增 `RedisManager.blocking_client(name, socket_timeout=None)`：为阻塞命令分配独立连接池，
  不设 socket 超时（由 `BLOCK` 参数自身限时）；
- `TaskWorker` 使用 `blocking_client("worker")`；`RedisStreamBuffer` 使用 `blocking_client("sse")`；
- worker 读取失败日志从 `logger.exception` 降为单行 warning，避免故障时刷爆日志；
- 新增回归测试：
  `tests/unit/test_stream.py::test_stream_buffer_prefers_blocking_redis_client`
  与 `::test_stream_buffer_falls_back_when_redis_is_down`。

修复后 worker 日志稳定为 `task completed`，`pending=0, lag=0`。

---

## 4. 复现步骤

```powershell
# 1) 启动真实依赖（独立容器，不碰已有服务）
./scripts/dev_pg_redis.ps1

# 2) 使用脚本打印的环境变量
$env:DATABASE_URL = "postgresql+asyncpg://xjb:xjbpass@127.0.0.1:55432/xjbdb"
$env:REDIS_URL = "redis://127.0.0.1:56379/0"
$env:REDIS_REQUIRED = "true"
$env:TASKS_EAGER = "false"

# 3) 迁移 + 三个进程
python -m alembic upgrade head
python -m uvicorn src.main:app --port 8000
python -m src.worker
python scripts/dev_llm_stub.py --port 8125   # 可选：本地流式 LLM

# 4) 验证
curl http://127.0.0.1:8000/health/ready
curl -X POST http://127.0.0.1:8000/items/ai/agent/stream \
  -H "Authorization: Bearer <jwt>" -H "X-Idempotency-Key: demo-1" \
  -H "Content-Type: application/json" -d '{"message":"你好"}'
docker exec xjb-redis redis-cli XINFO GROUPS xianxiaobao:tasks
```

---

## 5. 未覆盖

- 真实商业 LLM（只用了本地 stub）与真实飞书租户；
- Playwright 爬虫在容器内的浏览器依赖；
- pgvector **索引**（HNSW/IVFFlat）与大规模召回性能——当前只验证了 `ORDER BY cosine_distance`
  的正确性，生产数据量大时应建索引并做压测；
- Docker 镜像构建（`docker build`）未在本次执行，仅验证了容器化依赖服务。
