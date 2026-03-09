<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&height=250&section=header&text=二手交易平台%20Backend&fontSize=50&animation=fadeIn&fontAlignY=38&desc=基于%20FastAPI%20构建的现代化、全异步驱动智能交易社区&descAlignY=55&descAlign=62" />

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?style=for-the-badge&logo=python&logoColor=white) 
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi) 
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white) 
![pgvector](https://img.shields.io/badge/pgvector-Vector_DB-03599C?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2CA5E0?style=for-the-badge&logo=docker&logoColor=white)
![ZhipuAI](https://img.shields.io/badge/AI_Agent-GLM_4.5-blueviolet?style=for-the-badge&logo=openai&logoColor=white)

<br/>

> **✨ 欢迎来到这个充满魔法的代码仓库！这不仅仅是一个后端，它是为你打造的一体化高并发、AI 驱动的交易世界引擎！ ✨**

</div>

---

## ☄️ 核心特性 (Features)

<details open>
<summary><b>🔥 展开查看大厂级黑科技列表</b></summary>

- 🌌 **高维空间检索 (Vector RAG)**：抛弃落后的 `%LIKE%` 模糊搜索！引入 `pgvector` 向量数据库，调用 `embedding-2` 为商品注入 1024 维高维灵魂。在多维空间中计算余弦相似度 (Cosine Similarity)，实现真正的“懂你所想”语义级智能搜索。 
- 🛡️ **绝对防御力场 (Pessimistic Locking)**：纯正大厂级电商交易核心！引入数据库悲观锁 (`with_for_update`) 与严格的订单流转状态机。在极高并发的“秒杀”抢购中，完美实现 0 超卖、0 脏数据，捍卫每一笔交易的物理一致性！ 
- 📊 **全知之眼 (Dashboard Aggregation)**：利用 SQLAlchemy 的 `selectinload` 魔法消除 N+1 异步查询风暴。一个聚合接口打包“我的发布”、“我的订单”与时间线流水，极速驱动前端极其优雅的个人看板。
- 🤖 **AI 智能中枢 (Agent Hub)**：接入 `ZhipuAI (GLM-4.5-Flash)` 大语言模型。结合 RAG 意图拦截器，化身 24 小时私人幽默管家。
- 🕸️ **关系之网 (Many-to-Many)**：优雅的 SQLAlchemy M2M 拓扑结构，允许一个物品挂载无数张属性标签 `<二手><近全新><同城秒发>`。
- ⚡ **光速响应 (Redis Cache)**：集成高性能 AIORedis，对于热点数据接口（如精选标签查询）实现真·毫秒级缓存直出！🚀
- 🖼️ **异步无界 (Background Tasks)**：自带文件管理和后台异步图像处理系统，就算传了 10 个G的图片，主线程也绝不阻塞半秒。
- 🧱 **永不迷路 (Alembic Migration)**：全自动追踪模型定义的数据库迭代器，包括 `pgvector` 扩展的无缝激活与回滚。
- 🐳 **容器领域 (Docker Compose)**：全自动化部署，将繁杂的环境依赖全部打包入舱，真真正正的 "一键起飞"。
</details>

---

## 🚀 极光启动 (Quick Start)

我们要让代码飞起来！(๑•̀ㅂ•́)و✧ 

### 🌟 方式一：自动化一键启动 (最新推荐！)

我们为你准备了「后悔药」级别防呆脚本 `run.sh`，自动**杀死串库进程、自动映射补全环境、强制无缝拉起容器组！**

```bash
# 赋予魔法棒执行权限
chmod +x run.sh

# 见证奇迹的时刻
./run.sh
```

---

### 🐳 方式二：Docker 原教旨启动

只要你懂 Docker，三行代码征服世界：

```bash
# 构建并分离挂载所有微服务 (API + 慢库 Postgres(pgvector) + 快库 Redis)
docker compose up -d --build

# 召唤飞行日志
docker compose logs -f web
```

> 🎉 **部署成功后，你的开发者神器已就绪：**
> 👉 **酷炫接口测试仪 (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
> 👉 **纯净本文档 (ReDoc)**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 💻 本地骇客模式 (Local Dev Start)

如果你想亲自在终端抚摸代码脉络...

```bash
# 1. 呼唤封闭力场
python -m venv .venv
source .venv/bin/activate  # (Win: .\.venv\Scripts\Activate.ps1)

# 2. 吞噬星空 (安装依赖列表)
pip install -r requirements.txt

# 3. 造物主降临 (全量构建数据库表，包含 Vector 向量扩展)
alembic upgrade head

# 4. 点燃等离子引擎
uvicorn src.main:app --reload
```

---

## 🔮 交互演示大赏 (Magic Show)

### 🤖 降维打击：1024 维空间语义检索 (Vector RAG)

无需精准的关键字，只需在对话框输入：**"我想打黑神话悟空，有什么装备推荐？"**

```json
POST /ai/agent
{
  "messages": [
    {"role": "user", "content": "我想打黑神话悟空，有什么装备推荐？"}
  ]
}
```

**系统的“高维直觉”会这样运作：**

1. 将你的话送入 `embedding-2` 引擎，压缩为 1024 维浮点数矩阵。
2. 触发数据库底层的余弦距离 SQL 算法：`order_by(ItemModel.embedding.cosine_distance(query_vector)).limit(3)`。
3. 精准揪出毫不包含“黑神话”字样，但语义极度相关的【戴尔游戏本】和【索尼显示器】，并由 AI 幽默地推荐给你！

### ⚔️ 闪电突袭：防超卖秒杀交易

高并发下的抢购，我们拒绝排队，只用锁说话！

```json
POST /items/42/buy
Headers: { "Authorization": "Bearer <你的动态护盾 Token>" }
```

**底层并发防御机制：**
当你按下按钮的毫秒间，`with_for_update()` 悲观锁瞬间冻结数据库的该行记录。如果是你第一个到达，交易状态机丝滑流转至 `paid`；如果慢了一步，系统立刻回滚事务并返回 `400 手慢了，已被抢购一空！`。

---

## 🏗️ 建筑图纸 (Architecture)

```text
fastapi/
 ├── src/                  # ✨ 灵魂中枢
 │   ├── main.py           # 🚀 万物起源 (App 入口)
 │   ├── auth/             # 🛡️ 守夜人 (JWT 认证)
 │   ├── users/            # 👤 玩家大厅
 │   └── posts/            # 📦 核心集市 & AI 中控
 │       ├── models.py     # 🗄️ 骨骼 (ORM, M2M & Vector(1024) 结构)
 │       ├── schemas.py    # 📄 结界 (Pydantic 序列化瘦身验证)
 │       ├── service.py    # 🧠 大脑 (核心业务层)
 │       └── router.py     # 🛣️ 血管 (RAG 检索、悲观锁交易链路)
 ├── alembic/              # ⏳ 时空机器 (Alembic 升级图纸)
 ├── requirements.txt      # 📜 附魔符文卷轴
 └── docker-compose.yml    # 🐳 集装箱编排法阵 (含 pgvector)
```

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&height=100&section=footer" />

**Made with ❤️ and FastAPI &nbsp; | &nbsp; May the Force pattern be with you! (´▽`ʃ♡ƪ)**

</div>
