# FastAPI项目启动脚本
# 使用方法: .\start.ps1

Write-Host "=== 启动 FastAPI 开发服务器 ===" -ForegroundColor Cyan
Write-Host ""

# 检查虚拟环境
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "错误: 虚拟环境不存在，请先运行 .\setup.ps1" -ForegroundColor Red
    exit 1
}

# 检查PostgreSQL容器
Write-Host "检查PostgreSQL容器状态..." -ForegroundColor Yellow
$containerStatus = docker ps --filter "name=fastapi-postgres" --format "{{.Status}}" 2>$null

if (-not $containerStatus) {
    Write-Host "警告: PostgreSQL容器未运行" -ForegroundColor Yellow
    Write-Host "是否启动容器? (Y/N): " -ForegroundColor Yellow -NoNewline
    $response = Read-Host
    
    if ($response -eq 'Y' -or $response -eq 'y') {
        docker start fastapi-postgres
        Start-Sleep -Seconds 3
        Write-Host "✓ PostgreSQL容器已启动" -ForegroundColor Green
    } else {
        Write-Host "继续启动服务器(将使用SQLite)..." -ForegroundColor Yellow
    }
} else {
    Write-Host "✓ PostgreSQL容器运行中" -ForegroundColor Green
}

Write-Host ""
Write-Host "正在启动FastAPI服务器..." -ForegroundColor Cyan
Write-Host "访问地址:" -ForegroundColor White
Write-Host "  - API: http://localhost:8000" -ForegroundColor Gray
Write-Host "  - 文档: http://localhost:8000/docs" -ForegroundColor Gray
Write-Host "  - 健康检查: http://localhost:8000/health" -ForegroundColor Gray
Write-Host ""
Write-Host "按 Ctrl+C 停止服务器" -ForegroundColor Yellow
Write-Host ""

# 激活虚拟环境并启动服务器
& .\.venv\Scripts\Activate.ps1
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
