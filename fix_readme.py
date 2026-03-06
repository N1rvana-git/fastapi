import re

with open("README.md", "r", encoding="utf-8") as f:
    text = f.read()

features_insert = """- 🤖 **AI 智能管家 (ZhipuAI / Agent)**：搭载了最新的大语言模型，理解用户意图并自动使用工具(Function Calling)搜索平台二手商品和求购信息。
- 🐳 **容器化部署 (Docker)**：配置了"""

text = text.replace("- 🐳 **容器化部署 (Docker)**：配置了", features_insert)

quickstart_replace_old = """我们要让代码跑起来！(๑•̀ㅂ•́)و✧ 

### 方法一：🐳 Docker 一键启动 (推荐!) 

本项目已配置好完整的 Docker 环境，只需要动动手指：

```bash
# 复制并重命名环境变量（如果有）
# cp .env.example .env

# 一键拉起所有服务 (FastAPI + PostgreSQL + Redis)
docker compose up -d --build

# 查看运行日志看看有没有报错~
docker compose logs -f fastapi_app
```"""

quickstart_replace_new = """我们要让代码跑起来！(๑•̀ㅂ•́)و✧ 

### 方法一：🔥 自动化一键启动 (最新推荐) 

告别各种繁琐的命令，本项目专门编写了极速启动脚本 `run.sh`。它能自动帮你**清理冲突端口、映射虚拟环境、强制构建 Docker 容器**。

只需要执行：
```bash
chmod +x run.sh
./run.sh
```

### 方法二：🐳 Docker 手动启动

```bash
# 一键拉起所有服务 (FastAPI + PostgreSQL + Redis)
docker compose up -d --build

# 查看运行日志看看有没有报错~
docker compose logs -f web
```"""

text = text.replace(quickstart_replace_old, quickstart_replace_new)

with open("README.md", "w", encoding="utf-8") as f:
    f.write(text)
