# Shared by both launchers. Windows PowerShell 5.1 compatible, ASCII only.
# winget updates registry PATH; an existing parent process may still have an old PATH.
$env:PYTHONIOENCODING = 'utf-8'
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    $probe = @(
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'),
        (Join-Path $env:USERPROFILE 'scoop\shims'),
        'C:\ffmpeg\bin'
    )
    foreach ($directory in $probe) {
        if (Test-Path -LiteralPath (Join-Path $directory 'ffmpeg.exe')) {
            $env:Path = $directory + ';' + $env:Path
            break
        }
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        $packageRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
        if (Test-Path -LiteralPath $packageRoot) {
            $executable = Get-ChildItem -LiteralPath $packageRoot -Recurse -Filter 'ffmpeg.exe' -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($executable) { $env:Path = $executable.Directory.FullName + ';' + $env:Path }
        }
    }
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning 'ffmpeg not found; mp3 files can be sent, but voice messages need ffmpeg.'
}
