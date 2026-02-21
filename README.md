# FastAPI Practice Project

一个功能完整的FastAPI学习项目，包含用户认证、CRUD操作、数据库迁移等企业级功能。

## ✨ 功能特性

- 🔐 **JWT身份认证** - 基于Token的安全认证系统
- 👤 **用户管理** - 用户注册、登录、信息查询
- 📦 **物品管理** - 完整的CRUD操作，带权限控制
- 🗄️ **数据库支持** - PostgreSQL (生产) + SQLite (测试)
- 🔄 **数据库迁移** - Alembic自动迁移管理
- 🧪 **测试覆盖** - 完整的单元测试和集成测试
- 📚 **自动文档** - Swagger UI + ReDoc
- ✅ **健康检查** - 服务和数据库健康监控

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Docker (用于PostgreSQL)
- Git

### 一键安装

```powershell
# 克隆项目（如果需要）
git clone <repository-url>
cd fastapi-practice-jzp

# 运行设置脚本（自动完成所有配置）
.\setup.ps1

# 启动服务器
.\start.ps1
```

### 手动安装

```powershell
# 1. 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动PostgreSQL容器
docker run -d `
  --name fastapi-postgres `
  -e POSTGRES_USER=fastapi_user `
  -e POSTGRES_PASSWORD=fastapi_pass `
  -e POSTGRES_DB=fastapi_db `
  -p 5433:5432 `
  postgres:15

# 4. 运行数据库迁移
.\.venv\Scripts\alembic.exe upgrade head

# 5. 启动服务器
uvicorn src.main:app --reload
```

## 📖 API文档

启动服务器后访问：
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🔑 API使用示例

### 1. 注册用户

```bash
POST http://localhost:8000/users/
Content-Type: application/json

{
  "username": "john",
  "email": "john@example.com",
  "password": "SecurePass123",
  "age": 28,
  "phone": "1234567890"
}
```

### 2. 登录获取Token

```bash
POST http://localhost:8000/token
Content-Type: application/x-www-form-urlencoded

username=john@example.com&password=SecurePass123
```

响应：
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### 3. 创建物品（需要认证）

```bash
POST http://localhost:8000/items/
Authorization: Bearer <your_token>
Content-Type: application/json

{
  "name": "Laptop",
  "price": 1299.99,
  "is_offer": false
}
```

### 4. 查询物品列表

```bash
GET http://localhost:8000/items/
# 可选参数：
# ?skip=0&limit=10&is_offer_filter=true
```

### 5. 更新物品（需要认证+所有权）

```bash
PUT http://localhost:8000/items/1
Authorization: Bearer <your_token>
Content-Type: application/json

{
  "price": 999.99
}
```

### 6. 删除物品（需要认证+所有权）

```bash
DELETE http://localhost:8000/items/1
Authorization: Bearer <your_token>
```

## 🧪 运行测试

```powershell
# 运行所有测试
pytest -v

# 运行特定测试文件
pytest tests/test_main.py -v

# 查看测试覆盖率
pytest --cov=src --cov-report=html
```

## 📁 项目结构

```
fastapi-practice-jzp/
├── src/                      # 源代码目录
│   ├── main.py              # 应用入口
│   ├── config.py            # 配置管理
│   ├── database.py          # 数据库连接
│   ├── auth/                # 认证模块
│   │   ├── router.py        # 认证路由 (/token)
│   │   ├── schemas.py       # Token数据模型
│   │   ├── utils.py         # JWT工具函数
│   │   └── dependencies.py  # 认证依赖
│   ├── users/               # 用户模块
│   │   ├── router.py        # 用户路由 (/users)
│   │   ├── schemas.py       # 用户数据模型
│   │   └── service.py       # 用户业务逻辑
│   └── posts/               # 物品模块
│       ├── router.py        # 物品路由 (/items)
│       ├── schemas.py       # 物品数据模型
│       ├── models.py        # 数据库模型
│       ├── service.py       # 物品业务逻辑
│       ├── dependencies.py  # 依赖注入
│       └── utils.py         # 密码工具
├── health/                  # 健康检查模块
├── tests/                   # 测试目录
│   ├── conftest.py          # 测试配置和fixture
│   ├── test_main.py         # 主测试文件
│   ├── test_user.py         # 用户测试
│   └── test_unit/           # 单元测试
├── alembic/                 # 数据库迁移
│   ├── versions/            # 迁移脚本
│   └── env.py               # Alembic配置
├── .env                     # 环境变量
├── requirements.txt         # 项目依赖
├── alembic.ini              # Alembic配置
├── pytest.ini               # Pytest配置
├── setup.ps1                # 一键安装脚本
├── start.ps1                # 启动脚本
└── SETUP_GUIDE.md           # 详细设置指南
```

## 🔧 配置说明

### 环境变量 (.env)

```env
ENVIRONMENT="development"
APP_NAME="我的生产级API"
DATABASE_URL="postgresql+asyncpg://fastapi_user:fastapi_pass@localhost:5433/fastapi_db"
```

### 数据库配置

**PostgreSQL (生产环境)**：
```
Host: localhost
Port: 5433
User: fastapi_user
Password: fastapi_pass
Database: fastapi_db
```

**SQLite (测试环境)**：
```
DATABASE_URL="sqlite+aiosqlite:///./test.db"
```

## 🛠️ 开发工具

### 数据库管理

```powershell
# 生成迁移脚本
.\.venv\Scripts\alembic.exe revision --autogenerate -m "描述变更"

# 应用迁移
.\.venv\Scripts\alembic.exe upgrade head

# 回滚迁移
.\.venv\Scripts\alembic.exe downgrade -1

# 查看当前版本
.\.venv\Scripts\alembic.exe current

# 查看迁移历史
.\.venv\Scripts\alembic.exe history
```

### Docker容器管理

```powershell
# 启动容器
docker start fastapi-postgres

# 停止容器
docker stop fastapi-postgres

# 查看日志
docker logs -f fastapi-postgres

# 进入数据库
docker exec -it fastapi-postgres psql -U fastapi_user -d fastapi_db

# 删除容器
docker rm -f fastapi-postgres
```

## 📚 技术栈

- **Web框架**: FastAPI 0.109.0
- **ASGI服务器**: Uvicorn
- **ORM**: SQLAlchemy 2.0 (异步)
- **数据库**: PostgreSQL 15 / SQLite
- **迁移工具**: Alembic
- **认证**: JWT (python-jose)
- **密码哈希**: Passlib + bcrypt
- **测试框架**: Pytest + pytest-asyncio
- **HTTP客户端**: HTTPX
- **数据验证**: Pydantic

## 📝 开发规范

### 代码组织

- **router.py**: 处理HTTP请求，定义路由
- **schemas.py**: Pydantic模型，用于数据验证
- **models.py**: SQLAlchemy模型，定义数据库表结构
- **service.py**: 业务逻辑层
- **dependencies.py**: 依赖注入函数
- **utils.py**: 工具函数

### 命名约定

- 路由：小写+下划线 `get_user_info`
- 类名：大驼峰 `UserModel`, `UserCreate`
- 常量：大写+下划线 `DATABASE_URL`
- 私有函数：下划线前缀 `_internal_helper`

## 🐛 常见问题

### Q: IDE无法识别导入？
**A**: 确保已在PyCharm中配置虚拟环境解释器路径：
```
d:\PycharmProjects\fastapi-practice-jzp\.venv\Scripts\python.exe
```

### Q: 数据库连接失败？
**A**: 检查PostgreSQL容器是否运行:
```powershell
docker ps --filter "name=fastapi-postgres"
```

### Q: Alembic迁移失败？
**A**: 确保数据库容器运行，并检查alembic.ini中的连接字符串。

### Q: 测试失败？
**A**: 运行 `pip install --upgrade -r requirements.txt` 更新依赖。

## 📄 许可证

本项目仅用于学习目的。

## 👥 贡献

欢迎提交Issue和Pull Request！

## 📞 联系方式

如有问题，请[提交Issue](../../issues)。

---

**祝你编码愉快！** 🎉
