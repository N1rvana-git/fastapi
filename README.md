# FastAPI practice

一个基于 FastAPI 的异步应用，包含用户、帖子、飞书集成、AI 视觉分析和向量检索功能。

## 项目结构

```text
.
├── src/                 # 应用源码
│   ├── auth/            # 认证相关逻辑
│   ├── feishu/          # 飞书集成
│   ├── posts/           # 帖子、图片和 AI 功能
│   └── users/           # 用户功能
├── alembic/             # 数据库迁移
├── tests/               # 自动化测试
├── .github/workflows/   # CI 配置
├── Dockerfile           # 容器构建
├── docker-compose.yml   # 本地依赖服务
└── requirements.txt     # Python 依赖
```

## 本地开发

1. 复制 `.env.example` 为 `.env` 并填写本地配置。
2. 创建虚拟环境并安装依赖：

   ```bash
   python -m venv .venv
   python -m pip install -r requirements.txt
   ```

3. 执行数据库迁移：

   ```bash
   alembic upgrade head
   ```

4. 启动开发服务器：

   ```bash
   uvicorn src.main:app --reload
   ```

5. 运行测试：

   ```bash
   pytest
   ```

## 数据库变更

所有表结构和 pgvector 维度变更都必须通过 Alembic migration 提交。不要在仓库中提交数据库备份、运行日志、虚拟环境、二进制文件或一次性调试脚本。

## 敏感文件

本地环境变量、上传文件和数据库文件默认不会被 Git 跟踪。提交前请检查：

```bash
git status --short
git diff --cached --stat
```
