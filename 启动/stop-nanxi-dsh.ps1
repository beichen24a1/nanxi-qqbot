# ============================================================================
#  stop-nanxi-dsh.ps1 -- stop Nanxi's isolated DSH instance (port 3081).
#
#  Kills whatever is LISTENING on the port (that process IS the instance).
#  It never touches the main dsh (3080) or AstrBot.
#  ASCII only on purpose (PS 5.1 reads a BOM-less .ps1 as ANSI).
# ============================================================================
param([int]$Port = 3081)

$conns = @(netstat -ano | Select-String (':' + $Port + '\s') | Where-Object { $_ -match 'LISTENING' })
if ($conns.Count -eq 0) {
    Write-Host ('Port ' + $Port + ' is not listening - Nanxi''s instance is already stopped.')
    Read-Host 'Press Enter to close'
    exit 0
}

$pids = @($conns | ForEach-Object { [int](($_.ToString().Trim() -split '\s+')[-1]) } | Sort-Object -Unique)
Write-Host ''
foreach ($p in $pids) {
    $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
    $name = if ($proc) { $proc.ProcessName } else { '?' }
    Write-Host ('Stopping pid ' + $p + '  (' + $name + ')  holding port ' + $Port + ' ...')
    taskkill /F /PID $p 2>&1 | ForEach-Object { Write-Host ('  ' + $_) }
}
Start-Sleep -Seconds 3

$after = @(netstat -ano | Select-String (':' + $Port + '\s') | Where-Object { $_ -match 'LISTENING' })
Write-Host ''
if ($after.Count -eq 0) { Write-Host ('Nanxi''s instance on port ' + $Port + ' is stopped.') }
else { Write-Host ('Port ' + $Port + ' is STILL listening - check the output above.'); $after | ForEach-Object { Write-Host ('  ' + $_.Line.Trim()) } }
Write-Host ''
Read-Host 'Press Enter to close'