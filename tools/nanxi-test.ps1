<#
.SYNOPSIS
    Nanxi bot end-to-end test driver (second QQ test account).

.DESCRIPTION
    Drives the SECOND QQ test account (<TEST_BOT_QQ>, nickname "deepseek") through
    the in-container OneBot v11 HTTP API, so an agent can exercise the Nanxi bot
    (<BOT_QQ>) end to end inside the isolated test group <TEST_GROUP_ID>.

    The OneBot access token is read from the container at run time, so no secret
    is stored in this file.

    Architecture (see AGENTS.md / 南汐测试bot-使用说明.md):
      test bot <TEST_BOT_QQ>  --(SNOWLUMA_EXTRA_QQ_HOMES instance)
                           --> OneBot HTTP 127.0.0.1:3010 (inside container)
                           \-> wsClient --> AstrBot reverse WS 3002
      Nanxi    <BOT_QQ>  --(main instance)
                           --> OneBot HTTP 127.0.0.1:3000 (inside container)
                           \-> wsClient --> AstrBot reverse WS 3002

    Because SnowLuma is reachable only through the Docker CLI, every API call is
    issued as:  docker exec [-i] snowluma curl ... --data-binary '@-'
    which also avoids both the quote-escaping and the encoding traps.

.NOTES
    SAFETY: the target group is HARD-CODED to the private test group. Never edit
    it to point at a real group - the test bot is a real QQ account and anything
    it posts is visible to real people.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('status', 'send', 'read', 'wait', 'test', 'raw', 'groups')]
    [string]$Action,

    [Parameter(Position = 1)]
    [string]$Text,

    [int]$Count = 10,
    [int]$TimeoutSec = 45,
    [string]$Api = 'get_login_info',
    [string]$Body = '{}',
    [switch]$NoAt,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'

# Force UTF-8 on the pipeline so Chinese survives (Windows PowerShell 5.1 needs this).
$OutputEncoding = [System.Text.Encoding]::UTF8

$Container  = 'snowluma'
# ⚠️ 下面三个号码是**你自己部署时才有**的，所以从环境变量读；没设就用示例值
#    （示例值发不出去 —— 部署时请务必设 NANXI_TEST_BOT_UIN / NANXI_BOT_QQ / NANXI_TEST_GROUP）。
# ⚠️ 别写成 `$x = if (...) { ... } else { ... }` —— 那是 **PowerShell 7** 的语法，
#    在 **Windows PowerShell 5.1 上不成立**，变量会静默变成空（本脚本踩过：症状是
#    `onebot_.json: No such file or directory`）。所以用两步赋值。
$TestBotUin = $env:NANXI_TEST_BOT_UIN; if (-not $TestBotUin) { $TestBotUin = '10001' }
$TestBotTag = 'deepseek'
$NanxiUin   = $env:NANXI_BOT_QQ;       if (-not $NanxiUin)   { $NanxiUin   = '10002' }
$TestGroup  = $env:NANXI_TEST_GROUP;   if (-not $TestGroup)  { $TestGroup  = '100001' }
$Port       = 3010
$ConfigPath = "/app/data/config/onebot_$TestBotUin.json"

$script:Token = $null

function Get-TestToken {
    $raw = & docker exec $Container cat $ConfigPath 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        throw "cannot read $ConfigPath inside container '$Container' (is the container up?)"
    }
    $cfg = $raw | ConvertFrom-Json
    $tok = $cfg.networks.httpServers[0].accessToken
    if (-not $tok) { throw "no httpServers[0].accessToken found in $ConfigPath" }
    return $tok
}

function Invoke-OneBot {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [string]$Json,
        [string]$Method = 'POST'
    )
    if (-not $script:Token) { $script:Token = Get-TestToken }
    $url = "http://127.0.0.1:$Port/$Endpoint"
    if ($Json) {
        # base64 the body, decode it inside the container, then curl -d @file:
        # this dodges every layer of quote escaping and keeps Chinese intact.
        $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Json))
        $sh  = "echo $b64 | base64 -d > /tmp/nanxi-req.json; curl -s -m 20 -X $Method $url -H 'Authorization: Bearer $script:Token' -H 'Content-Type: application/json' -d @/tmp/nanxi-req.json"
        $out = & docker exec $Container sh -c $sh 2>$null
    }
    else {
        $out = & docker exec $Container curl -s -m 20 -X GET $url -H "Authorization: Bearer $script:Token" 2>$null
    }
    if ($LASTEXITCODE -ne 0) { throw "docker exec curl failed while calling $Endpoint" }
    if (-not $out) { throw "empty response from $Endpoint" }
    $obj = $out | ConvertFrom-Json
    if ($obj.status -ne 'ok') { throw "OneBot API $Endpoint returned: $out" }
    return $obj
}

function Get-History {
    param([int]$N = 10)
    $json = @{ group_id = [long]$TestGroup; count = [int]$N } | ConvertTo-Json -Compress
    $r = Invoke-OneBot -Endpoint 'get_group_msg_history' -Json $json
    return @($r.data.messages | Sort-Object message_seq)
}

function Get-LatestSeq {
    # Highest message_seq currently in the group; 0 when the history is empty.
    #
    # The @() here is load-bearing. PowerShell unrolls a one-element array on
    # return, so `Get-History -N 1` hands back a bare object, and `$obj[-1]` on
    # a bare object is $null - which silently made `test` treat "everything ever
    # said" as new, so it reported some hours-old message as the reply. Use a
    # window wider than one and take the max.
    $hist = @(Get-History -N 5)
    if ($hist.Count -eq 0) { return 0 }
    $max = ($hist | Measure-Object -Property message_seq -Maximum).Maximum
    if ($null -eq $max) { return 0 }
    return [int]$max
}

function Get-PlainText {
    param($Message)
    $parts = @()
    foreach ($seg in $Message) {
        switch ($seg.type) {
            'text' { $parts += [string]$seg.data.text }
            'at'   { $parts += "[@$($seg.data.qq)]" }
            'image' { $parts += '[图片]' }
            'face' { $parts += '[表情]' }
            default { $parts += "[$($seg.type)]" }
        }
    }
    return ($parts -join '')
}

function Show-Message {
    param($Msg, [bool]$Mine)
    $who  = $Msg.sender.nickname
    $uid  = $Msg.user_id
    $mark = if ($Mine) { '>>' } else { '  ' }
    $line = "$mark [$($Msg.message_seq)] $who($uid): $(Get-PlainText $Msg.message)"
    Write-Host $line
}

# ---------------------------------------------------------------- actions ---

switch ($Action) {

    'status' {
        $info = Invoke-OneBot -Endpoint 'get_login_info'
        Write-Host "container : $Container"
        Write-Host "test bot  : UIN=$($info.data.user_id) nickname=$($info.data.nickname)"
        Write-Host "nanxi     : UIN=$NanxiUin"
        Write-Host "test group: $TestGroup"
        $members = (Invoke-OneBot -Endpoint 'get_group_member_list' -Json (@{ group_id = [long]$TestGroup } | ConvertTo-Json -Compress)).data
        Write-Host "members   : $($members.Count)"
        foreach ($m in $members) { Write-Host "            $($m.user_id) $($m.nickname) [$($m.role)]" }
        $hist = Get-History -N 3
        Write-Host "last 3 messages:"
        foreach ($h in $hist) { Show-Message -Msg $h -Mine ($h.user_id -eq [long]$TestBotUin) }
    }

    'groups' {
        $r = Invoke-OneBot -Endpoint 'get_group_list'
        foreach ($g in $r.data) { Write-Host "$($g.group_id)  $($g.group_name)  ($($g.member_count) members)" }
    }

    'send' {
        if (-not $Text) { throw "-Text is required for -Action send" }
        $chain = @()
        $body  = $Text
        if (-not $NoAt) {
            $chain += @{ type = 'at'; data = @{ qq = $NanxiUin } }
            $body = " $body"
        }
        $chain += @{ type = 'text'; data = @{ text = $body } }
        $json = @{ group_id = [long]$TestGroup; message = $chain } | ConvertTo-Json -Depth 8 -Compress
        $r = Invoke-OneBot -Endpoint 'send_group_msg' -Json $json
        Write-Host "sent to $TestGroup (message_id=$($r.data.message_id)): $(if($NoAt){''}else{"@Nanxi "})$Text"
    }

    'read' {
        $hist = Get-History -N $Count
        foreach ($m in $hist) { Show-Message -Msg $m -Mine ($m.user_id -eq [long]$TestBotUin) }
    }

    'wait' {
        $deadline = (Get-Date).AddSeconds($TimeoutSec)
        $start = Get-Date
        $seen = Get-LatestSeq
        while ((Get-Date) -lt $deadline) {
            $hist = Get-History -N 12
            $reply = $hist | Where-Object { $_.message_seq -gt $seen -and $_.user_id -eq [long]$NanxiUin } | Select-Object -First 1
            if ($reply) {
                Write-Host "NANXI REPLIED after $([int]((Get-Date) - $start).TotalSeconds)s:"
                Show-Message -Msg $reply
                if ($AsJson) { $reply | ConvertTo-Json -Depth 8 }
                return
            }
            Start-Sleep -Milliseconds 1200
        }
        Write-Host "NO REPLY within ${TimeoutSec}s"
        exit 2
    }

    'test' {
        if (-not $Text) { throw "-Text is required for -Action test" }
        $before = Get-LatestSeq

        $chain = @()
        $body  = $Text
        if (-not $NoAt) {
            $chain += @{ type = 'at'; data = @{ qq = $NanxiUin } }
            $body = " $body"
        }
        $chain += @{ type = 'text'; data = @{ text = $body } }
        $json = @{ group_id = [long]$TestGroup; message = $chain } | ConvertTo-Json -Depth 8 -Compress

        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        Invoke-OneBot -Endpoint 'send_group_msg' -Json $json | Out-Null
        Write-Host "SENT   : $(if($NoAt){''}else{'@Nanxi '})$Text"

        $deadline = (Get-Date).AddSeconds($TimeoutSec)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 1200
            $now = Get-History -N 12
            $reply = $now | Where-Object { $_.message_seq -gt $before -and $_.user_id -eq [long]$NanxiUin } | Select-Object -First 1
            if ($reply) {
                $sw.Stop()
                Write-Host "REPLY  : $(Get-PlainText $reply.message)"
                Write-Host "LATENCY: $([int]$sw.Elapsed.TotalSeconds)s  (seq $before -> $($reply.message_seq))"
                if ($AsJson) {
                    [pscustomobject]@{
                        ok        = $true
                        sent      = $Text
                        reply     = (Get-PlainText $reply.message)
                        latency_s = [int]$sw.Elapsed.TotalSeconds
                        seq       = $reply.message_seq
                    } | ConvertTo-Json -Depth 6
                }
                exit 0
            }
        }
        $sw.Stop()
        Write-Host "TIMEOUT: no reply from Nanxi within ${TimeoutSec}s"
        $after = Get-History -N 6
        foreach ($m in $after) { Show-Message -Msg $m -Mine ($m.user_id -eq [long]$TestBotUin) }
        exit 1
    }

    'raw' {
        $r = Invoke-OneBot -Endpoint $Api -Json $Body
        $r | ConvertTo-Json -Depth 12
    }
}
