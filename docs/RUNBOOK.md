# 运维手册（Runbook）

面向"把服务跑起来、出问题能定位、发版不炸"的最小可执行清单。

---

## 1. 部署拓扑

```text
                    ┌──────────────────────────┐
   Users ──HTTPS──► │ Ingress / Nginx（关缓冲）│
                    └───────┬──────────────────┘
                            │
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
        web-0 (API)    web-1 (API)   web-N (API)     ← 各 1 进程，横向扩副本
              │             │              │
              ├─────────────┴──────────────┤
              ▼                            ▼
      PostgreSQL + pgvector            Redis（幂等/锁/流/队列）
                                            ▲
                                            │ XREADGROUP
                                     worker-0..N（任务）
```

- **API 无状态**：不在本地保存会话；上传目录需共享卷或对象存储。
- **worker 独立扩缩容**：LLM/飞书/embedding 任务都在这里。
- **迁移单实例**：K8s Job / compose `migrate`，绝不在 API 启动时执行。

---

## 2. 上线前检查

```text
[ ] ENVIRONMENT=production
[ ] SECRET_KEY 已用 secrets 管理，>=32 字符，未入库/未进镜像
[ ] DATABASE_URL 为 postgresql+asyncpg:// 且已启用 pgvector 扩展
[ ] redis 可达；REDIS_REQUIRED=true（多副本时必须有 Redis）
[ ] CORS_ORIGINS 为真实前端域名，CORS_ALLOW_ALL_IN_DEV=false
[ ] IDEMPOTENCY_HEADER_REQUIRED=true（前端已发送 X-Idempotency-Key）
[ ] LOG_FORMAT=json，日志已接入采集（Loki/ELK）
[ ] /health/live 与 /health/ready 探针已配置且路径正确
[ ] Ingress 已关闭 SSE 缓冲：proxy_buffering off; proxy_read_timeout 300s;
[ ] terminationGracePeriodSeconds >= 60
[ ] 备份任务（pg_dump 每日 + WAL 归档）已生效
```

---

## 3. Kubernetes 参考片段

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec:
  replicas: 3
  strategy: {type: RollingUpdate, rollingUpdate: {maxUnavailable: 0, maxSurge: 1}}
  template:
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: api
          image: ghcr.io/org/xianxiaobao-fastapi:sha
          ports: [{containerPort: 8000}]
          envFrom: [{secretRef: {name: api-secrets}}]
          readinessProbe:
            httpGet: {path: /health/ready, port: 8000}
            periodSeconds: 10
            failureThreshold: 3
          livenessProbe:
            httpGet: {path: /health/live, port: 8000}
            periodSeconds: 20
            failureThreshold: 3
          resources:
            requests: {cpu: 250m, memory: 512Mi}
            limits:   {cpu: "1",  memory: 1Gi}
          lifecycle:
            preStop:
              exec: {command: ["sleep", "10"]}   # 让 LB 摘流后再开始关闭
---
apiVersion: batch/v1
kind: Job
metadata: {name: migrate-<sha>}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: ghcr.io/org/xianxiaobao-fastapi:sha
          command: ["alembic", "upgrade", "head"]
```

worker 用同一镜像，`command: ["python", "-m", "src.worker"]`，不需要端口探针，
可用 `exec` 探针检查进程存活。**注意**：worker 也必须有 `terminationGracePeriodSeconds`，
否则任务会被硬杀（队列会重投，但可能重复执行；任务应保持幂等）。

### 反向代理（SSE 必须）

```nginx
location /items/ai/ {
    proxy_pass http://api_upstream;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;     # > 单次 Agent 最大执行时长
    chunked_transfer_encoding on;
}
```

Ingress-nginx 等价注解：

```yaml
nginx.ingress.kubernetes.io/proxy-buffering: "off"
nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
nginx.ingress.kubernetes.io/proxy-body-size: "12m"
```

---

## 4. 日常操作

| 操作 | 命令 |
| --- | --- |
| 查看健康 | `curl -s localhost:8000/health/ready \| jq` |
| 提升管理员 | `python -m src.make_admin --email a@b.com` |
| 手动跑迁移 | `alembic upgrade head`（单实例！） |
| 回滚一个迁移 | `alembic downgrade -1` |
| 查看任务积压 | `redis-cli XLEN xianxiaobao:tasks`、`XPENDING xianxiaobao:tasks workers` |
| 查看死信 | `redis-cli XRANGE xianxiaobao:tasks:dead - +` |
| 清理某会话流 | `redis-cli DEL chat:stream:<thread_id>` |
| 查看锁 | `redis-cli GET chat:lock:<thread_id>` |
| 清理僵尸审批 | 定时任务自动执行；手动：调用 `chat.expire_approvals` 或 SQL 置 `expired` |

---

## 5. 故障手册

### 5.1 `/health/ready` 503，`database` 失败

- 看 `checks[].detail`：连接超时 / 认证失败 / 库不存在；
- 检查连接池耗尽：日志中 `QueuePool limit ... overflow`；临时扩 `DB_POOL_SIZE` 或排查慢查询；
- 慢 SQL：`DB_STATEMENT_TIMEOUT_MS` 默认 15s，超时会直接报错而不是拖垮副本。

### 5.2 SSE 卡住 / 前端看不到"打字机"

1. 先确认响应头有 `X-Accel-Buffering: no`；
2. 检查 Ingress `proxy_buffering off`（最常见原因）；
3. 检查是否命中限流（429）或会话锁（`THREAD_BUSY` 帧）；
4. 看日志 `event=chat_stream_attached outcome=...`：
   - `in_progress`：附着到已有运行，正常；
   - `replay`：已完成回放，正常。

### 5.3 LLM 429 / 503

- 日志 `llm retry`；网关已指数退避（最多 `LLM_MAX_RETRIES`）；
- 降低 `LLM_MAX_CONCURRENCY` 防止把上游打爆；
- 用户侧会收到 `event: error`，`code=UPSTREAM_UNAVAILABLE`（不泄露上游细节）。

### 5.4 订单超卖 / 重复扣库存

- 理论上不可能：扣减是条件 UPDATE，订单有唯一幂等键；
- 若收到重复订单：确认是否用了**不同的** `X-Idempotency-Key`（业务上视为两次下单）；
- 排查：`SELECT idempotency_key, count(*) FROM orders GROUP BY 1 HAVING count(*)>1;`

### 5.5 审批一直 pending

- 超过 `AGENT_APPROVAL_TTL_HOURS`（默认 24h）会被定时任务置 `expired`；
- 定时循环只在 `TASKS_ENABLED=true 且 TASKS_EAGER=false` 的 API 进程里启动；
- 也可以由 worker 执行 `chat.expire_approvals` 任务（需要外部调度器触发）。

### 5.6 任务积压

```bash
redis-cli XLEN xianxiaobao:tasks
redis-cli XINFO GROUPS xianxiaobao:tasks      # pending / consumers
```
- 扩 worker 副本；
- 检查死信流里的错误（多为上游 4xx 或参数错误，重试无意义——任务应校验参数）。

### 5.7 Redis 宕机

- 服务不会崩溃：幂等/限流/锁/流缓冲退化为进程内实现（**仅单副本正确**）；
- 多副本必须 `REDIS_REQUIRED=true`，让 readiness 失败、流量摘除；
- 恢复后需**滚动重启** API（adapter 在启动时选择），否则会一直用降级实现。

### 5.8 迁移失败 / 锁表

- PostgreSQL DDL 会在表上加锁；大表加列请用 `ADD COLUMN ... NULL` + 回填 + 约束三步；
- 迁移失败后 `alembic current` 会停在旧版本；修复脚本后重跑；
- 并发迁移（多个 Pod 同时跑）是禁止的——这就是 `migrate` 单独服务的原因。

### 5.9 发版时 SSE 被截断

- `terminationGracePeriodSeconds` 太短：Agent 一轮可能 30–60s；
- 本项目在 shutdown 时 drain 在跑的 Agent 任务（默认 10s 后取消），
  对应把 grace period 设为 ≥ 60s，并配置 `preStop sleep 10`。

---

## 6. 安全运维

- **轮换 SECRET_KEY**：所有已签发 token 立即失效（用户需重新登录）；建议提前公告；
- **密钥管理**：`SECRET_KEY`、`CHAT_API_KEY`、`ZHIPUAI_API_KEY`、飞书 secret 只进 Secret 管理器，
  不进 `.env` 仓库文件、不进镜像层；
- **依赖审计**：在 GitHub 打开 Dependabot / `pip-audit`（建议加入 CI）;
- **日志脱敏**：连接串已脱敏；不要在业务日志里打印 token/密码/地址全文；
- **上传**：容器内 `/app/uploads` 可写即可，禁止执行权限；生产建议对象存储 + CDN。

---

## 7. 容量与参数

| 参数 | 建议起点 | 说明 |
| --- | --- | --- |
| `DB_POOL_SIZE` | 10 × 副本数 < PG `max_connections` × 0.8 | 每副本独立池 |
| `LLM_MAX_CONCURRENCY` | 上游 RPM / 平均响应秒数 | 先小后大，避免 429 |
| `REDIS_MAX_CONNECTIONS` | 20 | 单进程 |
| `AGENT_STREAM_TTL_SECONDS` | 600 | 断线重连窗口 |
| `AGENT_THREAD_LOCK_TTL` | 30 | Watchdog 每 10s 续期 |
| `AGENT_MAX_STEPS` | 6 | 限制工具循环与费用 |
| `MAX_UPLOAD_BYTES` | 10 MiB | 同时检查 Ingress body-size |

---

## 8. 备份与恢复

```bash
# 备份
pg_dump -Fc "$DATABASE_URL" -f backup-$(date +%F).dump
# 恢复（先停 API 写入）
pg_restore -d "$DATABASE_URL" --clean --if-exists backup-2026-11-14.dump
alembic current          # 确认版本
# Redis 只存缓存/队列/锁：可清空，无需备份（正在跑的任务会丢失，前端可用 Last-Event-ID 重试）
```
