# FastAPI 项目恢复指南

## 📋 项目概览

这是一个完整的FastAPI项目，包含以下功能：
- ✅ 用户注册与登录 (JWT认证)
- ✅ 物品CRUD操作（带权限控制）  
- ✅ PostgreSQL数据库集成
- ✅ Alembic数据库迁移
- ✅ 完整的测试套件

## 🔧 环境配置

### 1. Python解释器配置

**虚拟环境路径**：
```
d:\PycharmProjects\fastapi-practice-jzp\.venv\Scripts\python.exe
```

**PyCharm配置步骤**：
1. 打开 `File` → `Settings` (Ctrl+Alt+S)
2. 进入 `Project: fastapi-practice-jzp` → `Python Interpreter`
3. 点击齿轮图标 → `Add Interpreter` → `Existing Environment`
4. 选择上述路径

### 2. 安装依赖

```powershell
# 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 安装所有依赖
pip install -r requirements.txt
```

### 3. 环境变量配置

检查 `.env` 文件是否存在：
```dotenv
ENVIRONMENT="development"
APP_NAME="我的生产级API"
DATABASE_URL="postgresql+psycopg://fastapi_user:fastapi_pass@localhost:5433/fastapi_db"

# JWT配置会从config.py获取默认值
```

## 🗄️ 数据库配置

### PostgreSQL Docker容器

**容器信息**：
- 容器名: `fastapi-postgres`
- 端口: `5433` (主机) → `5432` (容器)
- 用户: `fastapi_user`
- 密码: `fastapi_pass`
- 数据库: `fastapi_db`

**启动容器**：
```powershell
# 启动
docker start fastapi-postgres

# 检查状态
docker ps --filter "name=fastapi-postgres"

# 查看日志
docker logs fastapi-postgres
```

**如果容器不存在，创建新容器**：
```powershell
docker run -d `
  --name fastapi-postgres `
  -e POSTGRES_USER=fastapi_user `
  -e POSTGRES_PASSWORD=fastapi_pass `
  -e POSTGRES_DB=fastapi_db `
  -p 5433:5432 `
  postgres:15
```

### 数据库迁移

```powershell
# 生成迁移脚本
.\.venv\Scripts\alembic.exe revision --autogenerate -m "initial migration"

# 应用迁移
.\.venv\Scripts\alembic.exe upgrade head

# 查看当前版本
.\.venv\Scripts\alembic.exe current

# 查看历史
.\.venv\Scripts\alembic.exe history
```

## 🚀 运行项目

### 启动开发服务器

```powershell
# 方式1: 使用uvicorn直接运行
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 方式2: 使用Python模块方式
python -m uvicorn src.main:app --reload
```

访问：
- API文档: http://localhost:8000/docs
- 备用文档: http://localhost:8000/redoc
- 健康检查: http://localhost:8000/health

## 🧪 运行测试

```powershell
# 运行所有测试
pytest -v

# 运行特定测试文件
pytest tests/test_main.py -v

# 运行带覆盖率
pytest --cov=src --cov-report=html

# 只运行单元测试
pytest tests/test_unit/ -v
```

## 📁 项目结构

```
fastapi-practice-jzp/
├── src/
│   ├── __init__.py          # [新增] 包标记
│   ├── main.py              # 应用入口
│   ├── config.py            # 配置管理
│   ├── database.py          # [已修复] 数据库连接
│   ├── auth/                # 认证模块
│   │   ├── __init__.py
│   │   ├── router.py        # 登录接口
│   │   ├── schemas.py       # Token模型
│   │   ├── utils.py         # JWT工具
│   │   └── dependencies.py  # 认证依赖
│   ├── users/               # 用户模块
│   │   ├── __init__.py      # [新增]
│   │   ├── router.py        # 注册/查询接口
│   │   ├── schemas.py       # 用户模型
│   │   └── service.py       # 业务逻辑
│   └── posts/               # 物品模块
│       ├── __init__.py      # [新增]
│       ├── router.py        # CRUD接口
│       ├── schemas.py       # 物品模型
│       ├── models.py        # 数据库模型
│       ├── service.py       # 业务逻辑
│       ├── dependencies.py  # 依赖注入
│       └── utils.py         # 密码工具
├── health/
│   ├── __init__.py
│   ├── router.py            # 健康检查
│   ├── schemas.py
│   └── dependencies.py
├── tests/
│   ├── __init__.py          # [新增]
│   ├── conftest.py          # 测试配置
│   ├── test_main.py         # 主测试
│   ├── test_user.py         # 用户测试
│   └── test_unit/
│       └── test_utils.py
├── alembic/
│   ├── env.py
│   └── versions/
├── .env                     # 环境变量
├── .gitignore               # [已更新]
├── requirements.txt         # [新增] 依赖列表
├── alembic.ini              # Alembic配置
└── pytest.ini               # Pytest配置
```

## 🔍 已修复的问题

1. ✅ **database.py拼写错误**：修复了 `Bse` → `Base` 并合并重复定义
2. ✅ **缺少requirements.txt**：创建了完整的依赖列表
3. ✅ **缺少__init__.py**：为所有包添加了包标记文件
4. ✅ **不完整的.gitignore**：更新了完整的忽略规则

## 📝 API使用流程

### 1. 注册用户
```bash
POST http://localhost:8000/users/
Content-Type: application/json

{
  "username": "testuser",
  "email": "test@example.com",
  "password": "ValidPassword123",
  "age": 25,
  "phone": "1234567890"
}
```

### 2. 登录获取Token
```bash
POST http://localhost:8000/token
Content-Type: application/x-www-form-urlencoded

username=test@example.com&password=ValidPassword123
```

### 3. 创建物品（需要认证）
```bash
POST http://localhost:8000/items/
Authorization: Bearer <your_token>
Content-Type: application/json

{
  "name": "Test Item",
  "price": 99.99,
  "is_offer": false
}
```

### 4. 查询物品（无需认证）
```bash
GET http://localhost:8000/items/
```

### 5. 更新物品（需要认证+权限）
```bash
PUT http://localhost:8000/items/1
Authorization: Bearer <your_token>
Content-Type: application/json

{
  "price": 79.99
}
```

### 6. 删除物品（需要认证+权限）
```bash
DELETE http://localhost:8000/items/1
Authorization: Bearer <your_token>
```

## 🎯 下一步操作

1. **立即执行**：
   ```powershell
   # 安装依赖
   pip install -r requirements.txt
   
   # 启动数据库
   docker start fastapi-postgres
   
   # 运行迁移
   .\.venv\Scripts\alembic.exe upgrade head
   
   # 启动服务
   uvicorn src.main:app --reload
   ```

2. **验证配置**：
   ```powershell
   # 测试数据库连接
   python test_pg_connection.py
   
   # 运行测试套件
   pytest -v
   ```

3. **在PyCharm中配置**：
   - 设置Python解释器（见上文）
   - 检查是否识别了所有导入

## 🐛 常见问题

### IDE无法识别导入
**原因**：虚拟环境未激活或PyCharm未配置正确的解释器  
**解决**：按照"Python解释器配置"步骤重新配置

### 数据库连接失败
**原因**：PostgreSQL容器未启动  
**解决**：
```powershell
docker start fastapi-postgres
docker logs fastapi-postgres  # 检查日志
```

### Alembic无法生成迁移
**原因**：模型未正确导入到env.py  
**检查**：alembic/env.py中是否有 `from src.posts import models`

### 测试失败
**原因**：可能是依赖版本问题或数据库状态  
**解决**：
```powershell
pip install --upgrade -r requirements.txt
pytest -v --tb=short  # 查看详细错误
```

## 📚 参考文档

- FastAPI官方文档: https://fastapi.tiangolo.com/
- SQLAlchemy异步: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Alembic迁移: https://alembic.sqlalchemy.org/
- JWT认证: https://python-jose.readthedocs.io/
