# 南汐测试 bot —— 使用说明（第二个 QQ 号驱动端到端测试）

> 建立于 2026-10-03。目标：让 DSH 里的 agent **自己**就能给南汐做真实群内验收，
> 不再依赖主人手动在群里发消息、手动截图回传。
> 配套技能：`nanxi-bot-e2e-test`（技能库）｜配套工具：`tools\nanxi-test.ps1`

---

## 1. 一句话

**用第二个真实 QQ 号（`<TEST_BOT_QQ>`，昵称「deepseek」）在只有 4 个人的私有群 `<TEST_GROUP_ID>` 里说话，
看南汐（`<BOT_QQ>`）真的回什么** —— 发消息、读回复、判延迟，全自动。

---

## 2. 角色与端口

| 角色 | QQ | 说明 |
|---|---|---|
| 南汐（被测） | `<BOT_QQ>` | SnowLuma **主实例**，AstrBot 平台 `onebot-qq` |
| 测试小号（驱动） | `<TEST_BOT_QQ>` | SnowLuma **第二实例**，昵称 `deepseek`，群管理员、**非主人** |
| 主人 | `<OWNER_QQ>` | 唯一主人；`/dsh`、`/mas 提issue` 只对他放行 |
| 测试群 | `<TEST_GROUP_ID>` | 群名「自己」，**仅 4 人**（主人 + 北晨3号 + deepseek + 南汐） |

| 端口 | 归属 | 宿主机可达 |
|---|---|---|
| 3000 | 主实例 OneBot HTTP | ✅ 映射 |
| 3001 | 主实例 OneBot WS | ✅ 映射 |
| **3010** | **测试小号 OneBot HTTP** | ❌ **仅容器内**（靠 `docker exec` 访问） |
| 3002 | AstrBot 反向 WS —— 平台 **`onebot-qq`**（南汐主号） | ✅ |
| **3003** | AstrBot 反向 WS —— 平台 **`onebot-qq-test`**（测试小号） | ✅ |
| 5099 / 6081 | SnowLuma WebUI / noVNC | ✅ |

---

## 3. 架构与四条关键结论

```
测试小号 <TEST_BOT_QQ> ── SnowLuma 第二实例（HOME=/app/.local/share/qq2，独立 QQ 客户端）
      ├─ OneBot HTTP 127.0.0.1:3010        ← 容器内回环
      └─ wsClient ──► ws://host.docker.internal:3003/ws   ← 平台 onebot-qq-test
南汐 <BOT_QQ> ────── SnowLuma 主实例
      ├─ OneBot HTTP 127.0.0.1:3000
      └─ wsClient ──► ws://host.docker.internal:3002/ws   ← 平台 onebot-qq
                                    │
                              AstrBot(6185) ── DeepSeek
```

1. **★ 两个 bot 必须挂在两个独立的 aiocqhttp 平台实例上**（3002 / 3003）。
   **不要**图省事让它们共用一个平台 —— `send_by_session()` 主动发送时传的是 `event=None`，
   `routing_params` 因此为空，同一个平台里有**两个连接**时 `call_action` 选不出目标，
   抛 `aiocqhttp.exceptions.ApiNotAvailable`，**AstrBot 的全部主动发送立刻挂掉**
   （`/api/v1/im/messages` 返回 HTTP 400 `Failed to send message` ⇒ `notify_owner` 群通知与
   mas 游戏播报全部静默失效）。单连接时不需要 `self_id` 也能选中，所以单 bot 时代一直正常
   —— **这是 2026-10-03 实测踩出来的坑，运维操作见 §11。**
2. **回复仍由南汐主号发出** —— 触发回复的是**主号那条连接**上报的事件（主号也在群里，`self_id=<BOT_QQ>`）。
3. 小号配置里 `reportSelfMessage: false` ⇒ **小号自己发的消息不上报**，
   一条群消息在 AstrBot 侧**只处理一次**（南汐视角），不会双回复、不会自环。
4. 小号**不占用新的宿主机端口**（3010 只在容器内）⇒ 主号原有链路零改动。

---

## 4. 怎么用

### 4.1 直接调工具脚本（推荐）

```powershell
# 自检：容器 / 小号身份 / 群成员 / 最近消息
& <PROJECT_ROOT>\tools\nanxi-test.ps1 status

# 一条龙：发消息 → 等回复 → 报延迟（JSON 可编程判定）
& <PROJECT_ROOT>\tools\nanxi-test.ps1 test "用一句话介绍你自己" -AsJson
# => {"ok":true,"sent":"...","reply":"...","latency_s":4,"seq":6163}

# 读最近消息 / 只发不等 / 透传任意 OneBot API
& <PROJECT_ROOT>\tools\nanxi-test.ps1 read -Count 10
& <PROJECT_ROOT>\tools\nanxi-test.ps1 send -Text "你好"      # 默认自动 @南汐
& <PROJECT_ROOT>\tools\nanxi-test.ps1 send -NoAt -Text "/mas 问题"
& <PROJECT_ROOT>\tools\nanxi-test.ps1 raw -Api get_group_list -Body '{}'
```

**token 不落在任何文件里** —— 脚本运行时从容器
`/app/data/config/onebot_<TEST_BOT_QQ>.json` 的 `networks.httpServers[0].accessToken` 读取。

### 4.2 让 agent 自己测

技能 `nanxi-bot-e2e-test` 已把这套流程写成可复用技能（含典型场景、坑、排障）。
在技能库确认采纳后，agent 遇到「验收南汐 / 回归插件 / 验证权限」会自动接上。

---

## 5. 前置条件（不满足就别开始）

- **必须 `danger-full-access`**：所有操作走 `docker` CLI；`workspace-write` 沙箱下
  `docker exec` 会因 npipe 权限被拒（症状：`permission denied while trying to connect to
  the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`）。
- 容器 `snowluma` 在跑，且 **`supervisorctl status` 里有 `qq-extra-1`**。
- 小号处于登录态（登录态持久化在卷 `qq-client-data` → 容器内 `/app/.local/share/qq2`）。

---

## 6. ⚠️ 容器重启后怎么办（重要）

**现状（2026-10-03 建立时）**：第二实例是通过**手动写 supervisor 配置**起的，
而 `/etc/supervisor/conf.d/` **不在卷里** ⇒ **容器一重启，`qq-extra-1` 就没了**
（`start.sh` 会 `rm -f` 同目录的 `extra-qq.conf`，然后按（为空的）`SNOWLUMA_EXTRA_QQ_HOMES` 重新生成）。

**小号的登录态不会丢**（在卷里），丢的只是「谁来启动那个 QQ 客户端」。

### 6.1 临时恢复（30 秒，不重启容器）

**一键（推荐）**：

```powershell
<PROJECT_ROOT>\启动\恢复测试bot.ps1
```

等价的手工步骤（脚本内部就是这几步）：

```powershell
docker exec snowluma sh -c "mkdir -p /app/.local/share/qq2 && chown -R 1000:1000 /app/.local/share/qq2"
docker cp <PROJECT_ROOT>\tools\extra-qq.conf snowluma:/etc/supervisor/conf.d/extra-qq.conf
docker exec snowluma sh -c "tr -d '\r' < /etc/supervisor/conf.d/extra-qq.conf > /tmp/e && mv /tmp/e /etc/supervisor/conf.d/extra-qq.conf; supervisorctl reread; supervisorctl update"
```

> ⚠️ 配置里的 `DBUS_SESSION_BUS_ADDRESS` **必须**写成 supervisor 的运行时插值
> `%(ENV_DBUS_SESSION_BUS_ADDRESS)s`，**不要硬编码** —— 那个 dbus socket 路径每次容器启动都带新的随机后缀，
> 硬编码只能撑到下一次重启（这一版踩过，已修）。`tools\extra-qq.conf` 已是正确写法（取自 SnowLuma 官方 `start.sh` 的模板）。

### 6.2 根治（暂不可用）：重建容器，带上 `SNOWLUMA_EXTRA_QQ_HOMES`

> ⚠️ **2026-10-03 实测：这条路暂时走不通。** 按下面命令重建后，新容器启动即崩：
> `/root/start.sh: line 146: /usr/local/bin/node: Operation not permitted`（exit 126），
> 配合 `--restart unless-stopped` 变成重启循环（3000/3001/5099/6081 全部起不来）。
> `SNOWLUMA_EXTRA_QQ_HOMES` 本身**是生效的**（日志里有 `Configured 1 extra QQ instance(s)`），
> 卡住的是 start.sh 里那次 `node` 调用 —— 而**同一镜像的旧容器完全正常**，疑似 Docker Desktop/WSL2 侧问题。
> **当场已回滚**：`docker rm -f snowluma` → `docker rename snowluma-old snowluma` → `docker start snowluma`，
> 主号与卷数据均无损。
>
> ⇒ **结论：用 §6.1 的恢复脚本代替**（配合「自动登录」，重启后跑一次即可、**不用重新扫码**）。
> 若将来再试，**务必先 `docker rename` 保留旧容器**，不要直接 `rm`。

**（以下为原理与原始命令，保留备用）** 这是官方多实例开关，容器创建时给环境变量即可，
`start.sh` 会自己生成 supervisor 配置，从此重启容器也会自动拉起两个 QQ 实例。

```powershell
# 0) 备份旧容器（可回滚，别删）
docker stop snowluma
docker rename snowluma snowluma-old

# 1) 用完全相同的镜像/卷/端口重建，只多一个 SNOWLUMA_EXTRA_QQ_HOMES
docker run -d --name snowluma --restart unless-stopped `
  -p 3000:3000 -p 3001:3001 -p 5099:5099 -p 6081:6081 `
  -e VNC_PASSWD=<REDACTED-VNC-PASSWORD> `
  -e TZ=Asia/Shanghai `
  -e DISPLAY=:1 `
  -e SNOWLUMA_HOME=/app/runtime `
  -e SNOWLUMA_DATA=/app/data `
  -e SNOWLUMA_WEBUI_PORT=5099 `
  -e SNOWLUMA_UID=1000 -e SNOWLUMA_GID=1000 `
  -e SNOWLUMA_LOG_LEVEL=info `
  -e SNOWLUMA_SCREEN=1920x1080x24 `
  -e SNOWLUMA_HOOK_AUTOLOAD=1 `
  -e "SNOWLUMA_EXTRA_QQ_HOMES=/app/.local/share/qq2" `
  -e "SNOWLUMA_QQ_FLAGS=--disable-gpu --disable-software-rasterizer --disable-gpu-compositing" `
  -v qq-client-data:/app/.local/share `
  -v qq-gateway-data:/app/data `
  -v qq-client-config:/app/.config `
  motricseven7/snowluma:latest

# 2) 验证：应有 qq / qq-extra-1 / snowluma 三个程序在 RUNNING
Start-Sleep -Seconds 40
docker exec snowluma supervisorctl status
netstat -ano | Select-String ":3000\s|:3001\s|:3002\s|:5099\s|:6081\s"

# 3) 确认成功后再删旧容器
docker rm snowluma-old
```

**失败回滚**（一步退回）：

```powershell
docker rm -f snowluma
docker rename snowluma-old snowluma
docker start snowluma
```

> 主号**不需要重新扫码**：登录态在卷 `qq-client-config`（`/app/.config/QQ`）里，
> 实测容器/SnowLuma 多次重启后主号都自动登录（2026-10-03 21:26 与 21:36 各验证一次）。

---

## 7. 建这套东西时踩过的坑（都真踩了）

| 坑 | 现象 | 正解 |
|---|---|---|
| `curl -d '{"json"}'` 四层引号 | JSON 被撕碎 / `Syntax error: Unterminated quoted string` | **base64 → 容器内 `/tmp/nanxi-req.json` → `curl -d @file`** |
| `$json \| docker exec -i ... --data-binary '@-'` | 交互式 shell 可用，**脚本里失效** → SnowLuma 报 `invalid json` | 同上；别用 stdin 那条路 |
| 无参 API 用 POST `{}` | `bad request: invalid json` | 无参 API（`get_login_info`/`get_group_list`）**用 GET** |
| PowerShell 里 `--data-binary @-` | `Unrecognized token in source text`（`@` 是 PS 符号） | 加引号 `'@-'`；或干脆不用它 |
| **给 QQ 窗口发 `Escape`** | QQ 主窗口被 unmapped（隐藏），remap 后**白屏**（Electron 不重绘） | **永远别发 Escape**；恢复了也别只 remap |
| 手动 `xdotool windowmap` 后白屏 | 窗口回来了但一片灰 | **`supervisorctl restart qq`**（登录态在卷里，会自动恢复） |
| 容器里没 `xdotool` | 无法精确点击/输入 | `docker exec -u 0 snowluma apt-get install -y xdotool`（容器内有 `ffmpeg` 可 X11 抓屏） |
| SnowLuma WebUI 密码忘了 | 进不去 5099 | **没解决**（`webui.json` 重置后日志不再打印新密码）；但本方案**不需要 WebUI** |
| **扫码没勾「自动登录」** | 容器/实例每次重启，小号都退回扫码界面（登录态其实还在） | 扫码时**务必勾上「自动登录」**（那是 QQ 客户端自己的开关，只有勾了才会免扫码）。已勾过一次即可；恢复脚本会在 3010 未监听时提示这一点 |
| **重建容器时 node 执行失败** | 2026-10-03 实测：新容器 `start.sh: line 146: /usr/local/bin/node: Operation not permitted`（exit 126）→ `unless-stopped` 导致重启循环 | 已 `docker rm -f` 坏容器 + `docker rename snowluma-old snowluma` **回滚成功**（主号与卷数据均无损）。**持久化重建这条路暂时搁置** —— 用 `启动\恢复测试bot.ps1` 代替。若要再试，务必先 `docker rename` 保留旧容器 |
| **硬编码 DBUS 地址** | 容器重启后用恢复脚本起不来第二实例 | 用 supervisor 的 **`%(ENV_…)s` 运行时插值**（SnowLuma 官方 `start.sh` 就是这么生成的）；dbus socket 路径每次启动都变 |

**抓屏与点击的可靠做法**（容器内）：

```powershell
# 抓屏（容器有 ffmpeg，无 ImageMagick）
docker exec snowluma sh -c "DISPLAY=:1 ffmpeg -loglevel error -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 -y /tmp/s.png"
docker cp snowluma:/tmp/s.png <PROJECT_ROOT>\_tmp\s.png

# 裁剪某个区域（例如二维码）
docker exec snowluma sh -c "ffmpeg -loglevel error -i /tmp/s.png -vf 'crop=340:475:790:295' -y /tmp/qr.png"

# 点击 / 列窗口
docker exec snowluma sh -c "DISPLAY=:1 xdotool mousemove 224 701 click 1"
docker exec snowluma sh -c "DISPLAY=:1 xwininfo -root -children | head -30"
```

---

## 8. 安全红线

1. **只在 `<TEST_GROUP_ID>` 发消息**。测试小号是**真实 QQ 号**，在真实群里发言真人可见。
   小号还在 `1051749095`、`<GROUP_B>`（**494 人真实群**）—— 后者除非必要**不要碰**。
2. **不要用小号冒充主人 `<OWNER_QQ>`**。AstrBot 按 `sender.user_id` 判主人，
   冒充 = 绕过权限，可能真的触发 `/dsh` 执行与 GitHub `提issue`。
3. **token 不落库**：`onebot_<TEST_BOT_QQ>.json`、`_tmp/extra-qq.conf` 都在 `.gitignore` 覆盖范围内，
   别 `git add -f`。
4. 小号是**群管理员**，但**不是主人** —— 这正好覆盖「管理员但无主人权限」这条容易漏测的路径。

---

## 9. 端到端验证记录（2026-10-03）

```
SENT   : @Nanxi 1+1等于几？
REPLY  : 等于2呀喵～这种问题也太简单了吧，小看我呢(・ω・)

         不过好歹是陪着你说说话，想再考我点什么也可以哦，反正闲着也是闲着喵～
LATENCY: 4s  (seq 6161 -> 6163)
```

AstrBot 侧同一事件的日志（证明只处理一次、且回复走主号）：

```
[21:39:28.677] [onebot-qq(aiocqhttp)] deepseek/<TEST_BOT_QQ>: [At:<BOT_QQ>] 你好呀，在吗？
[21:39:29.694] [respond.stage:206] Prepare to send - deepseek/<TEST_BOT_QQ>: 在的在的喵～(・ω・)
[21:39:30.264] [onebot-qq(aiocqhttp)] 南汐/<BOT_QQ>: 在的在的喵～(・ω・)
```

---

## 10. 平台拆分变更记录（2026-10-03，必读）

**起因**：小号最初和主号连**同一个** AstrBot 平台（3002）。端到端测试当场是通过的，
但紧接着 `notify_owner` 报 `HTTP 400 Failed to send message` —— **AstrBot 的主动发送全挂了**。

**根因**（读 AstrBot 源码定位）：

- 主动发送走 `OpenApiService.send_message` → `platform_inst.send_by_session(session, chain)`
  → `AiocqhttpMessageEvent.send_message(bot=self.bot, event=None, ...)`；
- 而 `_dispatch_send` 的 `routing_params` 是从 **`event`** 推出来的 ——
  `routing_params = {"self_id": event.self_id} if event.self_id else {}`；
- `event=None` ⇒ `routing_params` 为空 ⇒ 同一平台实例里有**两个 WS 连接**时，
  `CQHttp.call_action` 无法确定用哪个 bot ⇒ 抛 `aiocqhttp.exceptions.ApiNotAvailable`；
- 只有一个连接时，不传 `self_id` 也能选中 ⇒ 单 bot 时代一直正常（所以这是**新增第二个 bot 才暴露**的坑）。

**修法**：给两个 bot 各自一个平台实例。

| 改什么 | 位置 | 改成 |
|---|---|---|
| AstrBot 平台 | `astrbot\data\cmd_config.json` 的 `platform` 数组 | 追加 `{id:"onebot-qq-test", type:"aiocqhttp", enable:true, ws_reverse_host:"0.0.0.0", ws_reverse_port:3003, ws_reverse_token:""}` |
| 小号 OneBot | 容器内 `/app/data/config/onebot_<TEST_BOT_QQ>.json` 的 `networks.wsClients[0].url` | `ws://host.docker.internal:3003/ws` |
| 主号 OneBot | 容器内 `/app/data/config/onebot_<BOT_QQ>.json` | **不动**（仍是 3002） |

**生效步骤**（实测顺序）：

```powershell
# 1) 改容器里小号的 wsClient 端口，再重载 SnowLuma gateway
docker exec snowluma sh -c "sed -i 's|host.docker.internal:3002|host.docker.internal:3003|' /app/data/config/onebot_<TEST_BOT_QQ>.json"
docker exec snowluma sh -c "supervisorctl restart snowluma"

# 2) 改完 AstrBot 配置后再重启它（★ 必须先改文件再重启）
netstat -ano | Select-String ":6185\s+0\.0\.0\.0:0\s+LISTENING"   # 取 PID
taskkill /F /PID <pid>
Start-Process -FilePath "C:\Python310\python.exe" -ArgumentList "<PROJECT_ROOT>\run_astrbot.py" `
  -WorkingDirectory "<PROJECT_ROOT>\astrbot" -WindowStyle Hidden `
  -RedirectStandardOutput "<PROJECT_ROOT>\logs\astrbot.log" -RedirectStandardError "<PROJECT_ROOT>\logs\astrbot.err.log"
```

> `danger-full-access` 下这样起的 AstrBot **能常驻**（不再像 `workspace-write` 时代那样被沙箱回收），
> 2026-10-03 实测：重启后 3002/3003/6185 三个端口都正常 LISTENING。

**验收三条**（缺一不可）：

```powershell
netstat -ano | Select-String ":3002\s|:3003\s"     # 两条链路都应有 ESTABLISHED
# im/bots 应返回 ["onebot-qq","onebot-qq-test"]
# 再跑一次主动发送自检（见 §9）与 tools\nanxi-test.ps1 test
```

**备份**：改前的配置在同目录 `cmd_config.json.bak-before-2nd-platform`。

**注意**：小号上报的消息 umo 现在是 `onebot-qq-test:GroupMessage:…`（**不在白名单**）——
这是**有意为之**：小号只负责"替 agent 发言"，它上报的别人的消息会被白名单拦掉，不产生副作用。
