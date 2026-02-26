# 1. 指定基础镜像：我们站在巨人的肩膀上，直接用官方装好 Python 3.11 的精简版 Linux 系统
FROM python:3.11-slim

# 2. 指定工作目录：进入集装箱后，我们把工作台设在 /app 目录下
WORKDIR /app

# 3. 复制依赖清单：把本地的 requirements.txt 抄一份到集装箱的当前目录 (.)
COPY requirements.txt .

# 4. 安装依赖：让集装箱里的系统照着清单安装包 (加 --no-cache-dir 可以减小集装箱体积)
RUN pip install --no-cache-dir -r requirements.txt

# 5. 复制项目代码：把本地文件夹里的所有东西，统统搬进集装箱的 /app 目录下
# (不用担心把垃圾文件搬进去，因为我们刚才写了 .dockerignore)
COPY . .

# 6. 声明端口：告诉集装箱，这个应用运行在 8000 端口
EXPOSE 8000

# 7. 启动命令：集装箱启动时，自动执行这行命令启动 FastAPI 
# 注意：这里 host 必须是 0.0.0.0，意思是允许集装箱外部访问它
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]