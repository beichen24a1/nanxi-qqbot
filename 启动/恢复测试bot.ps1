<#
.SYNOPSIS
    恢复 SnowLuma 的第二个 QQ 实例（测试小号 <TEST_BOT_QQ>）。

.DESCRIPTION
    容器重启后第二实例不会自动启动 —— /etc/supervisor/conf.d/ 不在卷里，而 start.sh
    只在「容器创建时带了 SNOWLUMA_EXTRA_QQ_HOMES」的情况下才会生成那个配置。
    本脚本把 tools\extra-qq.conf 放回容器并让 supervisor 加载它，幂等，可反复跑。

    登录态在卷 qq-client-data -> /app/.local/share/qq2，所以恢复后 **不需要重新扫码**。

.NOTES
    需要 danger-full-access（要调用 docker CLI）。
    根治办法是重建容器时带上 -e SNOWLUMA_EXTRA_QQ_HOMES=/app/.local/share/qq2，
    见 南汐测试bot-使用说明.md §6.2。
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [int]$WaitSeconds = 60
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.Encoding]::UTF8

$Container  = 'snowluma'
# 测试小号的 QQ：从环境变量读（部署时设 NANXI_TEST_BOT_UIN）；没设就用示例值。
# ⚠️ 别写成 `$x = if (...) { ... } else { ... }` —— 那是 PowerShell 7 语法，
#    在 Windows PowerShell 5.1 上变量会静默变空。
$TestBotUin = $env:NANXI_TEST_BOT_UIN; if (-not $TestBotUin) { $TestBotUin = '10001' }
$ConfDst    = '/etc/supervisor/conf.d/extra-qq.conf'
$HomeDir    = '/app/.local/share/qq2'
$ConfSrc    = (Resolve-Path (Join-Path $PSScriptRoot '..\tools\extra-qq.conf')).Path

function Get-SupStatus {
    $out = & docker exec $Container supervisorctl status 2>$null
    $map = @{}
    foreach ($line in $out) {
        if ($line -match '^(\S+)\s+(RUNNING|STOPPED|FATAL|STARTING|BACKOFF|EXITED)') {
            $map[$Matches[1]] = $Matches[2]
        }
    }
    return $map
}

Write-Host '== 恢复测试 bot ==' -ForegroundColor Cyan
Write-Host "   容器 : $Container"
Write-Host "   小号 : $TestBotUin"
Write-Host "   配置 : $ConfSrc"

# 1) docker 可用 + 容器在跑
$names = & docker ps --format '{{.Names}}' 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'docker CLI 不可用 —— 本脚本需要 danger-full-access 权限（在 DSH 里让 agent 用 danger-full-access 跑）'
}
if ($names -notcontains $Container) {
    throw "容器 $Container 没在运行 —— 请先双击 启动\一键启动.bat"
}
Write-Host '[1/5] 容器在运行' -ForegroundColor Green

# 2) 已经起来了就早退（幂等）
$sup = Get-SupStatus
if ($sup['qq-extra-1'] -eq 'RUNNING' -and -not $Force) {
    Write-Host '[✓] qq-extra-1 已经在运行，不用恢复' -ForegroundColor Green
    Write-Host '    自检：& D:\dsh\QQbot\tools\nanxi-test.ps1 status'
    exit 0
}

# 3) 准备隔离 HOME（登录态就在这里面，不会因为这一步丢失）
& docker exec $Container sh -c "mkdir -p $HomeDir && chown -R 1000:1000 $HomeDir"
if ($LASTEXITCODE -ne 0) { throw "无法准备 $HomeDir" }
Write-Host '[2/5] 隔离 HOME 就绪' -ForegroundColor Green

# 4) 放回 supervisor 配置（去掉 CR，supervisor 对 \r 敏感）
& docker cp $ConfSrc "${Container}:$ConfDst"
if ($LASTEXITCODE -ne 0) { throw "docker cp 失败：$ConfSrc -> $ConfDst" }
& docker exec $Container sh -c "tr -d '\r' < $ConfDst > /tmp/extra-qq.clean && mv /tmp/extra-qq.clean $ConfDst"
if ($LASTEXITCODE -ne 0) { throw '清理 CR 失败' }
Write-Host '[3/5] supervisor 配置已放入容器' -ForegroundColor Green

# 5) 让 supervisor 加载
& docker exec $Container supervisorctl reread | Out-Host
& docker exec $Container supervisorctl update | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'supervisorctl update 失败' }
Write-Host '[4/5] supervisor 已加载配置' -ForegroundColor Green

# 6) 先等 qq-extra-1 进入 RUNNING（QQ 客户端启动要 10~40 秒）
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$running = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $sup = Get-SupStatus
    if ($sup['qq-extra-1'] -eq 'RUNNING') { $running = $true; break }
}
if (-not $running) {
    Write-Host '[✗] 超时：qq-extra-1 没起来' -ForegroundColor Red
    Write-Host '    排查：docker exec snowluma supervisorctl status'
    Write-Host '          docker logs --tail 40 snowluma'
    exit 1
}
Write-Host '[5/5] qq-extra-1 已在运行' -ForegroundColor Green

# 7) 再看 OneBot 3010。没监听通常意味着 QQ 停在扫码界面 —— 那是合法中间态，不是失败。
#    ⚠️ 只有扫码时勾了「自动登录」，重启后才不需要重新扫。
$listenDeadline = (Get-Date).AddSeconds(45)
$listening = $false
while ((Get-Date) -lt $listenDeadline) {
    $listen = & docker exec $Container sh -c 'ss -tln | grep -c ":3010"' 2>$null
    if ($listen -match '^[1-9]') { $listening = $true; break }
    Start-Sleep -Seconds 3
}
if ($listening) {
    Write-Host '[✓] OneBot HTTP 3010 已监听（小号已登录）' -ForegroundColor Green
} else {
    Write-Host '[!] qq-extra-1 起来了，但 3010 还没监听' -ForegroundColor Yellow
    Write-Host '    这通常表示小号的 QQ 客户端停在「手机QQ扫码登录」界面，需要扫码才能继续。' -ForegroundColor Yellow
    Write-Host '    · 看画面：打开 http://localhost:6081 （VNC 密码 <REDACTED-VNC-PASSWORD>）' -ForegroundColor Yellow
    Write-Host '    · 或截图交给主人扫：' -ForegroundColor Yellow
    Write-Host '        docker exec snowluma sh -c "DISPLAY=:1 ffmpeg -loglevel error -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 -y /tmp/s.png"' -ForegroundColor Yellow
    Write-Host '        docker cp snowluma:/tmp/s.png .\qr.png' -ForegroundColor Yellow
    Write-Host '    ★ 扫码时务必勾上「自动登录」，否则每次重启都要重扫。' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '恢复完成。验证登录与端到端链路：' -ForegroundColor Cyan
Write-Host '  & D:\dsh\QQbot\tools\nanxi-test.ps1 status'
Write-Host '  & D:\dsh\QQbot\tools\nanxi-test.ps1 test "用一句话介绍你自己" -AsJson'
