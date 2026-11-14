# 路线 B：并发压测报告（0.3.0-perf）

> 目标：用真实 PostgreSQL 15 + pgvector、Redis 7 和独立 uvicorn/worker 进程，量化
> “热点库存抢购”的吞吐与尾延迟，验证 **零超卖**，并用 50 路并发 SSE 验证流式链路容量。
>
> 结论先行：**并发正确性达标（5 件库存只产生 5 笔订单，无超卖；100 个独立商品 100 笔订单全部成功），
> 但本机（Windows 11 + Docker Desktop/WSL2）的绝对延迟不代表生产 Linux 环境**。
> 压测同时暴露并修复了 4 个真实容量缺陷，见第 4 节。

## 1. 环境与方法

| 项 | 值 |
|---|---|
| 主机 | Windows 11，Docker Desktop（WSL2 后端），共享开发机 |
| 数据库 | PostgreSQL 15 + pgvector 0.8.6，容器 `xjb-pg`，127.0.0.1:55432 |
| 缓存/队列 | Redis 7，容器 `xjb-redis`，127.0.0.1:56379 |
| 应用 | `uvicorn src.main:app` 单进程单 worker，独立 `src.worker` 进程 |
| 压测工具 | Locust 2.47.0（抢购）、自研 asyncio SSE harness（50 路流） |
| 数据准备 | `scripts/perf/seed_loadtest.py` 直接建用户/商品并预签 JWT（绕过登录限流） |
| 客户端连接 | 每个 locust 用户先发一次 `/health/live` 预热连接（避免 Windows 新建连接 ~20ms 的噪声） |

关键方法说明：

* 每个模拟买家只发起 **一次** 购买（`wait_time` 置为 3600s），保证“100 并发”是一次干净的突发，而不是重复轮询；
* `400 OUT_OF_STOCK` 是**正确业务结果**，在 locust 中标记为 success，只有 5xx/429/409 才算失败；
* 所有结果都回到数据库用 SQL 复核：订单数、去重买家数、价格快照、库存、`is_sold`；
* SSE 使用 50 个不同用户、50 个不同 `X-Thread-ID`/幂等键，LLM 用本地 stub（`--chunks 10 --delay 0.25`，约 2.5s/流）。

## 2. 结果

### 2.1 框架基线（无数据库写入）

100 用户持续请求 `/health/live` 10s：

| 指标 | 数值 |
|---|---|
| 吞吐 | **191 – 455 req/s**（随宿主机负载波动） |
| p50 | 55 – 260 ms |
| p95 | 190 – 980 ms |
| 失败 | 0 |

该接口不触达 DB/Redis，说明 **Python/FastAPI 框架本身不是瓶颈**，波动来自共享宿主机。

### 2.2 热点抢购：100 并发 vs 库存 5

商品：`inventory=5`，`price=100`；100 个不同买家同时下单。

| 指标 | 数值 |
|---|---|
| 请求数 | 100（全部完成，0 失败） |
| 结果分布 | 5 × `200` 下单成功；95 × `400 OUT_OF_STOCK` |
| p50 / p95 / p99 | **2.60s / 4.50s / 6.80s** |
| 突发吞吐 | **14.4 req/s** |
| 数据库复核 | `orders=5`，`distinct buyer=5`，`price=100..100`，`inventory=0`，`is_sold=true` |

> 结论：**零超卖**。热点行的 `UPDATE ... WHERE inventory >= 1` 在 PostgreSQL 中串行化，100 个并发
> 只能一个接一个地拿到行锁；这是“用串行换正确性”的预期代价，也是 14.4 req/s 上不去的原因。
> 若业务要求更高，需要排队/预扣（Redis 原子扣减 + 异步落库）或分片库存，而不是加大连接池。

原始数据：`.perf/20261114-203115/locust_contended.txt`、`buy_contended_stats.csv`。

### 2.3 无热点基线：100 个商品各 1 件库存

每个买家抢自己的商品，消除单行锁：

| 指标 | 数值 |
|---|---|
| 请求数 | 100（0 失败） |
| p50 / p95 / p99 | **3.06s / 4.87s / 4.90s** |
| 突发吞吐 | **20.5 req/s** |
| 数据库复核（后续完整跑） | `orders=100`，`distinct item=100`，`distinct buyer=100`，100 个商品全部 `inventory=0 & is_sold` |

> 无热点时吞吐提升有限（20.5 vs 14.4 req/s），说明在本机剩余瓶颈是 **Windows + Docker
> 的请求/连接处理与宿主机争抢**，而不是行锁本身。生产 Linux 上应以本报告脚本重跑取值。

原始数据：`.perf/20261114-202952/locust_unconstrained.txt`、`buy_newworker_stats.csv`。

### 2.4 50 路并发 SSE

| 指标 | 数值 |
|---|---|
| 流数量 / 成功 | **50 / 50**（0 失败） |
| 收到 token 帧 | 500（每流 10 帧 + done） |
| 首 token 延迟 p50/p95/p99 | **5.93s / 8.17s / 8.25s** |
| 流总时长 p50/p95 | **8.15s / 10.54s** |
| 观测最大并发 | 50 |

原始数据：`.perf/20261114-205951/sse_results.json`。

> 50 路同时在线时，阻塞式 `XREAD`、限流脚本、幂等键、任务入队会同时争用 Redis 连接池；
> 初始配置下 50 路里只有 4 路成功，见第 4.1/4.2 节。

## 3. 复现步骤

```powershell
# 1) 依赖（PG15 + pgvector / Redis7）
docker run -d --name xjb-pg -e POSTGRES_USER=xjb -e POSTGRES_PASSWORD=xjbpass `
  -e POSTGRES_DB=xjbdb -p 55432:5432 pgvector/pgvector:pg15
docker run -d --name xjb-redis -p 56379:6379 redis:alpine
docker exec xjb-pg psql -U xjb -d xjbdb -c "CREATE EXTENSION IF NOT EXISTS vector;"

$env:DATABASE_URL="postgresql+asyncpg://xjb:xjbpass@127.0.0.1:55432/xjbdb"
$env:REDIS_URL="redis://127.0.0.1:56379/0"
$env:SECRET_KEY="local-dev-secret-key-that-is-long-enough-32"
$env:ENVIRONMENT="development"
python -m alembic upgrade head

# 2) 启动 API / worker / LLM stub（三个终端）
$env:CHAT_API_KEY="stub"; $env:CHAT_BASE_URL="http://127.0.0.1:8125/v1"
python -m uvicorn src.main:app --port 8124 --no-access-log
python -m src.worker
python scripts/dev_llm_stub.py --port 8125 --chunks 10 --delay 0.25

# 3) 造数据（100 买家 + 1 个库存 5 的商品）
python scripts/perf/seed_loadtest.py --buyers 100 --stock 5 --items 1 --price 100

# 4) 抢购压测（100 用户、一次性突发）
$env:PYTHONUTF8="1"; $env:PERF_TOKENS=".perf/<run>/tokens.json"
locust -f scripts/perf/locustfile_buy.py --headless -u 100 -r 200 -t 8s `
  --host http://127.0.0.1:8124 --csv .perf/<run>/buy_contended --only-summary

# 5) 50 路 SSE
python scripts/perf/sse_load.py --streams 50 --tokens .perf/<run>/tokens.json

# 6) SQL 复核（示例：item=109）
docker exec xjb-pg psql -U xjb -d xjbdb -c `
  "select count(*), count(distinct buyer_id) from orders where item_id=109;"
docker exec xjb-pg psql -U xjb -d xjbdb -c `
  "select inventory, is_sold from item where id=109;"
```

辅助脚本：`scripts/perf/locustfile_health.py`（框架基线）、`concurrency_probe.py`（连接/阶段探测）、
`diagnose_latency.py`（单请求与 DB 分解）、`analyze_log.py`（JSON 访问日志 P50/P95/P99）。

## 4. 压测暴露并修复的容量缺陷

### 4.1 阻塞型 Redis 客户端池硬编码 4（P0）

50 路 SSE 每路持有一个 `XREAD BLOCK` 连接，第 5 路开始直接
`redis.exceptions.MaxConnectionsError: Too many connections` → HTTP 500。
修复：`REDIS_BLOCKING_MAX_CONNECTIONS`（默认 100），`blocking_client()` 使用独立池。
回归测试：`tests/unit/test_redis_pool.py`。

### 4.2 共享 Redis 池默认 20，被限流脚本打满（P0）

50 路 SSE 每路都执行 rate-limit `EVAL`，20 个连接瞬间耗尽，仍返回
`MaxConnectionsError`。修复：`REDIS_MAX_CONNECTIONS` 默认 100，`.env.example` 同步说明。

### 4.3 `UserModel.items/favourites` 的 `selectin` 放大（P1）

加载一个商品 → 加载 owner → 又把 owner 的**全部商品**及其 owner/tags 一起 `selectin`，
压测数据量下单次 `/buy` 从 81ms 恶化到 133ms+，并放大 DB 负载。
修复：两个关系改为 `lazy="raise"`，需要时显式 `selectinload`。
（dashboard 通过 `list_for_owner` 查询，不依赖该关系。）

### 4.4 Windows Selector 事件循环被全局强制（P1）

为 psycopg3 兼容，`src/main.py` 曾无条件切换 `WindowsSelectorEventLoopPolicy`；该循环在 Windows
上新建连接受 ~15.6ms 定时器粒度影响，100 并发连接被串行化。修复：仅在
`AGENT_RUNTIME=langgraph` 或 `LANGGRAPH_ENABLED=true` 时切换（worker、conftest 同步）。

### 4.5 其它

* **默认 DB 池 30** 在 100 并发热点抢购下出现 5 次 `QueuePool` 超时（500）；调大到 80（`DB_POOL_SIZE=40` + overflow 40）后 100/100 无 5xx。生产建议把池超时映射为 `503 + Retry-After`，而不是 500（未在本次实现）。
* **LLM stub backlog=5**（`ThreadingHTTPServer` 默认）导致 50 路 SSE 被拒/重试，表现为 ~15s 后 `error` 事件；修复为 256。这是测试工具问题，不是业务代码。
* **`ChatRecord` 的 `session.refresh()`** 在并发关闭会话时偶发 `InvalidRequestError`，因 `expire_on_commit=False`，已移除该调用（修复 Feishu 测试偶发失败）。

## 5. 测量陷阱（避免误读）

1. **系统代理**：本机 Python 检测到 `http://127.0.0.1:7896`，`requests/httpx` 默认 `trust_env=True`
   会把 localhost 请求送进代理，产生 502/数秒延迟。压测脚本统一 `trust_env=False`。
2. **新建连接成本**：Windows loopback 上 100 个并发新连接本身约 2s（用 stdlib `http.server`
   对照同样如此），因此 locust 用户先做一次健康检查预热，再计量购买。
3. **日志重定向**：PowerShell `>` 重定向会拖慢同步日志写入；压测用 OS 级重定向（`cmd /c ... > file`），
   并可将 `LOG_LEVEL=CRITICAL` 关闭访问日志做纯性能对照。
4. **客户端差异**：单个 asyncio/httpx 进程并发 100 条请求的客户端开销很大，SSE 用 warm-up + 50 路；
   抢购以 Locust/gevent 为准。
5. **共享开发机**：同一台机器上的浏览器、IDE、其它容器会显著影响绝对值，报告中的区间反映该现实。

## 6. 结论与后续

* **正确性**：热点 5 件库存 → 5 笔订单、5 个买家、价格快照正确、库存 0、`is_sold=true`；100 个独立商品 → 100 笔订单、全部售罄。**零超卖，可写进简历。**
* **性能**：本机热点抢购 p99 6.8s / 14.4 req/s，无热点 20.5 req/s；50 路 SSE 全部成功。
  这些数字用于证明“测过、知道瓶颈在哪”，不建议直接当作生产 SLA。
* **下一步**：在 Linux CI runner（或云主机）用同一套脚本复测；若要提升热点吞吐，引入
  Redis 预扣 + 异步落库/排队，而不是继续加连接池。
