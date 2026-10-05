# ============================================================================
#  start-nanxi-dsh.ps1 -- launch Nanxi's ISOLATED dsh web instance (port 3081)
#
#  Why a separate instance:
#    Nanxi (the QQ bot) drives her own DSH agent. Running it inside the main
#    dsh process means a heavy task on her side stalls the GUI you are using
#    (measured 2026-10-04: 44s of directory IO froze the whole web UI).
#    This instance has its own DSH_HOME, its own port, and its own plugin set.
#
#  What is shared with the main instance:
#    sessions/  -> junction to %USERPROFILE%\.dsh\sessions  (her sessions stay
#                  visible in the main GUI; per-session cross-process write
#                  locks make this safe)
#    skills/    -> junction to %USERPROFILE%\.dsh\skills
#  What is NOT shared:
#    storages/  -> independent. The official docs say dsh-storage-json has NO
#                  cross-process write lock ("last writer wins"), so sharing it
#                  between two live instances would risk lost updates.
#
#  ASCII only on purpose: Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI.
#
#  Usage:
#    powershell.exe -NoProfile -ExecutionPolicy Bypass -File start-nanxi-dsh.ps1
# ============================================================================

param(
    [int]$Port   = 3081,
    [int]$HeapMB = 4096
)

$ErrorActionPreference = 'Continue'

$dshHome  = 'D:\dsh\nanxi-dsh'
$logDir   = Join-Path $dshHome 'logs'
$crashDir = Join-Path $dshHome 'crash'
$dshCmd   = Join-Path $env:APPDATA 'npm\dsh.cmd'

New-Item -ItemType Directory -Force -Path $logDir, $crashDir | Out-Null

# --- do not start a second copy on the same port ----------------------------
$busy = @(netstat -ano | Select-String (":" + $Port + "\s") | Where-Object { $_ -match 'LISTENING' })
if ($busy.Count -gt 0) {
    Write-Host ('Port ' + $Port + ' is already listening - the nanxi instance looks like it is already up.')
    $busy | ForEach-Object { Write-Host ('  ' + $_.Line.Trim()) }
    Write-Host 'Nothing to do.'
    Read-Host 'Press Enter to close'
    exit 0
}

if (-not (Test-Path -LiteralPath $dshCmd)) {
    Write-Host ('ERROR: dsh.cmd not found at ' + $dshCmd)
    Read-Host 'Press Enter to close'
    exit 1
}

# --- environment ------------------------------------------------------------
$env:DSH_HOME = $dshHome
# ⚠️ 权限模式**只认** read-only / workspace-write / danger-full-access（2026-10-04 踩过：
#    填别的值会让 sandboxPolicy 服务起不来，整棵工具树链式残废）。
# 2026-10-04 起给 nanxi 开成 danger-full-access，与主实例对齐 —— 理由（主人拍板）：
# 「不让南汐有操作电脑的权限」这个想法是错的。默认的 workspace-write 会让正常活（比如
# vitest 要 spawn 子进程）在沙箱里被拒，然后弹一个**主人不一定看得到**的提权审批，
# 白卡好几分钟。开满之后她能像主实例一样直接干活。
$env:DSH_PERMISSION_MODE = 'danger-full-access'
$env:NODE_OPTIONS = "--max-old-space-size=$HeapMB --report-on-fatalerror --report-directory=$crashDir --report-compact"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log   = Join-Path $logDir ('nanxi-web-' + $stamp + '.log')

# --- keep only the newest 30 console logs -----------------------------------
$old = @(Get-ChildItem -Path $logDir -Filter 'nanxi-web-*.log' -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime -Descending | Select-Object -Skip 30)
if ($old.Count -gt 0) { $old | Remove-Item -Force -ErrorAction SilentlyContinue }

Write-Host ''
Write-Host '=========== Nanxi DSH instance ==========='
Write-Host ('  DSH_HOME : ' + $dshHome)
Write-Host ('  profile  : nanxi')
Write-Host ('  port     : ' + $Port)
Write-Host ('  console  : ' + $log)
Write-Host ('  NODE_OPTIONS : ' + $env:NODE_OPTIONS)
Write-Host '  Keep this window open while Nanxi is in use.'
Write-Host '  Ctrl+C, or closing the window, stops this instance.'
Write-Host '=========================================='
Write-Host ''

# NOTE (2026-10-05): the pipeline here used to feed a StreamWriter while DSH ran,
# but PowerShell buffers native-command output -- so the log file stayed 0 bytes
# for as long as the service lived (it never exits, so the log always looked
# empty). Worse, whoever grabbed the file first locked the other one out.
# Redirect inside cmd instead: each line lands on disk immediately.
$inner  = '{0} --profile nanxi --port {1} --no-open' -f $dshCmd, $Port
try {
    & cmd.exe /c ('{0} > "{1}" 2>&1' -f $inner, $log)
} finally {
    if (Test-Path $log) {
        Get-Content -LiteralPath $log -Encoding UTF8 -ErrorAction SilentlyContinue |
            Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
    }
}

Write-Host ''
Write-Host ('nanxi dsh web exited with code ' + $LASTEXITCODE)
Write-Host ('full log : ' + $log)
Read-Host 'Press Enter to close'
