<div align="center">

# ✨ 🛍️ 我的全栈二手平台 (Second-Hand Marketplace) ✨

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/redis-%23DD0031.svg?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)

*一个功能强大、性能爆表的现代化 FastAPI 实战项目！ ヾ(≧▽≦*)o*

</div>

---

## 🌟 项目简介 (Features) 

欢迎来到这个超酷的全栈二手交易平台后端！ (❁´◡`❁) 本项目包含了企业级 Web 开发的各种进阶姿势，非常适合用来学习和作为脚手架使用~ 

- 🛡️ **安全第一 (JWT Auth)**：基于 OAuth2 密码流的 Token 身份认证，保护你的每一个 API！
- 👥 **用户系统 (User Management)**：安全可靠的密码哈希 (Bcrypt)，完善的注册与登录流。
- 📦 **物品管理 (CRUD)**：完整的二手商品发布、查询、修删，自带严格的主人权限控制。
- 🏷️ **智能标签 (Many-to-Many)**：高级的 SQLAlchemy 多对多关系，轻松给物品打上多个标签 `[数码, 二手, 九成新]`。
- ⚡ **毫秒级缓存 (Redis)**：引入 AIORedis，让高频接口（如标签列表）起飞，直接从内存秒回数据！ 🚀
- 🖼️ **异步处理 (Background Tasks)**：支持图片上传功能，并在后台默默为你处理耗时任务，一点都不卡顿哦~
- 🐳 **容器化部署 (Docker)**：配置了 `docker-compose.yml`，一键拉起 Web + Postgres + Redis，环境配置不再让人头秃 `\(￣︶￣*\))`

---

## 🚀 极速启动 (Quick Start)

我们要让代码跑起来！(๑•̀ㅂ•́)و✧ 

### 方法一：🐳 Docker 一键启动 (推荐!) 

本项目已配置好完整的 Docker 环境，只需要动动手指：

```bash
# 复制并重命名环境变量（如果有）
# cp .env.example .env

# 一键拉起所有服务 (FastAPI + PostgreSQL + Redis)
docker compose up -d --build

# 查看运行日志看看有没有报错~
docker compose logs -f fastapi_app
```
> 🎉 **TADA!** 现在你可以访问自动生成的接口文档啦：
> **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
> **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

### 方法二：💻 本地手动安装 (适合开发调试) 

```bash
# 1. 创建并激活虚拟环境 (๑•̀ㅂ•́)و✧
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1

# 2. 安装满汉全席 (依赖包)
pip install -r requirements.txt

# 3. 施展魔法：初始化数据库结构 ✨
alembic upgrade head

# 4. 启动服务器！起飞！ 🚀
uvicorn src.main:app --reload
```

---

## 🎮 核心功能演示 (Core Demos)

### 1️⃣ 🔑 注册与登录
- **`POST /users/`**：创建一个新账号，开启你的交易之旅~
- **`POST /token`**：输入账号密码，换取包含魔法力量的 Access Token！

### 2️⃣ 🏷️ 物品与标签的羁绊 (Many-to-Many)
在这里体验本项目最核心强大的功能哦：

**第一步：创造世界 (创建标签)**
```json
POST /items/tags/
{ "name": "💻 数码" }
{ "name": "🔄 二手" }
```

**第二步：上架宝贝 (创建带标签的物品)**
```json
POST /items/
{
  "name": "iPhone 15 Pro Max",
  "price": 6999.0,
  "tag_ids": [1, 2]  // <- 看这里！直接关联多个标签~ 
}
```

**第三步：吃瓜群众 (自动查询嵌套数据)**
```json
GET /items/
// 返回的结果自动包含了完整的标签信息哦！(*^▽^*)
{
  "name": "iPhone 15 Pro Max",
  "tags": [
    { "id": 1, "name": "💻 数码" },
    { "id": 2, "name": "🔄 二手" }
  ]
}
```

---

## 📂 魔法宝箱 (Project Structure)

```text
fastapi/
 ├── src/                  # ✨ 核心代码都在这里
 │   ├── main.py           # 🚀 应用的绝对入口
 │   ├── auth/             # 🛡️ 认证与守卫模块 (JWT验证)
 │   ├── users/            # 👤 用户的家
 │   └── posts/            # 📦 物品、标签与上传模块
 │       ├── models.py     # 🗄️ 数据库模型 (ORM & 多对多)
 │       ├── schemas.py    # 📄 数据校验护盾 (Pydantic)
 │       ├── service.py    # 🧠 大脑 (业务逻辑)
 │       └── router.py     # 🛣️ 交通枢纽 (路由定义)
 ├── alembic/              # ⏳ 穿梭时光的数据库迁移工具
 ├── tests/                # 🧪 科学家们的测试实验室
 ├── docker-compose.yml    # 🐳 集装箱编排图纸
 ├── Dockerfile            # 📦 镜像制造配方
 └── requirements.txt      # 📜 魔法卷轴清单
```

---

## 🤝 参与贡献 (Contributing)

发现 bug？有超棒的新点子？非常欢迎提交 Issue 和 Pull Request！(oﾟvﾟ)ノ
让我们一起把这个项目变得更可爱更强大吧！💪

---
<div align="center">

**Made with ❤️ and FastAPI &nbsp; | &nbsp; Happy Coding! (´▽`ʃ♡ƪ)**

</div>
