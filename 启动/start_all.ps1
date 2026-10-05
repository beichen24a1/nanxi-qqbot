# 南汐 QQ 机器人 - 一键启动脚本
# 启动顺序：Docker Desktop(引擎) → SnowLuma(容器) → AstrBot(Python)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==============================" -ForegroundColor Cyan
Write-Host "   南汐 QQ 机器人 · 一键启动" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan

# ---- 并发保护：重复双击会让两个 AstrBot 抢 3002，后启动的那个 OneBot 绑不上端口 ----
# 症状是「AstrBot 看着活着（6185 能开），但 QQ 通知发不出、机器人不回话」（2026-09-25 踩过）。
$lockDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\logs"))
New-Item -ItemType Directory -Force -Path $lockDir | Out-Null
$lockFile = Join-Path $lockDir "start.lock"
if (Test-Path -LiteralPath $lockFile) {
    $lockAge = (Get-Date) - (Get-Item -LiteralPath $lockFile).LastWriteTime
    if ($lockAge.TotalMinutes -lt 5) {
        Write-Host ""
        Write-Host "[!] 已经有一个启动流程在跑了（锁文件 $lockFile，$([int]$lockAge.TotalSeconds) 秒前创建）。" -ForegroundColor Yellow
        Write-Host "    本窗口不再重复启动，避免两个 AstrBot 抢端口。" -ForegroundColor Yellow
        Write-Host "    若确认没有别的窗口在跑，删除该锁文件后重试即可。" -ForegroundColor Yellow
        exit 1
    }
}
Set-Content -LiteralPath $lockFile -Value (Get-Date -Format o) -Encoding UTF8

# ---- 0) 确保 Docker Desktop(引擎) 已启动 ----
Write-Host ""
Write-Host "[0/3] 检查 Docker Desktop ..." -ForegroundColor Yellow
$dockerExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$engineReady = $false
if (Get-Process -Name "Docker Desktop","com.docker.backend" -ErrorAction SilentlyContinue) {
    Write-Host "  [..] Docker Desktop 进程已存在，等待引擎..."
} else {
    Write-Host "  [..] 启动 Docker Desktop ..."
    if (Test-Path $dockerExe) { Start-Process -FilePath $dockerExe } else { Write-Host "  [!] 未找到 Docker Desktop，跳过" }
}
for ($i=0; $i -lt 30; $i++) {
    docker info *>$null
    if ($LASTEXITCODE -eq 0) { $engineReady = $true; break }
    Start-Sleep -Seconds 3
}
if ($engineReady) { Write-Host "  [OK] Docker 引擎就绪" -ForegroundColor Green }
else { Write-Host "  [!] Docker 引擎未就绪（Docker Desktop 可能还在启动）" -ForegroundColor Yellow }

# ---- 1) SnowLuma 容器 ----
Write-Host ""
Write-Host "[1/3] 检查 SnowLuma ..." -ForegroundColor Yellow
$snow = (docker ps --filter "name=snowluma" --format "{{.Names}}" 2>$null)
if ($snow -match "snowluma") {
    Write-Host "  [OK] SnowLuma 已在运行" -ForegroundColor Green
} else {
    Write-Host "  [..] 启动 SnowLuma 容器 ..."
    docker start snowluma 2>$null | Out-Null
    Write-Host "  [OK] SnowLuma 已启动（首次会自动拉起 QQ）" -ForegroundColor Green
}

# ---- 2) AstrBot 进程 ----
Write-Host ""
Write-Host "[2/3] 检查 AstrBot ..." -ForegroundColor Yellow
$astr6185 = (Test-NetConnection -ComputerName 127.0.0.1 -Port 6185 -WarningAction SilentlyContinue).TcpTestSucceeded
$astr3002 = (Test-NetConnection -ComputerName 127.0.0.1 -Port 3002 -WarningAction SilentlyContinue).TcpTestSucceeded

if ($astr6185 -and $astr3002) {
    Write-Host "  [OK] AstrBot 已在运行、OneBot 已就绪 (http://localhost:6185)" -ForegroundColor Green
} else {
    if ($astr6185 -and -not $astr3002) {
        # 半死状态：6185 在、3002 没绑上 ⇒ OneBot 适配器启动失败（WinError 10013：端口被上一个
        # 实例占着）。此时 AstrBot 表面正常，但所有主动发送都会抛 ApiNotAvailable。
        # 处理：停掉这个半死实例，重新起一个干净的。
        Write-Host "  [!] AstrBot 处于半死状态（6185 在、3002 未监听 = OneBot 没绑上），先停掉它 ..." -ForegroundColor Yellow
        $stalePids = netstat -ano | Select-String "LISTENING" | Select-String ":6185\s" |
            ForEach-Object { ($_.Line -split '\s+')[-1] } | Sort-Object -Unique
        foreach ($sp in $stalePids) {
            if ($sp -match '^\d+$') {
                taskkill /F /PID $sp 2>$null | Out-Null
                Write-Host "      已停止半死实例 PID $sp" -ForegroundColor Yellow
            }
        }
        Start-Sleep -Seconds 3
    }
    Write-Host "  [..] 启动 AstrBot ..."
    $env:PYTHONIOENCODING = "utf-8"

    # 日志落盘 + 轮转：AstrBot 的日志只走 stdout，隐藏窗口下会全部丢失，
    # 出问题（例如「任务完成通知发不出去」）时无从倒查它是何时、为何没的。
    #
    # ⚠️ 必须用 PowerShell 原生重定向。曾写成 `cmd /c "<exe>" "<script>" >> log 2>&1`，
    #    该写法被 cmd 的 /c 引号剥离规则吃坏：python 根本没启动、日志也不生成，
    #    症状就是「双击一键启动没效果」（2026-09-19 踩过）。
    #    PowerShell 限制 stdout / stderr 不能指向同一个文件，故分成两个文件。
    $logDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\logs"))
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    foreach ($base in @("astrbot.log", "astrbot.err.log")) {
        $p = Join-Path $logDir $base
        if (Test-Path -LiteralPath $p) {
            $name = [System.IO.Path]::GetFileNameWithoutExtension($base)
            $ext = [System.IO.Path]::GetExtension($base)
            Move-Item -LiteralPath $p -Destination (Join-Path $logDir "$name-$stamp$ext") -Force
        }
    }
    Get-ChildItem -Path $logDir -Filter "astrbot-*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip 5 | Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $logDir -Filter "astrbot.err-*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip 5 | Remove-Item -Force -ErrorAction SilentlyContinue

    Start-Process -FilePath "C:\Python310\python.exe" -ArgumentList "D:\dsh\QQbot\run_astrbot.py" `
        -WorkingDirectory "D:\dsh\QQbot\astrbot" -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "astrbot.log") `
        -RedirectStandardError (Join-Path $logDir "astrbot.err.log")
    Write-Host "  [OK] AstrBot 已启动（日志：$logDir\astrbot.log）"

    # 起完再验一次：OneBot 端口绑上了才算真的可用
    Write-Host "  [..] 等 OneBot 绑定 3002 ..."
    $ok3002 = $false
    for ($i=0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 3002 -WarningAction SilentlyContinue).TcpTestSucceeded) { $ok3002 = $true; break }
    }
    if ($ok3002) { Write-Host "  [OK] OneBot 已就绪（3002 已监听，QQ 通道可用）" -ForegroundColor Green }
    else { Write-Host "  [!] 3002 仍未监听 —— 请看日志：$logDir\astrbot.log（多半是端口被占）" -ForegroundColor Yellow }
}

Write-Host ""
Write-Host "----- 访问入口 -----" -ForegroundColor Cyan
Write-Host "  DSH Web       : http://localhost:3080"
Write-Host "  AstrBot WebUI : http://localhost:6185"
Write-Host "  SnowLuma WebUI: http://localhost:5099"
Write-Host "  在 QQ 群 <TEST_GROUP_ID> 发消息，即可测试南汐回复" -ForegroundColor Green
Write-Host ""
Write-Host "本脚本运行完毕，服务已在后台运行。按任意键关闭本窗口。" -ForegroundColor Gray

Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
