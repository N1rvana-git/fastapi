# FastAPI Practice Project

一个功能完整的FastAPI学习项目，包含用户认证、CRUD操作、**多对多关系(Tags)**、数据库迁移等企业级功能。

##  功能特性

-  **JWT身份认证** - 基于Token的安全认证系统
-  **用户管理** - 用户注册、登录、信息查询
-  **物品管理** - 完整的CRUD操作，带权限控制
-  **标签系统** - **[新增]** 物品与标签的多对多关系 (Many-to-Many)
-  **数据库支持** - 默认使用 SQLite (无需配置)，可切换 PostgreSQL
-  **数据库迁移** - Alembic自动迁移管理
-  **测试覆盖** - 完整的单元测试和集成测试
-  **自动文档** - Swagger UI + ReDoc

##  快速开始

### 环境要求

- Python 3.10+
- Git

### 极速安装 (Windows)

无需 Docker，直接运行：

```powershell
# 1. 克隆项目
git clone https://github.com/N1rvana-git/fastapi.git
cd fastapi

# 2. 运行一键安装脚本 (安装依赖 + 初始化数据库)
.\setup.ps1

# 3. 启动服务器
.\start.ps1
```

> **注意**: 如果脚本执行受限，请先运行 `Set-ExecutionPolicy RemoteSigned -Scope Process`

### 手动安装 (跨平台)

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows使用: .\.venv\Scripts\Activate.ps1

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库 (自动创建 test.db)
alembic upgrade head

# 4. 启动服务器
uvicorn src.main:app --reload
```

##  API文档

启动服务器后访问：
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

##  核心功能演示

### 1. 注册与登录
- **POST** `/users/` - 注册新用户
- **POST** `/token` - 获取 Access Token

### 2. 物品与标签 (Many-to-Many)
这是本项目最核心的进阶功能演示：

#### 第一步：创建标签
```bash
POST /items/tags/
{ "name": "数码" }  # 假设返回 ID=1
{ "name": "二手" }  # 假设返回 ID=2
```

#### 第二步：创建带标签的物品
```bash
POST /items/
{
  "name": "iPhone 15",
  "price": 4999.0,
  "tag_ids": [1, 2]  # <--- 直接关联多个标签ID
}
```

#### 第三步：自动查询
查询物品列表时，API 会自动返回包含完整标签信息的嵌套 JSON：
```json
{
  "name": "iPhone 15",
  "tags": [
    { "id": 1, "name": "数码" },
    { "id": 2, "name": "二手" }
  ]
}
```

##  项目结构

```
fastapi/
 src/
    main.py              # 应用入口
    auth/                # 认证模块 (JWT)
    users/               # 用户模块
    posts/               # 物品与标签模块
        models.py        # 数据库模型 (含 Many-to-Many 定义)
        schemas.py       # Pydantic模型 (含嵌套序列化)
        service.py       # 业务逻辑
        router.py        # 路由定义
 alembic/                 # 数据库迁移脚本
 tests/                   # 测试用例
 .env.example             # 环境变量示例
 requirements.txt         # 项目依赖
 setup.ps1                # 自动安装脚本
 start.ps1                # 启动脚本
```

##  数据库配置

本项目默认使用 **SQLite**，开箱即用。
数据库文件会自动生成为项目根目录下的 `test.db`。

如需切换为 **PostgreSQL**，请修改 `.env` 文件：
```properties
# DATABASE_URL="sqlite+aiosqlite:///./test.db"
DATABASE_URL="postgresql+asyncpg://user:pass@localhost/dbname"
```

##  贡献

欢迎提交 Issue 和 Pull Request！

---
**Happy Coding!** 
