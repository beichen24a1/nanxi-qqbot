# 阶段 1 深化：DSH 桥接工程化改造计划

> 生成日期：2026-09-18 ｜ 状态：**待主人确认后开工**
> 上游文档：`AGENTS.md`、`南汐自主智能体-目标与路线图.md`
> 本文档记录：缘起 → 事实核实 → 差距分析 → 任务分解 → 验证清单 → 风险

---

## 一、缘起

群友给了一份「AstrBot ↔ DSH 桥接」的五层架构思路（触发层 / 会话映射层 / 传输层 / Agent 执行层 / 输出格式化层）。经核实，该思路**基本正确**，且其来源是一个真实存在的开源实现。本文档把它落成可执行计划。

### 1.1 核实结论（重要，含对思路的修正）

| 群友说法 | 核实结果 |
|---|---|
| 参考 `dsh-qqbot-bridge` 的做法 | ✅ **项目真实存在**（有**两个同名仓库**，见 §2.1）。此前一度误判为"不存在"，已纠正 |
| 一次性验证码审批、只接受相同 peer+sender、超时/卸载 fail-closed | ✅ **逐字对应** `wang-22-code` 的 `docs/ARCHITECTURE.md` 审批 6 步 |
| 会话映射需持久化（建议 SQLite/JSON 三元组表） | ⚠️ **概念对、实现说复杂了**：真实做法是 **`sessionKey` → SHA-256 → 确定性 SessionId**，不建表 |
| 节流 2.5 秒 | ⚠️ 数值不准：实际 `streamFlushIntervalMs` **2000ms**（wang-22-code）/ `stream_throttle_ms` **1000ms**（Jiangsubei） |
| 推荐 HTTP + SSE | ✅ **成立**（此前我方误判为"绕远路"）：DSH 官方客户端 `AbstractApiClient` 默认实现就是 **SSE**（`lib/types/fetch/client.d.ts:163 readSse`）。我们的 Node 客户端改用 WS（`/api/events.mux`）是**等价替代**，已验证可用 |
| 信标文件 `~/.dsh/xxx-ingress.json` 自动发现端口和 Token | ❌ **不成立**：本机 `~/.dsh` 全递归无任何 ingress 文件；两个参考仓库也无此机制。同机回环访问 DSH **无需任何 Token** |
| DSH 插件分宿主侧 + 客户端侧两半 | ✅ 成立（Jiangsubei 有 `dist/client.js` + WebUI 设置卡片） |
| `ctx.effect()` 包裹资源、卸载自动清理 | ✅ 成立（Cordis 插件生命周期） |

### 1.2 关键认知修正

参考实现是 **DSH 进程内 Cordis 插件**（直接 `ctx.agents` / `ctx.workspaceRegistry`），我们的 `/dsh` 是 **外部 HTTP 客户端**（`dsh_cli.js` → `127.0.0.1:3080`）。一度担心"进程内才能做的事在 HTTP 上做不了" —— **经查证不成立**：所需能力在 HTTP RPC 上全部具备（见 §2.2）。

**结论：架构不必推倒重来，补齐工程层即可。**

---

## 二、事实基线（已核实，非推测）

### 2.1 参考实现

| 仓库 | 说明 |
|---|---|
| [`wang-22-code/dsh-qqbot-bridge`](https://github.com/wang-22-code/dsh-qqbot-bridge) | 3★，MIT，TypeScript。**有 `docs/ARCHITECTURE.md`**，即群友思路的来源。含 `src/session/`（确定性 id）、`src/transport/chunker.ts`、`src/approval.ts` |
| [`Jiangsubei/dsh-qqbot-bridge`](https://github.com/Jiangsubei/dsh-qqbot-bridge) | 0★，MIT，2026-09-17 发布。**远程接管 DSH 已有会话**、流式、workspace 归组、9 个中文命令、审批+提问转发 |
| [`tencent-connect/dsh-qqbot`](https://github.com/tencent-connect/dsh-qqbot) | 腾讯**官方**插件 |
| [`sliverp/DeepSeek-harness-qqbot`](https://github.com/sliverp/DeepSeek-harness-qqbot) | 腾讯官方 Bot Gateway 通道插件 |

> ⚠️ **只借鉴设计，不复制代码**：以上全部基于**腾讯官方 QQ Bot API**（AppID/AppSecret/OpenID），与我们的**个人号 + SnowLuma/OneBot 协议端**是两套不互通的认证体系。且它们**均不做人设**，我们保留「南汐转述」是差异化选择。

### 2.2 DSH HTTP API 能力清单（实测自 `dsh-host-apiproxy/lib/types/fetch/client.d.ts`）

```
sessions   : list · search · create · history · models · selectModel · rename · fork
             · prompt · attachment · updateQueue · cancel        ← 注意：无 resume
workspace  : list · create · rename · delete · insertBefore
             · insertSessionBefore · archiveSession               ← 归组能力完备
approvals  : （api/approvals.d.ts 存在）                          ← 审批可走 HTTP
questions  : （api/questions.d.ts 存在）
goals      : create · edit · pause · resume · complete · clear
subagents  : list · history · prompt · interrupt
host       : describe · pickDirectory · listDirectory · createDirectory · openPath
skills · agentPresets · llm · settings · credentials · events(mux/host)
```

**两个决定性细节**（`lib/types/api/sessions.d.ts:248-271` 原文语义）：

1. **`session.create` 支持预分配 `sessionId`**
   > *"A caller may **preallocate `sessionId`**: retries with the **same id and cwd return the same session**, while a different cwd fails with `session-conflict`."*
   → 确定性 id 重复调用**天然幂等**，**不需要 resume API**。

2. **`session.create` 的 `workspaceId` / `cwd` 二选一**
   > *"At most one of `workspaceId` / `cwd` is accepted… **Workspace creation attaches the session after publication**; an attach failure returns `workspace-attach-failed`."*
   → 现在只传 `cwd` ⇒ **会话没被 attach 到工作区** ⇒ 这正是 Web 里显示「未分组」的根因。

### 2.3 现状 vs 目标

| 层 | 现状 | 目标 | 差距 |
|---|---|---|---|
| 触发层 | `/dsh` 命令 + `on_agent_begin` 自然语言拦截 + 群白名单 + 主人鉴权 | 保持 | ✅ 已达标 |
| **会话映射层** | **每次调用无条件 `sessions.create`** ⇒ 会话无限增长、无记忆、无归属 | 确定性 id 复用 + 工作区归属 | 🔴 **P0** |
| 传输层 | WS 事件流（`/api/events.mux`），每任务起一个 node 子进程 | 保持 + 超时/重连 | ⚠️ 可用 |
| **执行层** | 只等 `turn/end` 取终态；**忽略 `assistant/chunk`** | 流式进度 + 审批 | 🔴 **P0 / P1** |
| **输出格式化层** | 南汐转述后**一整条**发出，无切分 | 按 Markdown 边界切分 | 🔴 **P1** |

---

## 三、目标与非目标

### 目标
- 让 `/dsh` 成为**有记忆、有归属、有反馈**的连续助手，而不是"一次性黑盒执行"。
- 为阶段 2（定时调度）、阶段 4（自我扩展）打地基 —— 两者都需要"能定位并复用既有会话"。

### 非目标（明确不做）
- ❌ 不改造为"DSH 进程内插件"（会破坏 AstrBot 人格/白名单/主人鉴权三层结构）。
- ❌ 不引入腾讯官方 Bot API（我们的号是个人号协议端）。
- ❌ 不做 DSH 全局沙箱模式变更 / 永久授权。
- ❌ 不实现群聊内 `/切换` `/会话` 全套命令（P2 只做最小可用子集）。

---

## 四、任务分解

### P0-1 会话复用（确定性 SessionId）　✅ 2026-09-18 已完成

**问题**：`dsh_cli.js:13` 无条件 `sessions.create({cwd})` → 每次 `/dsh` 都是新会话，无上下文记忆，DSH Web 里会话越堆越多。

**做法**（照搬参考实现的派生思路，适配我们的身份模型）：

1. 定义 sessionKey。我们的身份维度是「群 + 发起人」，不是官方的 `appId:scope:peerId`：
   ```
   nanxi:${senderId}                    # 私聊：主人一个长期会话
   nanxi:group:${groupId}:${senderId}   # 群聊：按 群+人 隔离
   ```
   > ⚠️ 验证 #2 已用 `nanxi:group:<TEST_GROUP_ID>:owner` 占用过一个会话（见 §5.3）。**实施时 key 统一加版本段**（如 `nanxi:v1:group:…`），避免与探测残留撞 id。
2. 派生确定性 id（SHA-256 → UUID 形态，与参考实现同构；**裸 UUID 已被实测接受**）：
   ```js
   const h = createHash('sha256').update(sessionKey).digest('hex');
   const sessionId = `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20,32)}`;
   ```
3. 调用改为 `sessions.create({ sessionId, workspaceId, agentPreset })` —— 同 id 同 cwd **返回同一会话**（✅ 已实测幂等）。
   > 与 P0-2 合并后**应传 `workspaceId` 而非 `cwd`**（见 P0-2）；两者混用会触发 `session-conflict`。
4. 保留逃生门：`/dsh -n <指令>`（也接受 `--new`）强制新会话（key 后拼 `:fresh:<时间戳>`）。

**涉及文件**：`dsh_cli.js`（新增 `sessionId`/`--fresh` 参数）、`astrbot_plugin_dsh/main.py`（传 sessionKey）

**验收**：连续两次 `/dsh` ⇒ DSH Web 中**只有 1 个**南汐会话且第二次能记得第一次的内容；`/dsh -new` ⇒ 生成新会话。

---

### P0-2 工作区归组（解「未分组」）　✅ 2026-09-18 已完成

**问题**：会话只带 `cwd`，未 attach 到工作区 ⇒ DSH Web 侧边栏显示「未分组」。

**做法**（已由验证 #1/#3 实测证实）：
1. `workspace.list` → 按 `path` 匹配取出 `workspaceId`（**首选，零副作用**）。实测 `<PROJECT_ROOT>` 早已注册 = `4d7facf1-b92a-41db-a873-990cf834d992`（title `QQbot`）
2. 未命中才 `workspace.create({ path })` —— **幂等**：*"Creates (or idempotently resolves) a workspace over an EXISTING directory… returns that workspace (`created: false`)"*
3. `sessions.create({ workspaceId, sessionId, agentPreset })` —— **此时不能再传 cwd**（二者互斥）；实测此法建的会话**立即出现在该工作区 `sessionIds` 首位**
4. 可选美化：`session.rename({ sessionId, title: '南汐-<群号>' })`

**涉及文件**：`dsh_cli.js`

**验收**：新会话在 DSH Web 中出现在「南汐」/「QQbot」工作区分组下，不再显示「未分组」。

**风险**：若 `workspace.create` 对已存在路径返回的 workspace 与我们预期不符 → 用 `workspace.list` 先比对 `path`。

---

### P0-3 流式进度反馈

**问题**：用户发 `/dsh` 后**最长干等 300 秒**毫无反馈（当前只发一句"南汐去办喵…"然后静默）。

**做法**（分两步走，先简后繁）：

- **步骤 A（先做，低风险）**：`dsh_cli.js` 捕获 `assistant/chunk`，按**时间窗口节流 2000ms** 把进度以 JSONL 写到 stdout；`main.py` 逐行读，每满一个窗口 `event.send` 一条简短进度（如"还在做喵…（已 45 秒）"）。
- **步骤 B（后续可选）**：把 DSH 的中间叙述流式转述到群里。

⚠️ **已知坑（必须遵守）**：`qq-bridge/src/dsh-client.js:120-124` 记载 —— `assistant/chunk` 与 `assistant/message` **内容重复**，两者都累加会导致文本翻倍（曾把「收到」发成「收到收到」）。**用于终态文本时只取 `assistant/message`；用于流式进度时才用 `chunk`。**

**涉及文件**：`dsh_cli.js`、`astrbot_plugin_dsh/main.py`

**验收**：长任务期间群里能看到至少 1 条进度提示，且最终回复**不重复**。

---

### P1-1 长回复切分

**问题**：南汐转述后的文本**一整条**发出；超长会撞 QQ 单条上限（参考值约 5000 字符）。

**做法**：移植 `chunker.ts` 的 `chunkMarkdownText(text, limit)` 逻辑（MIT，约 70 行 → 用 Python 重写，仅标准库）：
- 状态机跟踪 ``` 代码块，**不在代码块中间断开**；
- GFM 表格（`^\|.+\|$`）整块缓冲，**不在表格中间断开**；
- 优先在换行 / 空行边界切分。

**涉及文件**：`astrbot_plugin_dsh/main.py` 新增 `_chunk_markdown()`

**验收**：伪造一段 8000 字符含代码块/表格的文本，切分后**每块 ≤ 上限**且代码块/表格完整。

---

### P1-2 审批转发（先探测，后实现）

**问题**：DSH 若发起 `approval/request`（如沙箱外路径访问），headless 环境**无人应答** → 可能直接挂到 300s 超时。这是隐藏失败模式。

**步骤 A（必须先做）**：实测一次"需要审批的操作"在 headless 下的真实行为（超时？拒绝？报错？）。
- 参考：本机已存在 `~/.dsh/auto-approve` 目录 —— 需查清其语义。
**步骤 B（据 A 的结论决定）**：
- 若为 fail-closed 且不阻塞 → 可暂不实现，仅在文档标注。
- 若会挂死 → 实现最小转发：`dsh_cli.js` 捕获审批帧 → stdout 通知 → AstrBot 发带验证码的 QQ 消息 → 主人回 `/approve CODE` → 回传。
- 备选：为 QQbot 工作区配置**受限自动批准规则**（比全量 auto-approve 安全）。

**涉及文件**：`dsh_cli.js`、`astrbot_plugin_dsh/main.py`

---

### P2-1 会话管理命令（最小子集）

**做法**：为 `/dsh` 增加子命令，直接用 `session.list` / `session.rename` / `session.history`：
- `/dsh 会话` —— 列出当前工作区会话（序号 + 标题 + 最近活跃）
- `/dsh 新` —— 另起新会话
- `/dsh 重命名 <标题>` —— 改当前会话标题

**验收**：主人可在 QQ 里查看并切换南汐的会话，无需打开 DSH Web。

---

## 五、验证结果（✅ 已于 2026-09-18 实测完成）

探测脚本：`_scripts_archive\probe_workspace_session.mjs`（只读）、`_scripts_archive\probe_session_affinity.mjs`（含写操作）

### 5.1 结论速览

| # | 验证项 | 结果 | 实测证据 |
|---|---|---|---|
| 1 | 工作区注册现状 | ✅ `<PROJECT_ROOT>` **早已注册** | `workspaceId = 4d7facf1-b92a-41db-a873-990cf834d992`，title `QQbot`，探测时 `sessionIds` 11 条 |
| 1b | 「未分组」确实存在 | ✅ 确认 | 全库 89 个会话，**38 个未归组**；其中多个 `cwd = <PROJECT_ROOT>` 的会话**不在**该工作区 `sessionIds` 内 |
| 2 | 预分配 sessionId 是否幂等 | ✅ **成立** | 同 id 同 cwd 连续两次 `session.create`，两次均返回 `7f74dd9f-…-496b78585c84` |
| 2b | 同 id 不同 cwd | ✅ 按预期拒绝 | `session-conflict: session "…" already exists with cwd "<PROJECT_ROOT>"; requested "<WORKSPACE_MAS>"` |
| 3 | `workspaceId` 是否解「未分组」 | ✅ **成立** | 传 `cwd` 的会话**不在** `sessionIds`；传 `workspaceId` 的会话**在**，且排在该工作区列表**首位** |

### 5.2 由此确定的三条硬事实

1. **确定性 id 复用可行** —— `session.create({sessionId, cwd})` 幂等，**不需要 resume API**（HTTP 侧本就没有该 RPC）。
2. **归组只认 `workspaceId`** —— `cwd` 参数**不会**产生任何归属。⇒ P0-2 必须把 `cwd` 替换为 `workspaceId`。
3. **裸 UUID 形态被 DSH 接受**（无需 `session-` 前缀）⇒ 可照搬 SHA-256 → UUID 派生算法。

### 5.3 探测产生的残留（★ 实施前需处置）

| 会话 id | 来源 | 状态 |
|---|---|---|
| `7f74dd9f-d305-85a3-a6c7-496b78585c84` | 验证 #2，由 `nanxi:group:<TEST_GROUP_ID>:owner` 派生 | ⚠️ 用 `cwd` 方式创建，**未归组**；且**占用了该 key** |
| `b76e8fce-7339-0a3a-ba6d-db87c146ab1a` | 验证 #3，由 `nanxi:probe:workspace-affinity` 派生 | 已归组，纯测试用，可清理 |

> ⚠️ **对 P0-1 的直接影响**：`7f74dd9f-…` 已被「cwd 方式」占用。若将来用同一 id 改走 `workspaceId` 方式创建，**可能触发 cwd 不匹配的 `session-conflict`**。
> 处置二选一：① 实施前删除该会话重新开始；② **sessionKey 加版本后缀**（如 `nanxi:v2:group:…`）隔离。**推荐 ②** —— 无需删除、天然可回退。

> **附带发现（待补进 `AGENTS.md`）**：`Get-NetTCPConnection` 在本沙箱**查不到监听端口**（静默返回空，会误判成"服务没跑"），必须改用 `netstat -ano | Select-String ":3080"`。

---

## 六、风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 会话复用后上下文膨胀 | 长会话变慢 / 费用上升 | 提供 `/dsh 新`；后续可加"会话轮转"策略（按 token 数或天数） |
| 确定性 id 碰撞 | 极低（SHA-256 前 128 bit） | 不缓解；可观测（id 异常） |
| 改动 `dsh_cli.js` 破坏现有 `/dsh` | 现有功能失效 | 保留旧调用路径开关；每步单独 commit，可 `git revert` |
| chunk/message 双计 | 回复翻倍 | 严格遵守 §P0-3 的已知坑说明 |
| `workspace.create` 语义与预期不符 | 归组失败 | 验证清单 #3 前置拦截 |
| headless 审批挂死 | `/dsh` 长任务卡 300s | 验证清单之外的 P1-2 步骤 A 前置探测 |

**回滚**：全部改动集中在 `dsh_cli.js` + `astrbot_plugin_dsh/main.py` 两个文件，逐项 commit，`git revert <sha>` 即可退回。

---

## 七、提交与文档约定

1. 每完成一项（P0-1 / P0-2 / …）**立即 commit**，消息格式 `阶段1: <改动摘要>`。
2. 每项完成后同步更新 `AGENTS.md` 的「当前任务状态」与「踩坑清单」。
3. 密钥仍不入库（`cmd_config.json` / `游戏通知\config.json` / `onebot_*.json` / `*.db` 均 gitignore）。
4. AstrBot 侧改动**必须重启**才生效：`启动\stop_astrbot.bat` + `启动\一键启动.bat`。
5. 真实发群的验证需主人**明确同意**后再做。

---

## 附录 A：参考实现关键代码摘录（MIT，仅作设计参考）

**A-1 确定性 SessionId**（`wang-22-code/src/session/session-manager.ts`）
```ts
sessionKey(scope, peerId) { return `qqbot:${this.config.appId}:${scope}:${peerId}`; }
deriveSessionId(key) {
  const hash = createHash('sha256').update(key).digest('hex');
  return `${hash.slice(0,8)}-${hash.slice(8,12)}-${hash.slice(12,16)}-${hash.slice(16,20)}-${hash.slice(20,32)}`;
}
// getOrCreate: ① agents.get(id) 复用活跃 → ② agents.resume({resumeSessionId}) → ③ agents.create({sessionId})
```
> 我们走 HTTP，没有 `sessions.resume`；靠 **`create` 预分配 id 的幂等语义**达到同一效果。

**A-2 工作区服务**（`Jiangsubei/src/dsh/workspaces.ts`）
```ts
export interface WorkspaceRegistryLike {
  list(): Workspace[];
  get(id): Workspace | undefined;
  resolveByPath(path): Promise<Workspace | undefined>;
  create(path, title?): Promise<Workspace>;   // 注册工作区
  readonly archivedSessionIds;
}
// Workspace = { id, title, path, sessionIds }  ← sessionIds 即"归属该工作区的会话"
// resolveDefaultWorkspacePath(dshHome) = $DSH_HOME/workspace/default
```

**A-3 Markdown 切分**（`wang-22-code/src/transport/chunker.ts`，约 70 行）
> 注释原文：*"QQ 单条消息有字符数限制（约 5000），需要在合适边界切分，并保持 GFM 表格、代码块的完整性。"*
> 三原则：不在代码块中断开、不在 GFM 表格中断开、优先空行断开。

**A-4 审批 6 步**（`wang-22-code/docs/ARCHITECTURE.md`）
> ① 只接管本插件所拥有的 Agent；② 生成一次性随机验证码；③ 工具与原因发给原任务发起者；④ 只接受相同 peer、相同 sender 的明确命令；⑤ 返回 `allowed-once` 或非授权结果；⑥ 超时、取消或卸载时失败关闭。**不改变全局沙箱模式，也不提供永久授权。**

---

## 附录 B：DSH API 速查（本项目用到的部分）

```
POST /api/workspace.list        {}                        → { items: WorkspaceView[] }
POST /api/workspace.create      { path, title? }          → { workspace, created }
POST /api/workspace.rename      { workspaceId, title }    → { workspace }
POST /api/workspace.insertSessionBefore { workspaceId, sessionId, beforeSessionId? }
POST /api/session.create        { workspaceId?|cwd?, sessionId?, agentPreset? } → { sessionId, agentPreset? }
POST /api/session.list          { cursor? }               → { items: SessionSummary[] }
POST /api/session.rename        { sessionId, title? }
POST /api/session.history       { sessionId, beforeSeq?, maxMessages? } → { events, hasMore }
POST /api/session.prompt        { sessionId, mode, content[] }
POST /api/session.cancel        { sessionId }
WS   /api/events.mux            ← 下行事件流（本项目的 Node 客户端走这条）
```

**事件流关注点**：`turn/start`、`assistant/chunk`（流式，勿与下者重复累加）、`assistant/message`（终态文本）、`turn/end`（终结信号）。

---

## 八、实施记录

### 2026-09-18 · P0-1 + P0-2 完成（commit `9e020cc`）

**改动**
- `dsh_cli.js`：新增 `--key` / `--cwd` / `--fresh` 参数；`deriveSessionId()`（SHA-256 → UUID 形态）；
  `resolveWorkspace()`（`workspace.list` 按路径匹配 → 命中即复用，未命中才 `create`）；
  复用模式一律传 `workspaceId`（不再传 `cwd`）。
  **不传 `--key` 时保留旧行为（仅 `cwd`、每次新建）—— 留作回退路径。**
- `astrbot_plugin_dsh\main.py`：新增 `_session_key()`（`nanxi:v1:group:<群号>:<发送者>` / `nanxi:v1:c2c:<发送者>`）；
  调用 DSH 时传 `--key`；新增 `/dsh -n <指令>` 强制开新会话；帮助文本更新。

**实测结果**（脚本层直连验证，均为真实 DSH 回合）

| 用例 | 结果 |
|---|---|
| 首次 `--key nanxi:v1:selftest` | ✅ sessionId `8c3f45ba-…`，workspaceId `4d7facf1-…`(QQbot)，reply「连通了」，耗时 2 秒 |
| 同 key 再发（问"我刚才让你回复哪三个字"） | ✅ **返回同一 sessionId 且答「连通了」** ⇒ 复用 + 记忆成立 |
| `--fresh` | ✅ 新 sessionId `f00a71ad-…`，key 追加时间戳 |
| 归组复查 | ✅ `8c3f45ba-…` 出现在 QQbot 工作区 `sessionIds` 内 |

**服务动作**：AstrBot 已重启（旧 PID 55336 → 新 PID 61680）；启动日志确认 `Loading plugin astrbot_plugin_dsh`，**无** `Failed to import`。

### 2026-09-18 · 工作区隔离（承接上一条）

**背景**：主人指出 `/dsh` 的会话与主项目共用 `QQbot` 工作区，会影响在 `QQbot` 下工作的 bot 的记忆。

**关键发现（实测）**：DSH 会从会话工作目录**向上逐级查找 `AGENTS.md` 并注入**，且**更深目录的指令优先**。
- 证据 1：工作区设成 `<PROJECT_ROOT>\nx_dsh` 后，agent 在一个**空目录**里仍准确答出主项目手册里的端口（6185），并自述"来自项目手册 AGENTS.md"。
- 证据 2：在 `nx_dsh\AGENTS.md` 写入隔离说明后，同样的提问改按子目录说明作答，不再套用上级项目知识。

**改动**
- 新工作区 `<PROJECT_ROOT>\nx_dsh`（workspaceId `ee14b4e9-22ae-4c69-b59e-6f6d3479b459`），内含**隔离用 `AGENTS.md`**。
- `main.py`：拆出 `PROJECT_DIR`（读密钥、定位 CLI）与 `DSH_WORKSPACE_DIR`（DSH agent 干活处）。
  ⚠️ 顺带修掉一个隐患：原 `_load_deepseek_key()` 用 `CWD` 拼 `游戏通知\config.json`，**改工作区后会导致读不到 DeepSeek key**（南汐转述失效）。
- `SESSION_KEY_PREFIX`：`nanxi:v1` → **`nanxi:v2`**。`session.create` 按 **cwd** 判重，换工作区必须同步升版，否则新 key 派生的 id 会撞上旧会话报 `session-conflict`。
- `dsh_cli.js`：`DEFAULT_CWD` → `<PROJECT_ROOT>\nx_dsh`。
- `.gitignore`：新增 `nx_dsh/*` + `!nx_dsh/AGENTS.md`（只跟踪隔离配置，临时产物不入库）。

**实测**：不带 `--cwd` 调用 → `workspaceId = ee14b4e9-…`（nx_dsh 工作区）✅

### 2026-09-18 · P0-3 进度反馈　✅ 完成

**问题**：`/dsh` 长任务期间群里**干等**（最长 300 秒毫无反馈）。

**改动**
- `dsh_cli.js`：stdout 改为 **JSONL 协议**（`start` / `progress` / `result` / `error` 各一行，调试信息一律走 stderr）；
  新增 `--progress-interval <ms>`（默认 15000，`0` = 关闭），用 `setInterval` 与事件流**解耦**地吐心跳
  —— 这样即使事件流卡住，上层也能知道"还活着"。`result` 行仍是 `{` 开头的单行 JSON，旧解析逻辑向后兼容。
- `astrbot_plugin_dsh\main.py`：`subprocess.run` → **`asyncio.create_subprocess_exec` 逐行流式读取**；
  收到 `progress` 后按节流发提示（首条 ≥15 秒、两条间隔 ≥45 秒、最多 4 条）；
  超时/结束统一收尾（kill + wait + 取消 stderr 读取任务）。
  **进度只报"还活着"，绝不发 DSH 的中间文本** —— 遵守"由南汐转述、不复制 DSH 输出"的要求。

**实测**：造一个"读三个文件并总结"的任务（9.9 秒），输出 `start` + **3 条 `progress`**（3s/6s/9s）+ `result`，协议正确。

**顺带发现并处理**：该实测暴露出 DSH agent 会**自行调用 `notify_owner`** 把结果摘要发到群里，
导致同一任务在群里出现**两条**消息（DSH 原始摘要 + 南汐转述），违背主人的要求。
已在 `nx_dsh\AGENTS.md` 增加约束：「不要调用 `notify_owner`，结果由上层转述」。

**后续修复（同日，均由主人在群里实测暴露）**
- 回归 ①：`asyncio.create_subprocess_exec` 在本机沙箱**被禁用**（Windows asyncio 用命名管道接 stdio → `PermissionError [WinError 5]`）。改用 `subprocess.Popen` + 后台线程 + `queue`，流式进度不受影响。
- 回归 ②：`prompt: GreedyStr = None` 让 AstrBot 的贪婪参数**完全失效**，只把第一个词交给 DSH（`/dsh 检查 <PROJECT_ROOT> 下所有…` 只传了"检查"）。去掉默认值即修复。
- 回归 ③：`on_agent_begin` 的兜底正则过宽，**任何**提到 dsh 的句子都被劫持去跑 DSH。已收紧为「动词 + 空格 + `dsh` + 内容」，并加开关 `NL_TRIGGER_ENABLED`。

### 2026-09-18 · P1-1 长回复切分　✅ 完成

**问题**：南汐转述正常约 600~900 字（不会超限），但**转述失败回退原始 DSH 输出**时可能几千字，会撞 QQ 单条消息上限。

**改动**：`astrbot_plugin_dsh\main.py` 新增 `_chunk_markdown(text, limit)`（思路移植自 `chunker.ts`，MIT），上限常量 `REPLY_CHUNK_LIMIT = 1800`；`/dsh` 命令与自然语言拦截均改为**逐块发送**。
比参考实现多做一步：**把代码块当原子单元**（原实现只用 `in_code` 状态避免误判表格，代码块仍会被 `append_line` 切开）。现做法是先把整个代码块（含闭合围栏）收成一个块再加入，GFM 表格同理。

**实测**（`_scripts_archive\probe_chunk_markdown.py`，直接加载真实插件模块）：8 项全过 —— 短文本不切、长文本每块 ≤ 上限且可无损拼回、代码块围栏不分离、表格整块、超长单行硬切、正常长度转述不切。

### 2026-09-18 · P1-2 审批探测　✅ 完成（结论：暂不做转发）

**背景**：担心 `/dsh` 任务卡在审批上（headless 环境无人应答）。

**探测结论**
- 本机 DSH 装着 **`dsh-approval-gate`**（自动审批）与 `@deepseek-ai/dsh-permission-presets`；工作目录 `~/.dsh/auto-approve/`（`allowlist.json` / `audit.log` / `events.jsonl`）。
- 规则：`allowRules: workspace-write` **自动允许**；`hardCategories`（deletion / credential / remote / system / bulk）→ **转人工**。
- **实测**：工作区**内**的普通操作、以及工作区**外**的**只读**操作，**都不触发审批**（读 `C:\Windows\System32\drivers\etc\hosts` → 4 秒成功）。⇒ 绝大多数 `/dsh` 任务不会卡。
- **仅剩风险**：agent 主动用 `sandbox_permissions` **提权**时 → HARD → 转人工，而 QQ 侧没有转发通道 ⇒ 会卡到超时。

**已做的低成本兜底**
- 超时消息补上审批指引（提示可能卡在 DSH 审批、去 Web 面板看）。
- `nx_dsh\AGENTS.md` 新增「沙箱与权限」段：明确告诉 agent **读任意路径可以、不要请求提权**，被拒就停下说明。

**完整转发方案（待需要时再做）**：`approvals.d.ts` 已确认协议 —— 审批请求是 server-request（稳定 rpcId），应答是 client-response（echo 该 rpcId），走 `POST /api/respond`，载荷 `{sessionId, approvalId, outcome: 'allowed-once' | 'rejected'}`。要落地需先确认审批帧是否会出现在 `events.host` / `events.mux` 下行流里。

### 2026-09-18 · P1-3 急停（`@南汐 stop` / `/dsh stop`）　✅ 完成

**需求**：主人要一条能**强制停下正在跑的 DSH 任务**的指令。

**关键查证**：AstrBot **内置命令里已经有 `stop`**（`builtin_commands\main.py:49`）⇒ 自己再注册同名命令会**双触发、回两条**。
内置 stop 的实际行为（`core\utils\active_event_registry.py:52-91`）分两支：
- 第三方 runner → `stop_all()`（调 `event.stop_event()`，真掐断）；
- **本机是 `local` → `request_agent_stop_all()`：只给 event 设 `agent_stop_requested` 标志 + 调用已注册的停止回调，不中断事件传播**。
⇒ `/dsh` 是"handler 里等子进程"，**光靠内置 stop 停不下来**。

**做法（复用内置 stop 而不是抢名字）**
- 注册 `active_event_registry.register_agent_stop_callback(event, cb)`：用户发 `@南汐 stop` → 内置命令 → 回调 `cb` → 起线程调 `--cancel` 取消 DSH 那一回合 + `kill` 本地子进程（任务结束 `unregister`）。
- `dsh_cli.js` 新增 `--cancel <sessionId>`（走 `sessions.cancel`；DSH 语义：停 active turn，pending 队列保留）。
- 另给显式入口 `/dsh stop`：直接 `--cancel` 掉 `_running` 里登记的所有会话（由 CLI 的 `start` 行登记、任务结束注销）。
- 兜底：读循环每秒醒一次时检查 `event.get_extra("agent_stop_requested")`，为真就 kill 子进程。

**实测**（`_scripts_archive\probe_cancel.py`）：起一个本应跑 20s+ 的任务 → 中途 `--cancel` → 返回 `{"ok":true}` → 任务 **0.0 秒后收尾**、`reason=aborted`、CLI 退出码 0。

**遗留（截至 2026-09-18）**
- ⏳ **端到端实测待做**：需主人在 QQ 群真发 `/dsh` 验证（脚本层已全部验证通过）。
- ⏳ 未开始：P1-1 长回复切分、P1-2 审批探测、P2-1 会话管理命令。
- ✅ 探测残留会话已归档（`_scripts_archive\cleanup_probe_sessions.mjs`，可逆）

---

*本文档为实施计划 + 进度记录。P0-1/P0-2 已完成并实测；后续每完成一项即 commit 并回写本节与 `AGENTS.md`。*
