# FastAPI项目快速启动脚本
# 使用方法: .\setup.ps1

Write-Host "=== FastAPI 项目环境设置 ===" -ForegroundColor Cyan
Write-Host ""

# 1. 检查虚拟环境
Write-Host "[1/5] 检查虚拟环境..." -ForegroundColor Yellow
if (Test-Path ".\.venv\Scripts\python.exe") {
    Write-Host "  ✓ 虚拟环境已存在" -ForegroundColor Green
} else {
    Write-Host "  ✗ 虚拟环境不存在，正在创建..." -ForegroundColor Red
    python -m venv .venv
    Write-Host "  ✓ 虚拟环境创建完成" -ForegroundColor Green
}

# 2. 激活虚拟环境并安装依赖
Write-Host "[2/5] 安装项目依赖..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
Write-Host "  ✓ 依赖安装完成" -ForegroundColor Green

# 3. 检查PostgreSQL容器
Write-Host "[3/5] 检查PostgreSQL容器..." -ForegroundColor Yellow
$containerStatus = docker ps --filter "name=fastapi-postgres" --format "{{.Status}}" 2>$null

if ($containerStatus) {
    Write-Host "  ✓ PostgreSQL容器正在运行: $containerStatus" -ForegroundColor Green
} else {
    $containerExists = docker ps -a --filter "name=fastapi-postgres" --format "{{.Names}}" 2>$null
    
    if ($containerExists) {
        Write-Host "  ! 容器存在但未运行，正在启动..." -ForegroundColor Yellow
        docker start fastapi-postgres
        Start-Sleep -Seconds 3
        Write-Host "  ✓ PostgreSQL容器已启动" -ForegroundColor Green
    } else {
        Write-Host "  ! 容器不存在，正在创建..." -ForegroundColor Yellow
        docker run -d `
            --name fastapi-postgres `
            -e POSTGRES_USER=fastapi_user `
            -e POSTGRES_PASSWORD=fastapi_pass `
            -e POSTGRES_DB=fastapi_db `
            -p 5433:5432 `
            postgres:15
        Start-Sleep -Seconds 5
        Write-Host "  ✓ PostgreSQL容器创建并启动成功" -ForegroundColor Green
    }
}

# 4. 运行数据库迁移
Write-Host "[4/5] 运行数据库迁移..." -ForegroundColor Yellow
Write-Host "  正在检查迁移状态..."
.\.venv\Scripts\alembic.exe current

Write-Host "  正在应用迁移..."
.\.venv\Scripts\alembic.exe upgrade head
Write-Host "  ✓ 数据库迁移完成" -ForegroundColor Green

# 5. 测试连接
Write-Host "[5/5] 测试数据库连接..." -ForegroundColor Yellow
if (Test-Path ".\test_pg_connection.py") {
    python test_pg_connection.py
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ 数据库连接测试通过" -ForegroundColor Green
    } else {
        Write-Host "  ✗ 数据库连接测试失败" -ForegroundColor Red
    }
} else {
    Write-Host "  ! test_pg_connection.py 不存在，跳过测试" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 设置完成！ ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步操作：" -ForegroundColor White
Write-Host "  1. 启动开发服务器:" -ForegroundColor Gray
Write-Host "     uvicorn src.main:app --reload" -ForegroundColor White
Write-Host ""
Write-Host "  2. 运行测试:" -ForegroundColor Gray
Write-Host "     pytest -v" -ForegroundColor White
Write-Host ""
Write-Host "  3. 访问API文档:" -ForegroundColor Gray
Write-Host "     http://localhost:8000/docs" -ForegroundColor White
Write-Host ""
