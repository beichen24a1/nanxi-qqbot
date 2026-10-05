<#
  接入星驿（AstrDsh Relay）一键脚本
  ================================================
  为什么需要你亲手跑这一遍：
    DSH 侧装包与写配置都要落在 %USERPROFILE%\.dsh\ 下，而 agent 的沙箱
    **进不去那里**（实测 EPERM），所以这一步只能在沙箱外由你执行。

  本脚本做四件事，**每步失败即停**，不会带病往下走：
    1. DSH 侧装包           dsh plugin --profile web add <tgz>
    2. 写 DSH 侧配置        给 profiles\web\cordis.patch.yml 追加 token 与 cwd
    3. 归档自研插件         把 astrbot_plugin_dsh 移出 plugins（避免 /dsh 前缀双触发）
    4. 装星驿的 AstrBot 侧   解压 zip 到 data\plugins\
  它最后只**停** AstrBot，**不替你重启 DSH**。跑完后请你：
    · 重启 DSH   ：双击 %USERPROFILE%\.dsh\bin\start-dsh-web.ps1
                   ★ 必须用它！`dsh plugin add` 会把插件自带的 cordis.patch.yml 重置成
                     上游原版（引用本机不存在的 @deepseek-ai/dsh-skill-local），
                     插件树会加载失败、dsh 起不来；这个启动脚本每次都会 self-heal 修掉它。
    · 重启 AstrBot：双击 D:\dsh\QQbot\启动\一键启动.bat

  回退：脚本会把改动过的 cordis.patch.yml 备份成 .bak-before-relay-<时间戳>；
        归档的插件在 D:\dsh\QQbot\_disabled_plugins\ 下，移回去即可。
#>

$ErrorActionPreference = 'Stop'

$proj     = 'D:\dsh\QQbot'
$dshHome  = Join-Path $env:USERPROFILE '.dsh'
$dshCmd   = Join-Path $env:APPDATA 'npm\dsh.cmd'
$patchF   = Join-Path $dshHome 'profiles\web\cordis.patch.yml'
$tgz      = Join-Path $proj '_dl\astrdsh-relay\dsh-astrbot-relay-0.9.7.tgz'
$zip      = Join-Path $proj '_dl\astrdsh-relay\astrbot_plugin_dsh_relay-0.9.7.zip'
$plugins  = Join-Path $proj 'astrbot\data\plugins'
$disabled = Join-Path $proj '_disabled_plugins'
$relayCwd = Join-Path $proj 'nx_dsh'

function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    --  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "`n    !!  $msg" -ForegroundColor Red; Read-Host '按回车退出'; exit 1 }

Write-Host '=========== 接入星驿 ===========' -ForegroundColor White

# ── 0) 前置检查 ───────────────────────────────────────────────
Step 0 '前置检查'
foreach ($p in @($dshCmd, $patchF, $tgz, $zip, $plugins)) {
    if (-not (Test-Path -LiteralPath $p)) { Fail "找不到：$p" }
}
Ok 'dsh.cmd / cordis.patch.yml / tgz / zip / plugins 目录 都在'

# ── 1) DSH 侧装包 ─────────────────────────────────────────────
Step 1 'DSH 侧装包'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item -LiteralPath $patchF -Destination "$patchF.bak-before-relay-$stamp" -Force
Ok "已备份 cordis.patch.yml -> cordis.patch.yml.bak-before-relay-$stamp"

& $dshCmd plugin --profile web add $tgz
if ($LASTEXITCODE -ne 0) { Fail "dsh plugin add 失败（退出码 $LASTEXITCODE）" }
Ok '装包完成'

# ── 2) 写 DSH 侧配置（幂等）───────────────────────────────────
Step 2 '写入 DSH 侧配置（token + cwd）'
$raw = Get-Content -LiteralPath $patchF -Raw -Encoding UTF8
if ($raw -match '(?m)^\s*-\s*id:\s*dsh-astrbot-relay\s*$') {
    Warn 'cordis.patch.yml 里已有 dsh-astrbot-relay 条目，跳过（不改动你现有的取值）'
} else {
    # token 由 agent 预先生成并写入 _refs\secrets\relay-token.txt（该目录已 gitignore），
    # 同时已写进 AstrBot 侧插件的配置 —— 两侧取值一致，你不必手抄任何密钥。
    $tokenFile = Join-Path $proj '_refs\secrets\relay-token.txt'
    if (-not (Test-Path -LiteralPath $tokenFile)) { Fail "找不到 token 文件：$tokenFile" }
    $token = (Get-Content -LiteralPath $tokenFile -Raw).Trim()
    if ($token.Length -lt 32) { Fail "token 长度不足 32（读到 $($token.Length)）" }

    $block = @"

# ── 星驿（AstrDsh Relay）：IM <-> DSH 网桥（2026-10-03 接入）──
# token 与 cwd 都是 required；patch 是【整体替换】该行 config，故这里只写这两项。
- id: dsh-astrbot-relay
  config:
    token: '$token'
    cwd: '$relayCwd'
"@
    Add-Content -LiteralPath $patchF -Value $block -Encoding UTF8
    Ok "已追加配置（cwd = $relayCwd）"
    Warn 'token 已与 AstrBot 侧配置同步写入，你不需要手抄'
}

# ── 3) 归档自研插件（避免 /dsh 双触发）───────────────────────
Step 3 '归档自研插件 astrbot_plugin_dsh'
$src = Join-Path $plugins 'astrbot_plugin_dsh'
$dst = Join-Path $disabled 'astrbot_plugin_dsh.disabled'
if (Test-Path -LiteralPath $src) {
    if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force }
    Move-Item -LiteralPath $src -Destination $dst
    Ok "已移出 plugins -> _disabled_plugins\astrbot_plugin_dsh.disabled"
} else {
    Warn 'plugins 下没有 astrbot_plugin_dsh（可能已归档），跳过'
}

# ── 4) 装星驿的 AstrBot 侧 ────────────────────────────────────
Step 4 '解压星驿的 AstrBot 侧插件'
Expand-Archive -LiteralPath $zip -DestinationPath $plugins -Force
$installed = Join-Path $plugins 'astrbot_plugin_dsh_relay'
if (-not (Test-Path -LiteralPath (Join-Path $installed 'metadata.yaml'))) {
    Fail "解压后没看到 $installed\metadata.yaml，请检查 zip 结构"
}
Ok "已装到 $installed"

# ── 5) 停 AstrBot（按端口，不误杀其它 python）────────────────
Step 5 '停 AstrBot（按端口 6185/3002）'
$stopped = $false
foreach ($port in 6185, 3002) {
    $lines = netstat -ano | Select-String ":$port\s.*LISTENING"
    foreach ($l in $lines) {
        $pid = ($l.ToString() -split '\s+')[-1]
        if ($pid -match '^\d+$' -and $pid -ne '0') {
            taskkill /F /PID $pid 2>&1 | Out-Null
            Ok "已停 PID $pid（端口 $port）"
            $stopped = $true
        }
    }
}
if (-not $stopped) { Warn '没找到监听 6185/3002 的进程（AstrBot 可能本来就没跑）' }

# ── 完成 ─────────────────────────────────────────────────────
Write-Host "`n=========== 脚本部分做完了 ===========" -ForegroundColor White
Write-Host '接下来请依次执行：' -ForegroundColor Yellow
Write-Host '  1) 重启 DSH   ：双击 %USERPROFILE%\.dsh\bin\start-dsh-web.ps1' -ForegroundColor White
Write-Host '                  （必须用它，它会 self-heal 修掉 dsh plugin add 留下的坏引用）' -ForegroundColor DarkGray
Write-Host '  2) 重启 AstrBot：双击 D:\dsh\QQbot\启动\一键启动.bat' -ForegroundColor White
Write-Host '  3) 回到 DSH 里告诉 agent「跑完了」，它会接着验收（bridge_token 已预填，无需你操作）' -ForegroundColor White
Write-Host ''
Read-Host '按回车关闭本窗口'
