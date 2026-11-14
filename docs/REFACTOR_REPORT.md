# 重构报告（0.1 → 0.2.0）

> 输入材料：《FastAPI 工业级后端架构与落地建议》（16 页 PDF，2026-11-13）
> 对象：闲小宝二手交易平台（`fastapi-practice-jzp`）
> 规模：新增/改写 `src/app` 72 个模块、约 6.9k 行；测试 11 个文件、约 1.1k 行；文档 4 篇

---

## 1. 执行摘要

原项目是一个"功能能跑、但离工业级很远"的练手项目：932 行的 `posts/router.py` 里同时做参数校验、SQL、
业务编排和 SSE；`import` 阶段就加载 600MB 视觉模型；同步 SDK 阻塞事件循环；下单接口给不存在的字段赋值，
必然 500；收藏接口引用不存在的表；匿名可注册为管理员；JWT 用空密钥签名；测试文件名重复导致互相覆盖。

本轮重构没有引入任何新依赖（部署环境离线），而是**用 Python 标准能力把 PDF 的架构主张全部落地**：
模块化单体 + 严格分层 + 全链路异步 + 纯 ASGI 中间件 + lifespan 资源治理 + 领域异常 + 幂等/限流 +
可降级基础设施 + Redis Stream 任务队列与 SSE 缓冲 + HITL 审批 + 结构化日志/探针 + 质量门禁。

结果：90 个测试全绿；`alembic upgrade/downgrade` 双向通过（含 SQLite）；真实 uvicorn 冒烟通过；
文档化改造点与差距。

---

## 2. 问题诊断（改造前，带证据）

| # | 问题 | 证据 | 影响 |
| --- | --- | --- | --- |
| 1 | 上帝路由 | `src/posts/router.py` 932 行；`src/feishu/router.py` 410 行 | 不可维护、不可测试 |
| 2 | import 即加载 600MB 模型 | `posts/router.py` 顶部 `from .ai_vision import ...`，`ai_vision.py` 模块级 `from_pretrained` | 冷启动慢、测试变慢、无模型即启动失败 |
| 3 | 同步调用阻塞事件循环 | `service.ask_ai_agent` 用同步 `OpenAI` 客户端在 async 生成器里 `for chunk in response` | 单个流式对话阻塞整个 worker |
| 4 | 下单必然 500 | `router.buy_item` 写 `item.buyer_id`，`ItemModel` 无该字段 | 核心交易链路不可用 |
| 5 | 收藏必然 500 | `toggle_favorite` 用 `item.favourited_by`，模型未定义该关系，也无关联表 | 功能不可用 |
| 6 | 权限提升漏洞 | `POST /items/register` 允许匿名传 `role=admin` | 任何人可成为管理员 |
| 7 | JWT 空密钥 | `SECRET_KEY: str = ""` + `.env` 未设置 | token 可伪造 |
| 8 | 路径穿越 | `uploads/{file.filename}` 直接使用客户端文件名 | 可覆盖任意文件 |
| 9 | SQLite 行锁失效 | 下单用 `with_for_update(nowait=True)` | SQLite 下无并发保护，且 PG 下锁等待策略粗糙 |
| 10 | 中间件反模式 | `@app.middleware("http")`（BaseHTTPMiddleware） | SSE 吞吐下降、上下文易丢 |
| 11 | 健康检查混用 | 唯一 `/health` 同时查 DB | DB 抖动导致 K8s 重启健康 Pod |
| 12 | 测试自欺 | `test_create_and_update_item` 定义两次；`len(response.json()) == 2` 但对端返回 dict；flake8 `\|\| true` | 门禁形同虚设 |
| 13 | 无幂等/无限流 | 下单、注册、Webhook 均可被重放；飞书 `INCR` 与 `EXPIRE` 分两步 | 重复扣库存、限流漏 key |
| 14 | SSE 无工程化 | 无心跳、无 `Last-Event-ID`、无缓冲控制，路由持有全局 DB session | 断线重连丢消息、连接池耗尽 |
| 15 | 依赖不可复现 | `requirements.txt` 是含 CUDA/Jupyter 的 pip freeze；无 `uv.lock` | 镜像 5GB+，环境漂移 |

---

## 3. 改造措施（按主题）

### 3.1 架构与分层
- 新建 `src/app/{core,shared,modules,api}`，按域切分 `users / items / orders / knowledge / chat / feishu / auth`；
- 每域 `router → service → repository → models`，DTO 在 `schemas.py`；
- `container.py` 作为唯一组合根，进程级资源（DB/Redis/HTTP/LLM/Agent/任务/存储）都在此创建与关闭；
- `core` 不含业务、`service` 不 import FastAPI、`router` 单函数 < 20 行。

### 3.2 异步纯度
- LLM/Embedding/飞书/爬虫：`httpx.AsyncClient` + 信号量 + 显式超时 + 指数退避；
- 视觉推理与磁盘 IO：`asyncio.to_thread`，模型线程锁懒加载；
- DB：SQLAlchemy 2.0 async，`expire_on_commit=False`，显式 `selectinload`；
- SSE 路由不再注入 DB session，后台 worker 自开短会话。

### 3.3 稳定性与并发
- 原子扣库存：`UPDATE ... SET inventory = inventory - n WHERE inventory >= n`（PG/SQLite 一致）；
- 订单价格快照 + `idempotency_key` 唯一索引；
- 幂等两阶段（Redis/内存）+ 并发 409 + 不同 payload 409；
- 三层背压：会话锁（Watchdog 续期 + Lua 释放）、用户限流、上游信号量；
- 优雅停机：先停调度、drain Agent、再关 HTTP/Redis/DB。

### 3.4 SSE / Agent
- Redis Stream 事件缓冲 + `Last-Event-ID` 续传 + 15s 心跳 + `X-Accel-Buffering: no`；
- 幂等三态（STARTED/IN_PROGRESS/COMPLETED）+ 断线策略（`continue`/`abort`）；
- 有界工具循环（`AGENT_MAX_STEPS`）+ 工具 JSON Schema + 输出截断；
- HITL：审批表状态机、条件 UPDATE 抢占、幂等执行、僵尸审批定时清理。

### 3.5 工程化
- `pyproject.toml`（ruff/mypy/coverage/hatch）、`requirements{,-ai,-dev}.txt` 分层；
- `Dockerfile` 多阶段 + 非 root + HEALTHCHECK + 可迁移不在 CMD；compose 增加 `migrate` 与 `worker`；
- CI：ruff → 测试覆盖率 → 迁移上/下 → 镜像推送；`pre-commit`；`Makefile`；
- 4 篇文档：README / ARCHITECTURE / MIGRATION / RUNBOOK（+ 本报告）。

---

## 4. 验证记录（本机实测）

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 单元 + 集成测试 | `pytest tests -q` | **90 passed**（约 15s；SQLite 内存库、无 Redis、无外部网络） |
| 全量语法 | `ast.parse` 全部 `src/**.py` + `tests/**.py` | 通过 |
| 应用导入 | `import src.main, src.worker, src.make_admin` | 通过 |
| 迁移升级 | `alembic upgrade head`（SQLite） | 通过，`agent_approvals/favourites` 与新增列齐全 |
| 迁移回滚 | `alembic downgrade base` | 通过，干净回退 |
| 真实服务冒烟 | `uvicorn src.main:app`（SQLite + 无 Redis） | `/health/live` 200、`/health/ready` 200、注册/登录/建商品/列表 全部正常 |
| SSE 冒烟 | `POST /items/ai/agent/stream` | 200，返回 `event: error`（无有效 LLM key），SSE 头与帧格式正确 |
| 配置一致性 | `.env.example` vs `Settings.model_fields` | 无未知/缺失键 |
| YAML/TOML | `yaml.safe_load` / `tomllib` | 全部通过 |

**未能在本机验证**（如实说明）：
- `ruff` / `mypy`：环境离线无法安装（CI 配置已就绪，mypy 为告警项）；
- `docker build` / `docker compose up`：无网络拉取基础镜像；
- 覆盖率百分比：缺 `pytest-cov`，CI 门禁暂设 60%；
- 真实 LLM/飞书/Playwright 端到端：需要密钥与浏览器（代码路径有降级与错误处理，且 SSE 已实测错误帧）。

---

## 5. 量化对比

| 指标 | 改造前 | 改造后 |
| --- | --- | --- |
| 最大单文件行数 | 932（posts/router.py） | ~374（items/router.py，且只做 HTTP 编排） |
| 导入应用耗时 | 受 600MB 模型下载/加载支配 | 毫秒级（模型懒加载） |
| 自动化测试 | 名义存在、实际失效 | 90 个，覆盖核心链路与并发/幂等/审批 |
| 交易链路 | 必然 500 | 可下单、可重复请求重放、防超卖 |
| 收藏功能 | 必然 500 | 可用（新增关联表） |
| 权限提升 | 匿名可注册 admin | 默认禁止，管理员 API 才能改角色 |
| 幂等 | 无 | 写接口 + SSE + 工具调用全部可重试 |
| 部署 | 单容器 + Celery，迁移靠脚本 | 迁移 Job + API/worker 分离 + 探针 + 优雅停机 |

---

## 6. 未完成与风险（面试时主动说）

1. `uv.lock` 未生成（离线）；`mypy` 未清零；覆盖率未测量——均为"流程/工具有了，数据还没跑"。
2. HITL 用业务库审批表代替 LangGraph checkpointer：语义等价但**没有**多步图快照回溯；
   未来接入 LangGraph 时保留审批表作为事实来源。
3. 无 Redis 时幂等/限流/锁退化为进程内，多副本场景必须 Redis（`REDIS_REQUIRED=true`）。
4. `users.email` 无数据库唯一约束（历史数据可能重复），由 service 保证。
5. 飞书只校验 verification token，未做 encrypt-key 签名校验；生产需补。
6. 未做压测与混沌演练；`LLM_MAX_CONCURRENCY` 等参数需要按真实上游 QPS 调。

---

## 7. 面试讲述模板（STAR）

**Situation**：项目是一个二手交易 + AI 导购的 FastAPI 应用，功能齐但工程化差：单文件近千行、
import 即加载大模型、同步 SDK 阻塞事件循环、下单/收藏接口一调用就 500、JWT 空密钥、测试互相覆盖。

**Task**：在不推倒业务的前提下，按工业级标准重构为可维护、可观测、可部署的架构，并保证核心交易链路正确。

**Action**：
1. 先做**分层与依赖收敛**：core/shared/modules，router 只做 HTTP，service 不依赖框架，repository 只做 SQL；
2. 再解决**正确性**：原子扣库存、订单价格快照与幂等唯一键、领域异常统一映射、补齐收藏关联表；
3. 再做**异步纯度**：httpx 网关 + 信号量 + 超时/退避，视觉与磁盘 IO 下放线程，SSE 路由不持有 DB session；
4. 然后做**协作型能力**：Redis Stream 事件缓冲 + Last-Event-ID 续传 + 会话锁 + 三层背压 +
   人工审批状态机（金额超阈值挂起、幂等恢复、超时清理）；
5. 最后做**工程闭环**：lifespan 资源治理、纯 ASGI 中间件、JSON 日志 + trace_id、双探针、
   alembic 双向迁移、Docker/compose/CI/pre-commit、90 个测试。

**Result**：90 测试全绿、迁移可上可下、真实 uvicorn 冒烟通过；核心链路从"必然 500"变为"可下单、可重试、
防超卖"；新增能力（幂等、限流、SSE 续传、HITL）都有对应测试与文档。

**可能的追问**：
- *为什么不用 Celery？* 见 ARCHITECTURE §9 ADR-1；
- *为什么不用 LangGraph checkpointer？* 见 ARCHITECTURE §6.4；
- *并发下如何防超卖？* 条件 UPDATE + 唯一幂等键，见 §6.1；
- *Redis 挂了怎么办？* 降级 + `REDIS_REQUIRED` 语义，见 RUNBOOK §5.7；
- *如何证明重构有效？* 测试/迁移/冒烟记录 + 前后对比表（本报告 §4/§5）。

---

## 8. 下一步 30/60/90

- **30 天**：CI 上跑通 ruff/mypy/覆盖率并清掉告警；`uv lock`；补 `pip-audit`/Dependabot；
- **60 天**：接入 OpenTelemetry + Prometheus/Grafana 面板与分级告警；压测出 P95/P99；
  飞书签名校验；`email` 唯一索引（先清洗数据）；
- **90 天**：多副本故障演练（Redis/DB/LLM 故障注入）；按需接入 LangGraph/Temporal 处理复杂长流程；
  把"分层规则""SSE 契约""错误码"做成自动化契约测试。
