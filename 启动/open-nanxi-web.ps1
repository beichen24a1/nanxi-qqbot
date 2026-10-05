# ============================================================================
#  open-nanxi-web.ps1 -- open Nanxi's DSH web UI (port 3081) in the browser.
#
#  Why this exists:
#    dsh 0.2.0 mints a fresh one-time token per process and prints the only
#    usable URL into the instance's own console log. Opening http://127.0.0.1:3081
#    directly returns 401. This script reads the URL back from the log for you.
#  ASCII only on purpose (PS 5.1 reads a BOM-less .ps1 as ANSI).
#  Usage:  open-nanxi-web.ps1            (open browser)
#          open-nanxi-web.ps1 -NoOpen    (just print the URL)
# ============================================================================
param([switch]$NoOpen)

$dshHome = 'D:\dsh\nanxi-dsh'
$logDir  = Join-Path $dshHome 'logs'

$latest = Get-ChildItem $logDir -Filter 'nanxi-web-*.out.log' -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) {
    $latest = Get-ChildItem $logDir -Filter 'nanxi-web-*.log' -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
if (-not $latest) {
    Write-Host 'No nanxi instance log found in ' -NoNewline
    Write-Host $logDir
    Write-Host 'Start the instance first:  start-nanxi-dsh.bat'
    Read-Host 'Press Enter to close'
    exit 1
}

$url = $null
foreach ($line in (Get-Content $latest.FullName -Encoding UTF8)) {
    if ($line -match 'dsh web:\s*(http://\S+)') { $url = $matches[1] }
}
if (-not $url) {
    Write-Host ('No entry URL found in ' + $latest.Name)
    Write-Host 'The instance probably failed to boot - check that log.'
    Read-Host 'Press Enter to close'
    exit 1
}

$port  = ([uri]$url).Port
$alive = @(netstat -ano | Select-String (':' + $port + '\s') | Where-Object { $_ -match 'LISTENING' }).Count -gt 0

Write-Host ''
Write-Host '=========== Nanxi DSH web UI ==========='
Write-Host ('  log  : ' + $latest.FullName)
Write-Host ('  port : ' + $port + '    listening: ' + $alive)
Write-Host ('  url  : ' + $url)
Write-Host '========================================'
Write-Host ''
Write-Host 'NOTE: the token is minted per process - this URL dies with the instance.'
Write-Host ''

if (-not $alive) {
    Write-Host ('Port ' + $port + ' is NOT listening - the instance is down.')
    Write-Host 'Start it with start-nanxi-dsh.bat, then run this again.'
    Read-Host 'Press Enter to close'
    exit 1
}

if ($NoOpen) { Write-Host '(-NoOpen) browser not launched.'; exit 0 }
Start-Process $url
Write-Host 'Opened in your default browser.'
Start-Sleep -Seconds 2