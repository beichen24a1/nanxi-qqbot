# ============================================================================
#  restart-astrbot.ps1 -- restart AstrBot cleanly (archive logs, kill by port,
#  relaunch, wait until both 6185 and 3002 are listening).
#
#  Why this exists: the plugin's tool descriptions live in Python docstrings,
#  which AstrBot only reads at startup -- so every plugin edit needs a restart.
#
#  ASCII only on purpose (PS 5.1 reads a BOM-less .ps1 as ANSI).
#  NOTE: a process launched from a DSH session is a child of that session and
#  dies with it. For a long-lived AstrBot prefer double-clicking 一键启动.bat.
# ============================================================================
param([int]$WaitSec = 60)

$root     = 'D:\dsh\QQbot'
$logDir   = Join-Path $root 'logs'
$py       = 'C:\Python310\python.exe'
$launcher = Join-Path $root 'run_astrbot.py'
$workDir  = Join-Path $root 'astrbot'

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach ($n in @('astrbot.log', 'astrbot.err.log')) {
    $p = Join-Path $logDir $n
    if (Test-Path $p) {
        Move-Item $p (Join-Path $logDir ($n -replace '\.log$', "-$stamp.log")) -Force -ErrorAction SilentlyContinue
    }
}

$killed = @()
foreach ($port in @(6185, 3002)) {
    $conns = @(netstat -ano | Select-String (':' + $port + '\s') | Where-Object { $_ -match 'LISTENING' })
    foreach ($c in $conns) {
        $procId = [int](($c.ToString().Trim() -split '\s+')[-1])
        if ($killed -notcontains $procId) {
            taskkill /F /PID $procId 2>&1 | Out-Null
            $killed += $procId
            Write-Host ('  killed pid ' + $procId + ' (held ' + $port + ')')
        }
    }
}
if ($killed.Count -eq 0) { Write-Host '  nothing was holding 6185/3002' }
Start-Sleep -Seconds 3

$env:PYTHONIOENCODING = 'utf-8'
$out = Join-Path $logDir 'astrbot.log'
$err = Join-Path $logDir 'astrbot.err.log'
Start-Process -FilePath $py -ArgumentList $launcher -WorkingDirectory $workDir -WindowStyle Hidden `
    -RedirectStandardOutput $out -RedirectStandardError $err
Write-Host '  launched, waiting for 6185 ...'

$ok = $false; $i = 0
for ($i = 1; $i -le $WaitSec; $i++) {
    Start-Sleep -Seconds 1
    if (netstat -ano | Select-String ':6185\s' | Where-Object { $_ -match 'LISTENING' }) { $ok = $true; break }
}
Write-Host ('  6185 listening: ' + $ok + '  (' + $i + 's)')

if ($ok) {
    $j = 0
    for ($j = 1; $j -le 45; $j++) {
        Start-Sleep -Seconds 1
        if (netstat -ano | Select-String ':3002\s' | Where-Object { $_ -match 'LISTENING' }) { break }
    }
    Write-Host ('  3002 OneBot listening: ' + ($j -le 45) + '  (' + $j + 's)')
    $bots = $null
    try { Write-Host ('  plugins: ' + ((Select-String -Path $out -Pattern 'Added llm tool' -Encoding UTF8 | Measure-Object).Count) + ' llm tools registered') } catch {}
} else {
    Write-Host '  --- stderr tail ---'
    Get-Content $err -Tail 20 -Encoding UTF8 -ErrorAction SilentlyContinue
}
Write-Host ''
netstat -ano | Select-String ':6185\s|:3002\s|:3003\s' | Where-Object { $_ -match 'LISTENING' } | ForEach-Object { Write-Host ('  ' + $_.Line.Trim()) }
exit 0
