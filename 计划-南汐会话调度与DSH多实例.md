# 计划：南汐的「会话调度」与 DSH 多实例

> **2026-10-04 立档。** 这份文档是**未完成事项的清单**，也是这一路踩坑的存档。
> 接手的人请先读 `AGENTS.md` 的「🚨 最新状态」，再回来看这里。
> 口径：**已完成 / 代码完成但未验证 / 未实施** 严格区分，别把"写完了"当成"跑通了"。

---

## 0. 一句话

让南汐从"只有一条固定的 DSH 会话"变成**像员工一样自己挑工作台**——
自己判断去哪干活、用现成的会话还是新开一间、要不要分个副本；
同时**为了不让她把主项目拖垮**，给她一个**独立的 DSH 实例**。

主人是项目经理，南汐是员工，DSH 工作区是她的工位。

---

## 1. 背景：为什么会有这份计划

1. **2026-10-03 深夜** 南汐自主调用 DSH 打通（插件 `astrbot_plugin_nanxi_dsh`，工具 `dsh_task`），
   但她当时只有**一条固定会话**（星驿建的 `im-f230637e`，cwd = `<PROJECT_ROOT>\nx_dsh`）。
2. 主人提出新要求：**"我像项目经理，南汐看到要求自己判断去找会话、或者判断是否要新建或分支会话。"**
3. **2026-10-04 事故**：一次测试让她 `rebind` 到 `mas`（AUTO-MAS 大项目）数目录，
   **44 秒的持续 IO 把 DSH Web 拖到无响应**——因为她和我（主项目会话）**跑在同一个 DSH 进程**里。
   主人重启 DSH，**AstrBot 作为 DSH 的子进程被连带杀死**。
   ⇒ 这直接催生了"给南汐独立实例"的需求，也暴露了测试方式的错误。

---

## 2. 已完成（代码在 `astrbot_plugin_nanxi_dsh\`，部署副本在 `astrbot\data\plugins\`）

| 能力 | 状态 | 实现位置 |
|---|---|---|
| `dsh_task(task, at="")` —— 跨项目出差 | 代码完成，**未端到端验证** | `dsh_task` / `_goto` / `_attach` |
| `dsh_look()` —— 工作台看板 | 代码完成，**未验证**（她两次都没调，凭上下文答了） | `dsh_look` / `_board_text` |
| `dsh_fork()` —— 分支副本 | 代码完成，**未验证**；桥接端点已用 HTTP 直调实测可用 | `dsh_fork` |
| 工作台台账 `workbench.json` | **已落地并实测记账正常** | `_workbench` / `_remember`，文件在 `data/plugin_data/astrbot_plugin_nanxi_dsh/` |
| 干完自动回家（`nx_dsh`） | 代码完成，**未验证** | `_go_home` / `_home_board` |
| 黑白名单（项目 + 会话） | 代码完成，**未验证** | `_board_denied` / `_session_denied` + `_conf_schema.json` |
| 进度播报去重（同名 30 秒一次） | **已修**（实测被刷屏后） | `_run_turn` 里的 `last_tool` |
| 默认会话**有工作区归属** | ⚠️ **手动做的**（`im-71cd32d5`），**代码里没有"首次自动确保"** | — |

**台账现状**（`data/plugin_data/astrbot_plugin_nanxi_dsh/workbench.json`）：

```json
{
  "onebot-qq:GroupMessage:<TEST_GROUP_ID>": {
    "__home__": "im-71cd32d5-513d-4e34-a0cb-b1631fb495fa",
    "D:\\dsh\\mas": "im-efee02cf-561a-4b3e-b764-75662adfe994"
  }
}
```

---

## 3. 待办

### P0 —— 不做完这套就是半成品

1. **端到端验证四条路径**。⚠️ **只用轻量任务**（`<PROJECT_ROOT>` 下的小目录），
   **别再拿 `mas` 当靶子**（见第 5 节坑 3）：
   - 看板：`dsh_look` 真的被调用（问法要绕开上下文里已有的答案）
   - 项目内复用：第二次说"mas 那个" → 回到**同一间**会话（不是新开）
   - 跨项目出差 + 自动回家：群里出现 `· 换到 …` / `· 回到 …`，且 `/where` 回到 `im-71cd32d5`
   - 分支：`dsh_fork` 之后子会话**归到同一工作区**（原理已用 HTTP 直调验证：
     源会话有 workspaceId 时，fork 的返回里就带 workspaceId）
2. **首次自动确保默认会话有归属**：写 `_ensure_home()` ——
   当 conversation 还没有 mapping 时，**先自己 `rebind` 到默认工作区**建一间有归属的，
   别让 `/message` 裸建（裸建出来的没有 workspaceId，之后 fork 的副本**全部落在「未分组」**）。
   原理见第 4 节的 fork 归组规则。
3. **黑白名单实测**：临时禁掉一个工作区 / 一个会话，确认她**看不见也去不了**。
4. **源码同步 + git 存档**：改 `astrbot\data\plugins\` 下的部署副本后，
   记得拷回 `astrbot_plugin_nanxi_dsh\`（`astrbot\` 整个目录被 gitignore，副本不进库）。

### P1 —— 隔离 ✅ **已完成（2026-10-04）**

5. ✅ **独立 DSH 实例已落地**：见 §4.5（含两处新踩的坑）。
6. ✅ AstrBot 侧两个插件（`astrbot_plugin_nanxi_dsh` 与星驿 `astrbot_plugin_dsh_relay`）
   的 `bridge_url` 已切到 `http://127.0.0.1:3081/astrbot-relay`；
   备份在 `_backup\20261004\*.bak-before-3081`。**改完要重启 AstrBot**。

### P2 —— 可选

7. `dsh-instance-manager`：多实例管理面板（侧边栏看/启停）+ agent 工具
   （`instance_list` / `start` / `stop` / `logs` / `sessions`）。
8. `dsh-interconnect`：两个实例互通（`interconnect_send` / `list` / `ping` / `reply`）。

### 老账（一直悬着，别忘）

9. **审批链路仍未实测**：要把 DSH 的 approval policy 从 `never` 切回 `ask`，
   才能验"DSH 请求提权 → 南汐转述 → **仅主人可批**"这条路。
   当前工具里对 `approval/required` 的处理是"转述 + 说明这条链路暂不支持远程批准"。
10. `dsh-find-plugin@0.3.7` 与 dsh 0.2.0-rc.2 不兼容（启动时被静默跳过），可选处理。

---

## 4. 多实例方案（调研结论，**代码未实施**）

### 4.1 官方事实（子代理逐条核对了本地 0.2.0-rc.2 随包文档）

- **官方文档里没有"多实例"这一节**，没有推荐方式，也没声明任何隔离边界。
- CLI 只有：`dsh [--profile] <name>`、`--from-default-profile <name>`、`dsh web --port <n> --no-open`。
- `--from-default-profile` **只从 5 个内置模板复制 `dsh.profile.bundles` 列表**；
  新 profile 的 `dependencies: {}`、`cordis.patch.yml` 为空 `[]`；
  **不读**本地同名 profile、**不复制**它的依赖与 patch。目标目录必须不存在（独占 mkdir）。
- **凭据 / sessions / storages / settings 都不在 profile 里** ⇒ 同一个 `$DSH_HOME` 下是**共用根**，不是继承。
- **共享 `$DSH_HOME` 的真实冲突面**：

  | 目录 | 跨进程写锁 | 结论 |
  |---|---|---|
  | `sessions/` | ✅ **有**（POSIX `flock`；Windows 用该路径派生的**命名内核信号量**） | 不同会话并发安全；同一会话的第二个写者被**排除（失败）而非交错** |
  | **`storages/`** | ❌ **官方原文：「没有跨进程写锁，两进程写同一单元可能交错替换，最后完成者胜」** | **唯一的真坑**（`workspace.json`、`session_projcache/`、`cost-meter/ledger.json`） |
  | `.credentials.yaml` | ✅ 有 `<file>.lock` | 不丢他人条目 |

- 端口必须不同：`EADDRINUSE` 会让 webserver 插件初始化失败，而它属于 required ⇒ **该实例启动终止**。
- `headless` profile 不开监听端口，与 web 实例无端口冲突。

> ⚠️ **fork 归组规则（2026-10-04 读 DSH 侧插件源码 + 实测确认）**：
> `dsh-astrbot-relay/lib/index.js:2744` 里 `forkWorkspace` 的等价物是
> `registry.list().find(e => e.sessionIds.includes(sessionId))` ——
> **只把子会话挂到「源会话所在的工作区」**。源会话没有归属（星驿用 cwd 建的），子会话就也不挂。
> 实测：`rebind` 建的会话有归组，从它 fork 出来的副本**也带 `workspaceId`** ✓

### 4.2 推荐的三层方案

```
① 隔离（必做，解决卡死）
   独立 HOME：<NANXI_DSH_HOME>        端口 3081
   ├─ 复制 .credentials.yaml         （签名密钥）
   ├─ 复制 storages/workspace.json   （8 个工作区，省得重新注册）
   ├─ sessions/ 用 junction 指向主 ~/.dsh/sessions   ← 会话互通可见，且有跨进程锁保护
   └─ storages/ 独立                  ← 避开"无锁、最后写入者胜"
   AstrBot 侧：两个插件的 bridge_url 都指 http://127.0.0.1:3081/astrbot-relay

② 管理（可选，很便宜）
   dsh-instance-manager —— 侧边栏统一看/启停所有实例；还带 agent 工具

③ 互通（可选）
   dsh-interconnect —— 两个实例互相 send/list，装完 hmr 秒级生效、不用重启
```

### 4.3 互通插件对比（**全部社区作品，一个都没实测**）

| 插件 | ★ | 通信模型 | 额外依赖 | 备注 |
|---|---|---|---|---|
| [dsh-interconnect](https://github.com/Chinesezjc/dsh-interconnect) | 35 | 持久 **WebSocket** + 共享 token（`DSH_INTERCONNECT_TOKEN`） | **不需要额外进程**（host 插件自带服务） | **最对口**：README 明说支持"另一台机器上的别的 DSH 实例"；`peers: {peer-a: http://127.0.0.1:13080}`；已实测跨机双向互通 |
| [dsh-agent-relay](https://github.com/Noelune/dsh-agent-relay) | 3 | 常驻 **HTTP Broker**(19121) + HMAC + 租约 | 要单独跑 broker + 密钥环 | 重；README 只测到 dsh **0.1.0-rc.6** |
| [dsh-ask-peer](https://github.com/zzhzz/dsh-ask-peer) | 8 | P2P，签名 Friend Card 发现 | 无 broker | 版本/重启要求**未验证** |
| [dsh-agent-teams](https://github.com/NanmiCoder/dsh-agent-teams) | 1907 | **单进程内**的子代理团队 | 无 | ⚠️ README 自述"并发进程编辑同一 team 不被协调"⇒ **不解决多实例** |

**`dsh-interconnect` 的关键工具**（这三条正中我们的需求）：

- `interconnect_list(instanceId)` —— **列出对端 live session（id + 标题 + 状态）**
- `interconnect_send(instanceId, sessionId, text, resume?, delivery?)` ——
  `delivery` 三档：`followup`（排队独立一轮）/ `steer`（插进当前轮）/ `inject`（只写上下文不唤醒）
- `interconnect_reply(text)` —— 回信，只需文本

⚠️ `resume=true` 会**唤醒离线 session 并起一次计费回合**，默认关闭是故意的。

### 4.4 待主人拍板

- 做到哪一层（① / ①+② / ①+②+③）
- `sessions/` 要不要 junction 共享（共享 = 主 Web UI 里能看见南汐在忙什么）

---

## 5. 踩坑存档（血泪，按疼的程度排）

1. **`Start-Process` 起的 AstrBot 是 DSH 的子进程** —— DSH 一重启，AstrBot 被**连带杀死**
   （2026-10-04 实测：6185 / 3002 全没，日志只剩一句 "dsh web: http://…"）。
   ⇒ **必须让主人双击 `启动\一键启动.bat`**，别在 DSH 会话里代起常驻服务。
2. **南汐的任务和主项目跑在同一个 DSH 进程**，共用事件循环 ⇒ 重任务会互相拖垮。
   这是要做多实例的**根本原因**。
3. **测试别用重任务**：拿 `<WORKSPACE_MAS>`（AUTO-MAS，带 `.git` 的大项目）当靶子，
   44 秒把 DSH 拖到无响应、主人只能重启。
   ⇒ 验证一律用 `<PROJECT_ROOT>` 下的小目录，或纯只读的元数据操作。
4. **AstrBot 写插件配置带 BOM**（`EF BB BF`）—— PowerShell 的
   `[IO.File]::ReadAllBytes` + `ConvertFrom-Json` 会报 "Unexpected character at position 0"。
   解法：`(Get-Content $p -Raw -Encoding UTF8) -replace "^\uFEFF", "" | ConvertFrom-Json`。
5. **模型会"学着演"上下文里出现过的话**（详见 AGENTS.md 坑 3）；
   它**还默认爱反问、不爱动手** —— 工具描述必须写成命令式
   （"直接调用它去看，不要反问主人，也不要凭记忆猜"）。
6. **工具描述是弱注意力区**：关键行为要**同时**写进 `req.system_prompt`
   （本插件的 `watch_request` 钩子就在干这个）。
7. **进度播报会刷屏**：DSH 连着调十几次同名工具（翻目录、逐个读文件），
   每条都发会把群刷爆 ⇒ 同名工具 **30 秒内只报一次**。
8. **`/reset` 在本机不生效**：`provider_settings.wake_prefix` 是空串，内置命令判的是
   `message_str == "reset"`（**不能带斜杠**）；而发裸 `reset` 会被"需要 admin"挡掉。
   清上下文最省事的办法是直接清 `data_v4.db` 里该会话的 `conversations.content`。

---

## 6. 下一步

等主人拍板第 4.4 节的两件事，然后按"**先备份 → 再动手 → 每步验证**"开工。
P0 那四条验证不用等，随时可以做（纯群内测试，风险低）。
---

## 7. P0 验收记录（2026-10-04 下午）

在**独立实例（3081）+ 清过上下文**的环境下逐条验，结果如下：

| 项 | 结果 | 证据 |
|---|---|---|
| `_ensure_home`（开工前建家） | ✅ **通过** | 开工前会话是孤儿 `im-f230637e`（无归属）；一条 `dsh_task` 之后变成 `im-e551b7aa`，**归属 ✅ nx_dsh** |
| 跨项目出差 + 自动回家 | ✅ **通过** | 群里出现 `· 换到 QQbot（新开了一间会话）`，干完后 `/where` 回到 `nx_dsh` 的家 |
| 干活准确性 | ✅ **通过** | 让她数 `<PROJECT_ROOT>\nx_dsh` 的文件：答"两个"，人工核对确实是 `AGENTS.md` + `mas会话.json` |
| `dsh_look` 被调用 | ✅ **通过**（有瑕疵） | 日志 `Agent 使用工具: ['dsh_look']`，答案 8 个工作区 + 当前归属**完全正确** |
| **配置改文件即生效** | ✅ **通过** | 把测试小号从 `owner_qq` 移出、**不重启 AstrBot**，下一次调用立刻 `非主人（<TEST_BOT_QQ>）…已拒绝` |
| 黑白名单 | ⚠️ **未测到** | 代码路径正确（`_board_denied` → `continue`，连名字都不给她看），但两次测试都因为**她凭上下文记忆作答、根本没去看板**而绕过，测不出来 |

### 已知瑕疵（不阻塞，记着）

1. **问了看板，她还会再跑一趟 `dsh_task`** —— 同一轮里 `dsh_look` 和 `dsh_task` 都调了。
   答案是对的，代价是多花几十秒 + 群里刷几条 `· DSH 正在用 xxx`。
   已经试过两轮强化（工具描述 + system prompt 里的"两条硬规矩"），**压不住**。
   下一步可考虑代码兜底（同一轮里 `dsh_look` 之后短时间内的 `dsh_task` 直接回看板文本）。
2. **`at` 会被乱填** —— 任务文字里出现项目名/路径时，模型倾向于把它填进 `at`。
   system prompt 里那条硬规矩**生效了**（复测时 `at=-`），但需要继续观察。
3. **模型会"凭记忆答"** —— 上下文里有过答案时，她倾向于直接背，不去调只读工具。
   这不是 bug，但会让"她到底查没查"变得难以判断，**验收时要注意**。

### 运维补充（本轮新学到的）

- **重启 AstrBot 可以让 agent 做**，但**不要用嵌套的 `powershell -File <脚本>`** ——
  外层 PowerShell 会因为子进程持有 stdout 管道而**一直挂住**（实测两次都卡到超时）。
  正确做法是**在一条命令里直接** `taskkill` 再 `Start-Process`，**不套脚本、不做嵌套**。
- ⚠️ 从 DSH 会话里 `Start-Process` 起的进程**挂在这条会话的进程树上**：
  实测 `job_kill` 掉自己的后台任务时，**AstrBot 被一起带走了**。DSH 重启同理。
  要真正常驻，仍以双击 `启动\一键启动.bat` 为准。
- **Windows 端口存活判定只看 LISTENING**：`netstat` 里含 `:<port>` 的行大多是 `TIME_WAIT`
  残留（2~4 分钟自消），按"行数 > 0"判占用会误报（`start-nanxi-dsh.ps1` 踩过）。
### 7.1 补测（2026-10-04 傍晚）

| 项 | 结果 | 证据 |
|---|---|---|
| **`dsh_fork`** | ✅ **通过** | 日志 `Agent 使用工具: ['dsh_fork']`；群里 `· 分了一间副本出来（im-da772425…，继承了 336 条上下文）`；副本**归在 `nx_dsh`**（fork 继承源会话的工作区）；干完 `_go_home` 把线拉回原家 —— 符合"副本不动原会话"的设计 |
| **黑白名单** | ✅ **通过** | 把 `android` 加进 `workspace_deny`（**不重启**），逼她"去 android 看看"：她先调 `dsh_look`，然后回"工作台上压根就没有一个叫 android 的"，并列出其余 **7** 张台子（正常 8 张）—— 连名字都看不到 |

### 7.2 ⚠️ 新踩的坑（很重要）

**人格的 `tools` 白名单必须显式列出每一个工具。** 本机实测：`personas.tools = '["dsh_task"]'` 时，
**`dsh_look` / `dsh_fork` 根本没被下发给模型** —— 表现是"模型死活不用那个工具"，
而工具描述写得再清楚也没用（它压根看不见）。

已改成 `["dsh_task", "dsh_look", "dsh_fork"]`（备份 `_backup\20261004\data_v4.db.bak-before-persona-tools-3`）。

⇒ **以后每加一个新工具，都要记得同步这个白名单**，否则新工具等于不存在。
（`watch_request` 只会检查 `dsh_task` 在不在，不会检查另外两个。）
---

## 8. ✅ 让她真的「自己挑工位」（2026-10-04 晚，已实测）

### 8.1 她之前为什么不挑

不是懒，是**她根本不知道有哪些项目可选**。`dsh_task` 的 `at` 留空是"安全默认"，
而要主动填，前提是知道有什么可填 —— 可那份清单只有 `dsh_look` 能看到，她不调。

### 8.2 改了两处

1. **工作区清单常态化注入 system prompt**（新增 `_workspace_digest()`，缓存 60 秒）：
   每轮请求都带上一句
   `【当前工作区】QQbot（…）、nx_dsh（…最近在忙《…》）、mas（<WORKSPACE_MAS>，最近在忙《…》）…`，
   并明确"判断属于哪个项目就填进 at，**不要一律留空窝在默认工位**"。
2. **会话索引改成多 HOME 查找**（`_dsh_homes()`）：南汐跑在独立实例里，自己的缓存只有
   11 间会话，而 mas 那 27 间的标题只存在**主 HOME** 的缓存里（85 间）—— 两边都查才看得全。
   配置 `dsh_home` 支持 `;` 分隔多个路径，主用户的 `~/.dsh` 永远补在末尾。

### 8.3 实测结果

| 提问 | 她做了什么 |
|---|---|
| 「mas 那边最近在忙什么？」 | 调 `dsh_look`，答出 mas 的**具体**在忙什么（《星塔旅人》等三间）—— 修多 HOME 前她只能说"只报了 27 间" |
| 「去 xtlr 那个项目里看看根目录有几个文件」 | **自己填 `at=xtlr`** → 群里 `· 换到 xtlr（新开了一间会话）` → 一张 `[forward]` 卡片 → 收尾 → **`/where` 回到原来的家** |

⇒ 出差、干活、回家全自动，**没人告诉她该去哪个工位**。这是最初那条诉求（"我像项目经理，
她自己判断去找会话、或者判断是否要新建"）**第一次真正跑通**。
### 8.4 补测：会话复用 + 她是否知道会话在干嘛

| 项 | 结果 | 证据 |
|---|---|---|
| **复用会话** | ✅ 通过 | 第二次「xtlr 那间会话里，上回看的那个根目录有几个文件夹？」→ 群里 `· 回到 《…》（<DSH_WORKSPACES>\xtlr）`，**是「回到」不是「新开」**；台账 `<DSH_WORKSPACES>\xtlr` 仍指向同一间 `im-49905ce9` |
| **知道会话在干嘛** | ✅ 通过 | 第二轮她给 DSH 写的任务描述是「**刚才看过** <DSH_WORKSPACES>\xtlr 的根目录……现在请只回答有几个文件夹」——**DSH 自己说出了"刚才看过"**，说明复用同一间会话让**上下文真的连续** |

台账现状（四个项目各一间、互不串台）：

```json
"onebot-qq:GroupMessage:<TEST_GROUP_ID>": {
  "__home__": "im-e551b7aa…",
  "D:\\dsh\\mas":            "im-efee02cf…",
  "D:\\dsh\\QQbot":          "im-b9bea3ac…",
  "D:\\dsh\\QQbot\\nx_dsh":  "im-da772425…",
  "D:\\dsh\\xtlr":           "im-49905ce9…"
}
```

⇒ 复用带来的不只是省一次交代背景，而是**她真的记得那个项目里发生过什么**。
---

## 9. ⚠️ 一次"南汐卡住了"的完整事故与修复（2026-10-04 傍晚）

### 现象
主人在群里说「mas项目下有个叫baah的会话，你看看」，南汐切到 mas 后回了句
"链路半路断掉了"，之后**整个群会话卡死**：再问什么都不动。

### 因果链（逐条有日志）
```
16:39:49  南汐 at=mas，去查 baah 会话
16:40:45  ⚠️ DSH 链路中断：Timeout on reading data from socket
16:40:45  ⚠️ 回家失败：HTTP 409：该会话有投递或附…
```
`/health` 的 `pending` 把卡点暴露得很清楚：
```json
{"conversation":"onebot-qq:GroupMessage:<TEST_GROUP_ID>",
 "attaching":true, "queue":1, "approvals":0, "questions":0, "stuckAt":0}
```

**根因**：插件里 `_SSE_SOCK_READ_SECONDS = 45.0`（我当时按"心跳 15 秒 × 3"定的）。
DSH 去翻那个会话时 45 秒没吐字 ⇒ 客户端判超时、撒手走人。
但**服务端那次投递并不会因为客户端走了被取消** ⇒ 该会话永久停在 `attaching`
⇒ 之后所有 `adopt` / `rebind` 都被 **409「该会话有投递或附件」** 拒掉
⇒ 她既回不了家，也接不了新活。

### 处置
1. **解卡**：重启 nanxi 实例（`pending` 清空），再 `adopt` 把她拉回台账里的家。
2. **修根因**：45 秒 → **180 秒**，并做成配置项 `sse_read_timeout`；
   在代码注释里写明"别再调回 45 秒"以及连带后果。
3. **复测**：同一条原话重跑，**完整跑通**（`· 回到 im-efee02cf` → `[forward]` → 收尾），无超时无 409。

### 教训
- **心跳（heartbeatMs=15000）不等于内容**：模型想事情慢是常态，SSE 读超时不能按心跳的倍数拍脑袋。
- **超时的代价不对称**：客户端超时只是这一次调用失败，**但服务端会留下一个卡死的会话**，
  要人去重启实例才能解开。所以这个值宁可大。
- 排查这类"卡住"最快的一招：`GET /astrbot-relay/health` 看 `pending[].attaching`。

---

## 10. 外部项目调研结论（2026-10-04，均为只读调研）

### 10.1 `dsh-memory`（灵枢 LINGSHU）
- **是什么**：跨 harness 的**长期记忆系统**（标准 stdio MCP server），对话沉淀成**纯文本 md 认知图**，
  确定性规则决定记什么取什么，全可审计。自称"白箱 AGI 架构探索"，实质是记忆基础设施。
- **规模**：316★ / 1967 commits / 最后提交 9 分钟前 / 286 套 Python 测试 + 99 npm 用例，工程纪律罕见地高。
- **风险**：① 它写"已验证至 DSH 0.17.2"，本机是 **0.2.0-rc.2**（满足它写的下限，但**未实测**）；
  ② 本机**没有 Rust 工具链**（它有 Rust 检索内核）；③ 与本机已装的 `dsh-memory-evolve` **功能重叠**，
  两套都往 prompt 注入可能打架；④ 它说配置写 `cordis.yml`，而 DSH 惯例是 `cordis.patch.yml`。
- **对南汐价值有限**：她的会话本身就是长期连续的（实测第二轮回同一项目时 DSH 会说"刚才看过"），
  "跨会话记忆"的主要卖点对她不成立。

### 10.2 `MaiBot`（麦麦 / MaiSaka）
- **定位（官方原话）**：**"群聊里的数字生命"**，明确写"不追求完美、不追求高效，但追求亲切和真实"——
  **不是执行型助手**，与我们"AstrBot 大脑 + DSH 执行代理"是两条产品线。
- **规模**：6104★ / 643 fork / ~121 贡献者 / 7479 commits / GPL-3.0 / 最新 1.3.2（10-03）/ 约 3~4 版每月。
  Python 3.12+ / FastAPI / SQLite（22 表，无独立 DB）；插件跑**隔离子进程**（msgpack RPC）。
- **它有的**：官方插件市场 **391 个模块**、内核级 `@Tool`（等价 `@filter.llm_tool`）、
  **内置 MCP 客户端**（stdio/http/sse）、A-Memorix 长期记忆 + 人格画像、发言时机/频率/学黑话。
- **它没有的**：**没有 DSH 那种文件/终端执行能力**（工具面偏知识库/表情/渲染/搜索/MCP）。
- **接入方式差异（关键）**：MaiBot 不内置适配器，自己开**自研 WS 消息服务器**；
  **OneBot 只出现在"适配器 ↔ QQ端"那一跳**。官方维护 **SnowLuma 适配器**（1.3.0 起已合并 NapCat 适配器），
  但它连的是 SnowLuma 的**正向 WS**，而我们现在是**反向 WS 上报给 AstrBot** ⇒ 要接得另开一个正向 WS 端口。
- **结论：不必整体迁移**。迁移要重接协议 + 重写全部 AstrBot 侧资产（`nanxi_dsh`、星驿 AstrBot 半边、
  petpet、转发卡片补丁、`nanxi-test.ps1` 验收链、游戏通知的 `im/messages` 通道），
  且**没查到**等价于 `POST /api/v1/im/messages` 的外部主动发送 API（游戏通知的命脉）。
- **值得借鉴三块**：① **A-Memorix 长期记忆 + 人格画像**（我们这边最弱的一块）；
  ② **发言时机 / 频率 / 必要性回复**（南汐现在是"被叫到才回"，这是产品级差距）；
  ③ **插件子进程隔离 + Host/Runner RPC**（我们踩过插件刷屏把进程内存拉到 2GB）。

### 10.3 两家调研的共同指向
两个项目**都在解决"记忆"**，而"记得住人、记得住事"恰恰是南汐目前最薄弱的一环。
若要做，可借鉴的是**设计**（记忆生命周期/画像冲突替换/情景记忆），而不是直接搬代码——
它们分别是 MaiBot 插件与独立 MCP 服务，都不能原样装进 AstrBot。
---

## 11. 南汐 · 观察页（思维链可视化，2026-10-04 晚 完成）

### 11.1 它是什么
插件自带的一个**只读** WebUI 页面（`pages/trace/index.html`），把南汐干活的全过程
按顺序摊开：**她的决定 → 交给 DSH → 每一次工具调用 → 收工**。
打开路径：AstrBot WebUI（6185）→ 插件 → **南汐 · 观察**。

### 11.2 地基是抄 MaiBot「麦麦观察」的，三条纪律照守
调研发现那套系统的地基不是"展示模型思维链"，而是**「推理过程事件账本 + 实时卡片时间线」**。
抄过来的三招（业务无关，通用）：

1. **单调自增 `event_id` 的事件账本**（`trace.db` 的 `trace_events` 表）——
   断线/刷新/重启都不丢，前端拿 `event_id` 当游标补发。
2. **按 `event_id` 排序，绝不按时间戳** —— 同毫秒内多件事很常见，时间戳会错位。
3. **卡片身份 = `turn`** —— 同一轮的所有事件共用它，前端**原位刷新同一张卡**。
   实测一次任务的 5 条事件（`decision`/`dsh/start`/`dsh/tool`×2/`dsh/end`）共用
   `turn=df10eb3944`，页面上是**一张卡**而不是五张。

### 11.3 实现要点（AstrBot 侧的三个坑）
- **插件能自带网页**：`pages/<name>/index.html` + `metadata.yaml` 里声明
  `pages: [{name, title, entry_file}]`，AstrBot 的 WebUI 自动列出。
- **插件能注册 HTTP 路由**：`context.register_web_api(route, handler, methods, desc)`，
  挂在 `/api/plugins/extensions/<插件名>/<route>` 下；**同源 iframe 自带登录 cookie**，
  所以不用另做鉴权（实测未登录访问返回 401，正符合预期）。
- ⚠️ **handler 只收路径参数**（`view_handler(**path_values)`），**拿不到 query string** ——
  所以游标走**路径**（`/trace/0`、`/trace/1234`）而不是 `?since=`。
  路由支持 `<name>` 占位（单段）与 `<path:name>`（多段）。
- **不做 SSE 改用轮询**（1.5 秒）：插件 API 返回普通 JSON（`Callable[..., Awaitable[Any]]`），
  要吐 SSE 得绕到 ASGI 层，第一版不值得。

### 11.4 界面
**配色抄 SnowLuma**（用户指定）：直接从它的 `client/assets/index-*.css` 里取的变量 ——
Tailwind v4 + oklch，中性色带蓝调（hue 240–250），主色 **sky `#0ea5e9`**，
圆角 `.75rem`/`1rem`，卡片 + 细边框 + `backdrop-blur`，跟随 `.dark` 双主题。
布局：左侧垂直时间线，右侧「当前状态 / 工作台」两块常驻面板。
工具卡**同名合并计数**（`pwsh ×3`）—— 一次任务常把同一个工具调十几次，堆十几行没法看。

### 11.5 数据与安全
- 独立小 SQLite：`data/plugin_data/astrbot_plugin_nanxi_dsh/trace.db`（WAL），
  **与 AstrBot 主库无关**，删掉只丢观察记录。
- 保留策略照它：**10000 条 / 72 小时**。
- 埋点是**尽力而为**的：写失败只打 debug 日志，绝不拖垮正在跑的任务。
- 页面**只读**，不改任何行为；黑名单里的项目在面板上也看不见。
---

## 12. ⚠️ 观察页在 WebUI(iframe) 里空白 —— 完整事故与修复（2026-10-04 深夜）

### 12.1 症状
直接开 `/api/plugin/page/content/<插件>/trace/index.html` **一切正常**；
但从 AstrBot 仪表盘的「插件页面 → 南汐 · 自主调用 DSH」进去（即 iframe 内）**永远空白**：
"游标 0" + 右侧"读取中…"。

### 12.2 根因（四层，逐层剥出来的）
1. **AstrBot 给插件页 iframe 的 sandbox 是 `allow-scripts allow-forms allow-downloads`
   —— 故意不给 `allow-same-origin`** ⇒ iframe 的 origin 是 `null`：
   - **`localStorage` 一碰就抛 `SecurityError`** ⇒ 脚本在开头就死了 ⇒ `poll` 从未执行
     （表现：永远"游标 0"）。**这条最先修**：包一层 try/catch，不通就退回内存。
   - **`fetch("/api/...")` 变成跨源** ⇒ 不带 cookie、又没有可用的 CORS 语义 ⇒ 请求**挂起**
     （表现：右侧永远"读取中…"）。
2. **`bridge-sdk.js` 在 iframe 里加载失败**（`<script src>` 的 `onerror` 触发）。
   它和页面同样在 `PluginPageAuth.is_protected_path` 里、要 `asset_token`；
   静态 `<script src>` 不带 token ⇒ 401。改成动态注入并带上 token 后**仍然 error**，
   而 CORS/CORP 查过都是放开的（`access-control-allow-origin: *`、
   `cross-origin-resource-policy: cross-origin`）、CSP 也不限制脚本
   （只有 `frame-ancestors/object-src/base-uri`）—— 原因未定，但**不影响修复**（见下）。
3. **正解：手写那套 bridge 协议**（不加载脚本）。协议就在
   `astrbot/dashboard/plugin_page_bridge.js`：`channel="astrbot-plugin-page"` +
   `{kind:"request", requestId, action, ...}` → 父页面回 `{kind:"response", requestId, ok, data|error}`。
   父页面侧的处理在 `astrbot/data/dist/assets/PluginPagePage-*.js`，
   **它明确接受 `origin === "null"`**（`e.origin!==Z && e.origin!=="null"` 才拒），
   但要求 **`e.source` 必须是它持 ref 的那个 iframe 的 contentWindow**。
4. **`endpoint` 必须是相对的**（`"state"` / `"trace/0"`）。父页面自己会拼
   `/api/v1/plugins/extensions/<pluginName>/<endpoint>`（见它的 `te()`/`B()`）；
   把完整路径传进去会拼成 `.../astrbot_plugin_nanxi_dsh/api/v1/plugins/...` ⇒ 404 ⇒ 父页面回 error
   ⇒ 页面显示"连接失败"。

### 12.3 另一个坑：SPA 路由切换**不会重建 iframe**
改完 `index.html` 后光刷新路由（`#/plugin-page/...`）看到的还是**旧页面实例** ——
Vue 复用了组件、没重设 `iframe.src`。**必须整页 `reload()`** 才会加载新 HTML。
排查时差点因此误判成"AstrBot 缓存了 HTML"。

### 12.4 现在
- **iframe 内**：走手写 bridge（`bridgeCall`），父页面代发；轮询正常，数据实时。
- **直接开页面 URL**：走 `fetch`（此时没有 sandbox，同源正常）。
- 页面里保留了一套 `__nanxiDiag` 诊断上报（默认开，`?diag=0` 可关）：
  它**不是** bridge 的 channel，宿主会忽略，留着方便下次排查。
---

## 13. 支持「点名到具体会话」（2026-10-04 深夜，主人指出）

### 13.1 主人指出的问题
「mas 工作区下这些会话我都能看到（星塔旅人 / 南汐 mas / 活动卡片 / **baah** / debug…），
**为什么不能用**？」—— 主人让她「改一下 **baah** 的计划表」，她进的却**不是 baah**。

### 13.2 根因：台账把「每个工作区」锁死到**一间**
`_goto` 只按**工作区路径**认人：`workbench.json` 里 `<WORKSPACE_MAS>` 记着**第一次去时**用的那间，
之后永远复用它。于是同一个工作区下的十几间会话她**既看不到、也指不到**。

实测（`/workspaces` + 会话索引）在 mas 的 27 间里能读出标题的 17 间，其中：

```
《星驿 · onebot-qq/GroupMessage/<TEST_GROUP_ID>》 im-efee02cf…   ← 她一直用的就是这间
《skill》《baah》session-4a0b8eb7-…《新的起点》《主界面刷新》
《配置移动功能》《活动卡片》《星塔旅人》《debug-skill》《debug》《QQbot》《南汐mas》
```

**也就是说：她在 mas 里用的那间，其实是星驿替她的群会话建的那间，她从来没进过
mas 真正的项目会话。** 这正是主人说的「只用自己的、不用原本自带的」。

### 13.3 改法
1. 新增 `_find_session_by_name(boards, key)`：按**会话标题**在所有未拉黑工作区里找，
   支持 `工作区/会话名`（如 `mas/baah`）与裸 `会话名`（全局找，**命中唯一**才认）。
2. `_goto` 的「工作区认不出来」分支里先试会话名，再退到会话 id。
   —— 顺序刻意如此：**先工作区后会话名**，否则 `at=mas` 会被某个标题含 mas 的会话
   （比如《南汐mas》）抢走。
3. `_board_text`（`dsh_look` 的输出）现在**把每一区的具体会话名也列出来**
   （每区最多 8 个，并提示「要点名某一间，把 at 写成『工作区/会话名』」），
   否则她只知道"有 27 间"、对不上主人说的名字。

### 13.4 验证
用 `/workspaces` + 会话索引复算：mas 下含 `baah` 的会话**恰好 1 间**
（`session-4a0b8eb7-4d54-4136-bb77-4ec110a841aa`）⇒ 新逻辑下 `at=mas/baah` 会命中。

> ⚠️ 当时**没能跑群内端到端测试**：SnowLuma 容器重启过，测试小号的第二实例不会自动起
> （已知现象），`tools\nanxi-test.ps1` 直接报 `docker exec curl failed`。
> 要恢复得跑 `启动\恢复测试bot.ps1`（若小号停在扫码界面还需主人扫码）。
