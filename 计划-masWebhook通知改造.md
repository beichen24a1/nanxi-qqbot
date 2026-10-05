# 计划 · 用 mas 原生 Webhook 改造游戏日常通知

> 状态：**✅ 已实施（方案 A）· 2026-09-12**
> 主人决策：① 先只做 3 个（明日方舟/鸣潮/崩铁，蔚蓝档案 mas 不支持）；② 采用方案 A（mas Webhook 直接打 AstrBot 发送接口、固定句式）。
> 目标：mas 跑完某个游戏的日常后，**自己**把通知推出来（固定句式），机器人把这句话发到群 `<TEST_GROUP_ID>`。
> 实施结果见文末「八、实施结果」。

---

## 一、为什么要改（现方案的痛点）

现在的做法是：**mas 跑完 → 运行一个 bat → bat 调 DeepSeek 生成南汐口吻 → 调 AstrBot Open API 发群**。

痛点：
1. 要人工/外部把 bat 挂到 mas 的任务后边，mas 自己不知道有这回事；
2. 文案要过一次 LLM，慢、且不稳定（语气反复调）；
3. mas 的**任务失败/异常**也想通知时，bat 没法感知。

你想改成：**用 mas 自带的 Webhook 直接推**，并且**先不经过 AstrBot 的 LLM，固定句式发送**。

---

## 二、调研结论（已实读源码，非猜测）

### 2.1 mas 的自定义 Webhook 能力 —— 有，且足够用

实现在 `repo\app\services\notification.py` 的 `Notify.WebhookPush(title, content, webhook)`。

**配置项**（`repo\app\models\config.py` 里的 `Webhook` 类）：

| 配置 | 含义 | 说明 |
|---|---|---|
| `Info.Name` | 名称 | 卡片上显示用 |
| `Info.Enabled` | 是否启用 | 关掉就不推 |
| `Data.Url` | 目标地址 | 走 URL 校验（http/https） |
| `Data.Method` | `POST` / `GET` | 只支持这两种 |
| `Data.Headers` | 请求头 | **必须是合法 JSON 字符串**，如 `{"Authorization":"Bearer xxx"}` |
| `Data.Template` | 消息模板 | 可为 JSON 或纯文本，见下 |

**模板变量**（只有这 5 个）：

| 变量 | 内容 |
|---|---|
| `{title}` | 通知标题（如「明日方舟 · 代理结果」这类，由 mas 各任务模块给出） |
| `{content}` | 通知正文（完成数/未完成数/结果等） |
| `{datetime}` | `2026-09-11 21:30:00` |
| `{date}` | `2026-09-11` |
| `{time}` | `21:30:00` |

**模板解析逻辑**：先当 JSON 解析 → 递归替换变量；不是 JSON 就当纯文本替换（会转义引号/换行）；最终按 `Method` 发出去。

**成功判定（重要）**：`response.status_code == 200` 才算成功，否则 mas 记一条失败异常。→ **接收端必须回 200。**

### 2.2 mas 什么时候会推 —— 任务结果/统计/六星

以明日方舟（MAA）为例，`repo\app\task\MAA\tools\notify.py` 的 `push_notification(mode, title, message, user_config)`：

- `mode == "代理结果"`：受全局 `Notify.SendTaskResultTime` 控制（`任何时刻` / `仅失败时`），或本次含 `game_sign_summary`
- `mode == "统计信息"`：掉落/招募统计（受 `IfSendStatistic`）
- 六星出货推送（受 `IfSendSixStar`）

也就是说：**要"每次跑完都通知"，把 `SendTaskResultTime` 设成「任何时刻」即可**（你本机当前就是"任何时刻"）。

### 2.3 本机 mas 的现状（关键！）

`config\ScriptConfig.json` 里本机只配了 **3 个脚本**：

| uid | 类型 | 游戏 | 实际脚本 |
|---|---|---|---|
| `52b9fb32-…` | `MaaConfig` | **明日方舟** | MAA v5.10.2（`D:\jiao_ben\maa\...`） |
| `fdafc0ac-…` | `OkwwConfig` | **鸣潮** | OK-WW（`D:/jiao_ben/ok-/ok-ww`） |
| `aa203f94-…` | `HSRConfig` | **崩坏·星穹铁道** | March7thAssistant（`D:\jiao_ben\March7thAssistant_full`） |

`config\Config.json` 的 `Notify` 段目前：邮件/ServerChan/Webhook/Koishi **都没开**（`IfSendMail=false`、`IfServerChan=false`、`IfKoishiSupport=false`，且**没有 `CustomWebhooks` 键 = 还没配过自定义 Webhook**）。

### 2.4 ⚠️ 蔚蓝档案：mas 不支持

- mas v5.3.1 的任务模块只有：`MAA`(明日方舟)、`M9A`、`MaaEnd`(明日方舟:终末地)、`HSR`+`SRC`(崩铁)、`Okww`(鸣潮)、`OkNte`、`general`(通用)。
- 源码里 **grep 不到**「蔚蓝档案 / Blue Archive / BAAS」，**本机也没配**。

→ 结论：**蔚蓝档案没法用 mas 的 Webhook 通知**。需要你定夺（见第五节决策点）。

### 2.5 ⚠️ 发送通道：宿主机目前**无法**绕开 AstrBot 直发 QQ

实测（本轮实测，非推测）：

| 目标 | 结果 |
|---|---|
| `POST http://127.0.0.1:3000/get_login_info`（SnowLuma OneBot HTTP） | `RemoteDisconnected`（连上即被关闭） |
| TCP 探 3000 / 3001 发 HTTP | 连上后**立即返回空**（端口通、服务不可达） |

原因：SnowLuma 是 Docker 容器，容器内 OneBot 的 HTTP/WS 服务**绑定在容器内的 `127.0.0.1`**，宿主机的端口映射转发进去后目标不是 loopback，服务直接拒掉。

→ 所以：**宿主机上的进程要发 QQ 群消息，当前唯一可用通道就是 AstrBot**（AstrBot 是唯一持有活跃 OneBot 连接的本机进程 —— SnowLuma 主动反向 WS 连到 AstrBot 的 `3002`）。

要真正"完全不经过 AstrBot"，只能改 SnowLuma 容器内的 OneBot 监听为 `0.0.0.0` 并重启容器（有掉线/重新扫码风险），列为**备选方案 C**。

---

## 三、方案对比

### 方案 A（推荐）：mas Webhook 直接打 AstrBot 的发送接口，模板写死固定句式

```
mas 跑完日常（MAA / OK-WW / HSR）
      │  mas 原生「自定义 Webhook」触发（无需 bat、无需外部脚本）
      ▼
POST http://127.0.0.1:6185/api/v1/im/messages
   Headers: {"Content-Type":"application/json","Authorization":"Bearer <im_api_key>"}
   Template: {"umo":"onebot-qq:GroupMessage:<TEST_GROUP_ID>",
              "message":[{"type":"plain","text":"mas 把明日方舟的日常做完了喵，和主人说一声喵~ (´・ω・`)"}]}
      ▼
AstrBot 直接发到群 <TEST_GROUP_ID>（固定句式，不过 LLM）
```

- ✅ 最省：**不写任何代码**，mas 界面上填一条 Webhook 就有
- ✅ 固定句式（模板里写死），不经过南汐 LLM
- ✅ mas 自己触发，不用挂 bat
- ✅ 每游戏一条 Webhook → 各写各的固定句式（mas 支持 per-script / per-user Webhook）
- ✅ 复用已验证的 AstrBot Open API（`im/messages`，im-scope key 已有）
- ⚠️ 发送仍经 AstrBot **进程**（但只是管道，不生成内容、不过 LLM）

### 方案 B：mas Webhook → 本机小接收服务 → 固定句式 → 发群

```
mas Webhook → POST http://127.0.0.1:<端口>/webhook
   → 本机常驻小服务（Python，读固定句式表）
   → 经 AstrBot Open API 发群
```

- ✅ 灵活：能做多群、能加日志、能按游戏套不同句式、以后想接回 LLM 也行
- ✅ 对 mas 只暴露一个干净端点，mas 侧配置简单
- ⚠️ 要多常驻一个进程（开机自启要配）
- ⚠️ 发送仍经 AstrBot

### 方案 C：改造 SnowLuma 监听，彻底绕开 AstrBot

- 把 SnowLuma 容器内 `/app/data/config/onebot_<BOT_QQ>.json` 的
  `httpServers[0].host` 由 `127.0.0.1` 改为 `0.0.0.0`（必要时含 `wsServers`），重启容器。
- 之后宿主可直连 OneBot HTTP（`http://127.0.0.1:3000/send_group_msg`），mas Webhook 直接打过去，**真正不经 AstrBot**。
- ⚠️ 需要改容器内文件（本沙箱 docker CLI 被禁，需你手动执行）、**重启 SnowLuma 可能导致 QQ 掉线需重新扫码**；且 SnowLuma 的 HTTP server 是否提供 `/send_group_msg` 调用能力需实测确认。
- 建议：**作为后续可选优化**，不放在第一步。

---

## 四、推荐路线

**第一步（方案 A）**：用 mas 的 Webhook 直接打 AstrBot 发送接口，固定句式。

理由：零代码、立刻可用、可回滚（关掉 Webhook 即可），且完全满足"固定句式、不经 LLM、mas 自己触发"。

**第二步（可选，方案 B）**：如果之后要"多群 / 分游戏不同话术 / 留发送日志 / 想再交回南汐润色"，再引入本机接收服务。

**第三步（可选，方案 C）**：如果确实要彻底脱离 AstrBot（例如 AstrBot 不常开），再改 SnowLuma 监听。

### 固定句式草案（可逐条改）

| 游戏 | 句式（示例） |
|---|---|
| 明日方舟 | `mas 把明日方舟的日常做完了喵，和主人说一声喵~ (´・ω・`)` |
| 鸣潮 | `mas 把鸣潮的日常做完了喵，和主人说一声喵~ (´・ω・`)` |
| 崩坏：星穹铁道 | `mas 把崩铁的日常做完了喵，和主人说一声喵~ (´・ω・`)` |
| 蔚蓝档案 | ⚠️ mas 不支持，见决策点 |

可选增强：句尾拼 `{datetime}` 显示完成时间。

---

## 五、待主人确认的决策点

1. **蔚蓝档案怎么办？** mas 不支持它。
   - (a) 先只做 3 个（明日方舟/鸣潮/崩铁），蔚蓝档案以后另想办法；
   - (b) 蔚蓝档案也走"bat + 南汐 LLM"老路（保底能发）；
   - (c) 你说一个蔚蓝档案用的自动化工具名，我去查它有没有 webhook。
2. **发送通道**：确认接受"方案 A 仍经 AstrBot 进程发（但不过 LLM、固定句式）"？还是要直接上方案 C 改 SnowLuma？
3. **固定句式**：按上表草案，还是你给一版更想听的措辞？（每个游戏一句）
4. **是否只通知"成功完成"**，失败/异常要不要也发（mas 可按 `SendTaskResultTime` 控制：任何时刻 / 仅失败时）？
5. **旧方案（`游戏通知\` 那套 bat + LLM 生成）**保留备用，还是删掉？（建议保留，改个名归档）

---

## 六、实施步骤（确认后执行）

1. 在 mas「设置 → 通知」里新增 3 条自定义 Webhook（每个游戏一条）：
   - `Url` = `http://127.0.0.1:6185/api/v1/im/messages`
   - `Method` = `POST`
   - `Headers` = `{"Content-Type":"application/json","Authorization":"Bearer <im_api_key>"}`
   - `Template` = 固定句式 JSON（见方案 A）
2. 用 mas 界面自带的 **Webhook 测试**功能（源码里有 `WebhookTestIn` 接口）点一下，确认群里收到。
3. 跑一次真实日常，确认任务完成后自动播报。
4. 更新《维护笔记 / 更新记录 / 工作清单》，git 存档。

---

## 七、风险与回滚

| 风险 | 应对 |
|---|---|
| mas 要求接收端回 200，失败会记异常 | AstrBot Open API 正常返回 200 `{"status":"ok"}`，满足 |
| `Headers` 填错（非法 JSON）导致请求失败 | 严格按 JSON 写，先用 mas 的测试按钮验证 |
| AstrBot 未开机 / 未连上 QQ | 播报发不出；mas 侧会记失败（不影响游戏任务本身） |
| im_api_key 失效 | 重新在 AstrBot 建 im-scope key，仅改 mas 的 Headers |
| 回滚 | 把 mas 里对应 Webhook 的 `Enabled` 关掉即可，零副作用 |

---

## 八、实施结果（2026-09-12）

### 决策
- 蔚蓝档案：**暂不做**（mas 不支持），先只做明日方舟 / 鸣潮 / 崩坏·星穹铁道。
- 通道：**方案 A** —— mas 的 Webhook 直接 POST 到 AstrBot 的 `im/messages`，模板写死固定句式，不经 LLM。

### 关键实现细节（实读源码得出）

- **不能只配一条全局 Webhook**：全局 Webhook 对**所有**任务都触发，配 3 条会导致每次跑完发 3 条消息（3 个游戏的句式各来一遍）。
- **正确位置是「用户级 Webhook」**（每个游戏脚本下的用户配置各一条）：
  - 用户级 Webhook 只有在该通知带上 `user_config` 时才触发 —— 即 **"统计信息"** 通知；
  - 所以需要同时打开该用户的 `Notify.Enabled` 与 `Notify.IfSendStatistic`；
  - 触发时机：该用户当次日常成功完成时（`should_send_statistics`）。
- 「代理结果」通知（manager 层）传的是 `user_config=None` → **只走全局 Webhook**，因此不采用它来分游戏。

### 已落地的改动

新增 `游戏通知\apply_mas_webhook.py`（幂等 + 自动备份 + 预览模式），已执行 `--apply`：

| 游戏 | mas 脚本 | Webhook 名称 | 固定句式 |
|---|---|---|---|
| 明日方舟 | 新 MAA 脚本 | 南汐通知-明日方舟 | `mas 把明日方舟的日常做完了喵，和主人说一声喵~ (´・ω・`)` |
| 鸣潮 | 新 OK-WW 脚本 | 南汐通知-鸣潮 | `mas 把鸣潮的日常做完了喵，和主人说一声喵~ (´・ω・`)` |
| 崩坏：星穹铁道 | 新 三月七 脚本 | 南汐通知-崩坏：星穹铁道 | `mas 把崩铁的日常做完了喵，和主人说一声喵~ (´・ω・`)` |

每条 Webhook 的配置：

- `Url` = `http://127.0.0.1:6185/api/v1/im/messages`
- `Method` = `POST`
- `Headers` = `{"Content-Type":"application/json","Authorization":"Bearer <im_api_key>"}`
- `Template` = `{"umo":"onebot-qq:GroupMessage:<TEST_GROUP_ID>","message":[{"type":"plain","text":"<固定句式>"}]}`

改动前的原配置已备份：`ScriptConfig.json.bak-20260912-155820`。

### 验证

- ✅ 读回 mas 配置，3 条 Webhook 与开关均已生效；
- ✅ **完全模拟 mas 的 `WebhookPush`**（同样的 Url/Headers/Template/Method）请求 AstrBot → **3 条全部 HTTP 200**（mas 判定成功的条件），消息真实发到群。

### ⚠️ 修复记录：`instances` 索引缺失导致配置被 mas 清空（2026-09-12 晚）

**现象**（主人反馈）：mas 里看不到配置好的自定义 Webhook，也收不到通知。

**诊断**：
- 读回 mas 配置发现 **`CustomWebhooks` 整段消失**（而 `Notify.Enabled` / `IfSendStatistic` 的 `true` 仍保留）。
- 根因在 mas 源码 `app/models/ConfigBase.py::MultipleConfig.load`：
  *"如果字典中没有 `instances` 键, 则清空当前配置项"* —— 首次写入时漏了 `instances`。

**正确结构**：

```json
"CustomWebhooks": {
  "instances": [ {"uid": "<uid>", "type": "Webhook"} ],
  "<uid>": {"Info": {"Enabled": true, "Name": "..."},
            "Data": {"Url": "...", "Method": "POST", "Headers": "{...}", "Template": "{...}"}}
}
```

**修复内容**：
- `apply_mas_webhook.py` 新增 `upsert_webhook()`：写入时维护 `instances`（幂等，先按 uid 移除旧索引项再追加）。
- 修掉 `mas_running()` 的检测 bug：原先用 UTF-8 解码 `tasklist` 的 GBK 输出导致检测失准；
  现改为 PowerShell `Get-Process` 优先 + bytes 匹配兜底，并区分"无法确认"（返回 None）。

**二次验证（用 mas 自己的代码，非推测）**：在 mas 完全退出状态下写入后，用 mas 自带的
`environment\python\python.exe` 以 `MultipleConfig([Webhook])` 加载**真实配置**：

```
MaaUserConfig    kept=1 dirty=False 完全一致=True
OkwwUserConfig   kept=1 dirty=False 完全一致=True
HSRUserConfig    kept=1 dirty=False 完全一致=True
```

`dirty=False` 表示 mas **完全接受、不会纠正或重写** → 启动后 UI 可见、通知会生效。

**端到端复验**：再次模拟 mas 的 `WebhookPush` → **3 条全部 HTTP 200**，消息真实到群。

新备份：`ScriptConfig.json.bak-20260912-193415`。

### ⚠️ 待主人处理：避免重复通知

mas 里 **明日方舟** 与 **鸣潮** 的用户配置仍挂着「任务后执行脚本」（`ScriptAfterTask`）：

- `<PROJECT_ROOT>\游戏通知\明日方舟.bat`
- `<PROJECT_ROOT>\游戏通知\鸣潮.bat`

留着的话，同一件事会**通知两次**（Webhook 一次 + 那个 bat 再触发 LLM 版一次）。

**建议：在 mas 里把这 2 个「任务后执行脚本」清空**（崩铁的没配，无需处理）。
> 清空后，旧 bat 仍可手动运行作为备用手段。

### 以后怎么改

- 演示/预览要写入什么：双击 `游戏通知\预览mas通知配置.bat`
- 重新应用（改句式/换群后）：双击 `游戏通知\应用mas通知配置.bat`（会再次自动备份）
- 回滚：把 `ScriptConfig.json.bak-<时间戳>` 复制回 `ScriptConfig.json`

---

*本文档已随实施更新。*

