<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&height=250&section=header&text=二手交易平台%20Backend&fontSize=50&animation=fadeIn&fontAlignY=38&desc=基于%20FastAPI%20构建的现代化、全异步驱动智能交易社区&descAlignY=55&descAlign=62" />

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?style=for-the-badge&logo=python&logoColor=white) 
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi) 
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white) 
![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2CA5E0?style=for-the-badge&logo=docker&logoColor=white)
![ZhipuAI](https://img.shields.io/badge/AI_Agent-GLM_4.5-blueviolet?style=for-the-badge&logo=openai&logoColor=white)

<br/>

> **✨ 欢迎来到这个充满魔法的代码仓库！这不仅仅是一个后端，它是为你打造的一体化交易世界引擎！ ✨**

</div>

---

## ☄️ 核心特性 (Features)

<details open>
<summary><b>🔥 展开查看黑科技列表</b></summary>

- 🛡️ **坚如磐石 (JWT Auth)**：基于 OAuth2 密码流的动态 Token 护盾，为你的每一个 API 请求保驾护航。
- 🤖 **AI 智能中枢 (Agent Hub)**：接入 `ZhipuAI (GLM-4.5-Flash)`，带有强悍的函数调用能力（Function Calling），化身你的 24 小时私人交易管家，无论是买货还是卖货，一句话全搞定！
- 📦 **全能仓储 (CRUDx)**：从简单的发布、浏览，到精细的主人级权限控制，一切皆可通过 RESTful 标准轻松操作。
- 🕸️ **关系之网 (Many-to-Many)**：优雅的 SQLAlchemy M2M 拓扑结构，允许一个物品挂载无数张属性标签 `<二手><近全新><同城秒发>`。
- ⚡ **光速响应 (Redis Cache)**：集成高性能 AIORedis，对于热点数据接口（如精选标签查询）实现真·毫秒级缓存直出！🚀
- 🖼️ **异步无界 (Background Tasks)**：自带文件管理和后台异步图像处理系统，就算传了 10 个G，主线程也绝不阻塞半秒。
- 🧱 **永不迷路 (Alembic Migration)**：全自动追踪模型定义的数据库迭代器，时光倒流和未来构建无缝顺滑。
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
# 构建并分离挂载所有微服务 (API + 慢库 Postgres + 快库 Redis)
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

# 3. 造物主降临 (全量构建数据库表)
alembic upgrade head

# 4. 点燃等离子引擎
uvicorn src.main:app --reload
```

---

## 🔮 交互演示大赏 (Magic Show)

### 🤖 AI 智能交易助理 (Agent In Action)

无需繁琐表单，只需在对话框输入：**"我是一名学生，快帮我搜一下平台上有没有好心人在卖毕业设计的！"**

```json
POST /items/ai/agent
{
  "messages": [
    {"role": "user", "content": "有没有卖毕业设计的呀？"}
  ]
}
```
**系统将会自主推断：**
1. 分析语义："搜索出售 / 毕业设计"。
2. 内部隐式触发 `search_items` 钩子并在 Postgres 大海捞针。
3. 给你呈现出所有匹配列表页，甚至帮你砍价！

### 🏷️ 万物互联的多对多标签

**第一步：定义宇宙法则**
```json
POST /items/tags/
{ "name": "💻 万能数码" }
```

**第二步：祭出法宝**
```json
POST /items/
{
  "name": "战损版 MacBook Pro",
  "price": 99.0,
  "tag_ids": [1]  // <- 就是这么简单粗暴的关联！
}
```

---

## 🏗️ 建筑图纸 (Architecture)

```text
fastapi/
 ├── src/                  # ✨ 灵魂中枢
 │   ├── main.py           # 🚀 万物起源 (App 入口)
 │   ├── auth/             # 🛡️ 守夜人 (JWT 认证)
 │   ├── users/            # 👤 玩家大厅
 │   └── posts/            # 📦 交易集市 & AI 中控
 │       ├── models.py     # 🗄️ 骨骼 (数据库 ORM & M2M 模型)
 │       ├── schemas.py    # 📄 结界 (Pydantic 数据验证)
 │       ├── service.py    # 🧠 大脑 (核心增删改查)
 │       └── router.py     # 🛣️ 血管 (星际路由 & 智能 Agent)
 ├── alembic/              # ⏳ 时空机器 (数据库迁移记录)
 ├── requirements.txt      # 📜 附魔符文卷轴
 └── docker-compose.yml    # 🐳 集装箱编排法阵
```

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&height=100&section=footer" />

**Made with ❤️ and FastAPI &nbsp; | &nbsp; May the Force pattern be with you! (´▽`ʃ♡ƪ)**

</div>
