# 南汐 QQ 机器人 - 一键关闭脚本
# 停止顺序：AstrBot(Python 进程) → SnowLuma(Docker 容器)
#
# ⚠️ 安全约定：AstrBot **只按端口（6185 / 3002）精确停止**，
#    绝不"杀掉所有 python.exe" —— 你机器上可能还跑着别的东西。
#
# 用法：
#   双击 启动\一键关闭.bat          （正常关闭）
#   powershell -File stop_all.ps1 -DryRun   （只看会停什么，不动手）

param(
    [switch]$DryRun
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==============================" -ForegroundColor Cyan
Write-Host "   南汐 QQ 机器人 · 一键关闭" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "（DryRun 模式：只显示会做什么，不会真的停任何东西）" -ForegroundColor Yellow
}

# ---- 1) AstrBot：按端口 6185 / 3002 找 PID ----
Write-Host ""
Write-Host "[1/2] 停止 AstrBot ..." -ForegroundColor Yellow
$targets = @()
foreach ($port in 6185, 3002) {
    $pids = netstat -ano | Select-String "LISTENING" | Select-String ":$port\s" |
        ForEach-Object { ($_.Line -split '\s+')[-1] } | Sort-Object -Unique
    foreach ($p in $pids) {
        if ($p -match '^\d+$' -and $p -ne '0') {
            $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
            if ($proc) {
                $targets += [pscustomobject]@{ Pid = $p; Name = $proc.ProcessName; Port = $port }
            }
        }
    }
}

if ($targets.Count -eq 0) {
    Write-Host "  [..] 没找到在运行的 AstrBot（可能已经关了）" -ForegroundColor Gray
} else {
    foreach ($t in ($targets | Sort-Object Pid -Unique)) {
        if ($DryRun) {
            Write-Host "  [DryRun] 将停止 PID $($t.Pid)（$($t.Name)，端口 $($t.Port)）" -ForegroundColor Yellow
        } else {
            taskkill /F /PID $t.Pid 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [OK] 已停止 PID $($t.Pid)（$($t.Name)，端口 $($t.Port)）" -ForegroundColor Green
            } else {
                Write-Host "  [!] 停止 PID $($t.Pid) 失败（可能需要管理员权限）" -ForegroundColor Yellow
            }
        }
    }
}

# ---- 2) SnowLuma 容器 ----
Write-Host ""
Write-Host "[2/2] 停止 SnowLuma 容器 ..." -ForegroundColor Yellow
$snow = (docker ps --filter "name=snowluma" --format "{{.Names}}" 2>$null)
if ($snow -match "snowluma") {
    if ($DryRun) {
        Write-Host "  [DryRun] 将执行 docker stop snowluma" -ForegroundColor Yellow
    } else {
        docker stop snowluma 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] SnowLuma 已停止（QQ 会随之离线）" -ForegroundColor Green
        } else {
            Write-Host "  [!] docker stop 失败，可手动执行：docker stop snowluma" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  [..] SnowLuma 没在运行（或 Docker 引擎没起）" -ForegroundColor Gray
}

# ---- 收尾说明 ----
if (-not $DryRun) {
    Write-Host ""
    Write-Host "----- 说明 -----" -ForegroundColor Cyan
    Write-Host "  · AstrBot 与 SnowLuma 已停，下次双击 启动\一键启动.bat 即可恢复。"
    Write-Host "  · 如果重启后 QQ 提示要重新登录：打开 http://127.0.0.1:6081 扫码即可。"
    Write-Host "  · Docker Desktop 本身没有退出（留着下次启动更快）——"
    Write-Host "    要彻底退出，右键任务栏托盘里的 Docker 图标 → Quit Docker Desktop。"
    Write-Host "  · 只按端口精确停了 AstrBot，没有动你机器上其它 python 程序。" -ForegroundColor DarkGray
    Write-Host ""
}
