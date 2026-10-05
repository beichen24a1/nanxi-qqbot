# 计划：南汐（主 agent）↔ DSH（执行 agent）分层协作

> 确立 2026-10-02 ｜ 状态：**阻塞中**（地基待修，见 §0）
> 目标：让南汐回到"纯角色扮演 + 调度者"的位置，把"干活"整体外包给 DSH，
> 并且**全过程可见、需批准时由南汐转述给主人、主人点头后放行**。

---

## 0. 前置阻塞（2026-10-03 勘察才发现）

**`/dsh` 当前已全线失效（HTTP 401）** —— DSH 升级到 `0.2.0-rc.2` 后：
① 给 Web 加了签名 Cookie 认证；② 我们依赖的 `dsh-host-apiproxy` 客户端包**已被移除**。

⇒ 本文所有设计都建立在"能与 DSH 通话"之上，**必须先修复基础设施**：
`qq-bridge` 更新到上游 `v0.2.0-r3`（它已适配 0.2.0，含**离线铸造 Cookie**的鉴权实现与新协议），
再让 `dsh_cli.js` 走新认证 + 新端点（`/api/remote.mux`）。
详见 `环境勘察报告-20261003.md`。

---

## 一、目标定位（主人原话）

> 南汐只需要单纯角色扮演，遇到要写代码之类的问题就调用 dsh 等其他智能体，南汐只负责日常聊天。

> 南汐和 dsh 之间的关系就和你和你的子代理一样。

**关系模型**：南汐 = 主 agent（派活 / 旁观 / 答话 / 汇总），DSH = 她的执行子代理。
这不是新路线，而是**给阶段 1 补最后一块**：旧路线里 DSH 是南汐的"命令"（`/dsh`），
新目标是 DSH 成为南汐的"**工具**"——她自己判断何时用。

### 与旧路线图的关系

| | 旧（`南汐自主智能体-目标与路线图.md`） | 现在 |
|---|---|---|
| 南汐的角色 | 南汐**就是**那个 agent（人格+工具一体） | 南汐是**人格/前台**，DSH 是她的**手** |
| 怎么用上 DSH | 显式 `/dsh` 或"调用dsh"触发词 | **南汐自己判断**（LLM 工具调用） |
| 形态 | 命令式 | 委托式 |

DSH 只是南汐手上**第一个**外部智能体 → 这就是"多智能体"的入口。

---

## 二、要解决的三个真问题

1. **审批会卡死**：主人提"调度 DSH 时如果需要手动批准呢？"
2. **反馈是"跑完再说"，不是流式的**：主人提"不是流式的，而是在 dsh 操作完之后才给我反应"
3. **触发靠正则劫持**：顺口提到 dsh 就被劫持（正则已决定拆掉，`/dsh` 保留）

---

## 三、技术依据（★ 本节推翻了 AGENTS.md 的旧结论）

### 3.1 旧结论是错的

`AGENTS.md` §5.5 写着"DSH 提权会被转人工审批，而 **QQ 侧没有审批转发通道** → 卡到超时（最长 5 分钟）"。

**实测阅读协议后确认：通道一直是通的，是 `dsh_cli.js` 没接。**

DSH 的事件流（WebSocket `/api/events.mux`）每帧都是一个 **server-request 信封**
（`{ rpcId, payload }`，见 `qq-bridge/src/dsh-client.js:60-67`，用官方 `serverRequestSchema` 解析），
`payload.type` 取值：

| 事件类型 | 含义 | 我们旧代码 |
|---|---|---|
| `session/event` → `turn/start` | 回合开始 | ✅ 处理 |
| `session/event` → `assistant/chunk` | **流式文本增量** | ❌ 丢弃（collector 故意忽略以防文本翻倍） |
| `session/event` → `assistant/message` | 组装后的完整文本 | ✅ 处理 |
| `session/event` → `turn/end` | 回合结束 | ✅ 处理 |
| **`approval/requested`** | **审批请求**（`toolName` / `reason` / `approvalId`） | ❌ **丢弃 → DSH 干等 → 卡到超时** |
| **`question/requested`** | **agent 提问**（`questions[]`） | ❌ **丢弃 → 同样卡** |
| `stream/error` | 事件流错误 | ✅ 处理 |

⇒ 任务卡 5 分钟的真因：**DSH 一直在发 `approval/requested`，我们视而不见，它就只能等。**

### 3.2 应答协议（`qq-bridge` 已有完整实现，可直接复用）

```js
await api.respond({
  type: 'client-response',
  rpcId: envelope.rpcId,        // ★ 必须 echo 原 rpcId 才能配对
  result: { ok: true, value: { sessionId, approvalId, outcome: 'allowed-once' } },
});
```

- 审批 outcome：`'allowed-once'`（通过）| `'rejected'`（拒绝）
- 提问应答：`value: { sessionId, answer: { answers: [{ id, selected: [], custom: '' }] } }`
- 参考实现：`qq-bridge/src/bridge.js:7939-7994`（事件捕获与转发）、`7480-7500`（回复词匹配）
- 回复词表：`APPROVE_WORDS = {'通过','同意','允许','批准','yes','y','approve','ok'}`（`bridge.js:680`）

> ⚠️ `respond` 是**无状态 HTTP 调用**（带 rpcId 即可配对），
> 所以**应答可以由另一个进程发起** —— 这是本方案能落地的关键：
> 长驻的 `dsh_cli.js` 只管"报事件 + 等"，插件另起一个进程回填应答。

### 3.3 AstrBot 侧可行性（已核实，零风险）

- `agent_runner_type = local`（本机）**本来就支持 LLM 工具调用**：
  `core/pipeline/process_stage/method/agent_sub_stages/internal.py:285`
  把 `req.func_tool.names()` 交给 AgentRunner ⇒ **不需要切换 runner 类型**。
- 工具注册接口：`core/star/register/star_handler.py:586` 的 `register_llm_tool`
  （插件侧写法 `@filter.llm_tool(name="...")`，函数 docstring 会被解析成参数 schema）。
- 工具返回值（str）会回灌给 LLM 让它总结 ⇒ 正是"南汐自己组织语言"的机制。
- ⚠️ 本机 `provider_settings.tool_call_timeout = 120` 秒 ⇒ **工具体内不能同步等 DSH 跑完**。

---

## 四、设计

### 4.1 触发：南汐自主判断（替代正则）

```
@南汐 今天天气真好呀      → 南汐自己聊，不调工具
@南汐 帮我把 xxx 脚本修一下 → 南汐判断"这是干活" → 调用 dsh_task 工具
```

- 新增 `@filter.llm_tool(name="dsh_task")`：工具**立刻**返回"任务已派发"（绕开 120s 超时），
  DSH 在后台跑。
- **拆掉 `on_agent_begin` 里的 dsh 正则劫持**（钩子本身保留，改用于审批回复拦截，见 4.4）。
- **保留 `/dsh`** 作为"显式强制"后门（主人明确要保留）。

### 4.2 执行：后台跑 + 流式播报

`dsh_cli.js` 从"只吐 start/progress/result"扩展为**完整事件转发**（JSONL，一行一事件）：

| 新增行类型 | 来源 | 用途 |
|---|---|---|
| `{"type":"chunk", text, turn}` | `assistant/chunk` | 流式进度（**节流后**再决定怎么用） |
| `{"type":"tool", name, phase}` | 工具调用事件 | **事实级进度**（"正在运行 xxx"） |
| `{"type":"approval", rpcId, sessionId, approvalId, toolName, reason}` | `approval/requested` | 转述给主人等待批复 |
| `{"type":"question", rpcId, sessionId, questions}` | `question/requested` | 同上 |
| `{"type":"awaiting", kind}` | 进入等待 | 通知上层"在等人，别超时" |

新增子命令（供插件回填）：

```
node dsh_cli.js <baseUrl> --respond <rpcId> allowed-once|rejected
node dsh_cli.js <baseUrl> --answer  <rpcId> <json>
```

**超时策略**：进入"等待审批/提问"状态时**暂停超时计时**（否则会在主人思考时被杀掉）。

### 4.3 流式播报的分寸（重要）

**不直接转发 DSH 的 `chunk` 原文** —— 那是 DSH agent 的技术输出，又长又专业，
且违背既有约定"由南汐转述，不是复制 DSH 输出"（`main.py` 文件头注释）。

采用**两层**：
- **过程**：从事件流提取**事实级**动作（工具名/文件操作）→ 节流播报短句（客观事实，不需 LLM）；
- **节点**（审批 / 提问 / 完成）：由**南汐 LLM 转述**，她自己的话，不套模板。

### 4.4 审批：转述给主人 → 仅主人可批

```
DSH: approval/requested (toolName=rm -rf …, reason=…)
  ↓ dsh_cli.js 输出 {"type":"approval", rpcId, …}
插件：南汐转述 → 发到【任务所在的群】
      "主人，DSH 说它想执行 xxx，理由是 xxx，要放行吗？(´・ω・`)"
  ↓ 主人回复「通过」/「拒绝」（仅主人，非主人回复忽略）
插件：dsh_cli.js --respond <rpcId> allowed-once
  ↓ DSH 继续跑
```

- **落点**：任务所在的群（主人已确认）；**只有 `<OWNER_QQ>` 的批复生效**。
- **拦截方式**：复用 `on_agent_begin` 钩子 —— **仅当存在待批复任务时**才拦截主人的
  「通过/拒绝」；无待批复时完全放行（不影响正常聊天）。
- **超时**：等待超时（可配，默认 10 分钟）→ 自动 `rejected`，避免任务永久挂起。

### 4.5 权限

- `dsh_task` 工具：**仅主人**（工具内校验 `sender != OWNER_QQ` → 返回拒绝说明）。
- 审批批复：**仅主人**。

---

## 五、实施步骤

1. `dsh_cli.js`：事件转发（chunk/tool/approval/question）+ `--respond` / `--answer` + 等待期不超时
2. 实测新协议（真跑一个会话，含一次故意触发审批的用例）
3. `main.py`：审批/提问事件处理 + 待批复状态机 + 主人批复拦截 + 回填
4. `main.py`：`@filter.llm_tool("dsh_task")` + 拆正则（保留 `/dsh`）
5. 重启 AstrBot 实测：自主判断 / 流式播报 / 审批往返
6. 更新 `AGENTS.md`（**推翻**"QQ 侧无审批通道"的旧结论）+ git 存档

---

## 六、待验证风险

- [ ] `assistant/chunk` 能否稳定拿到工具调用事件（需实测确认事件名，不能只靠推测）
- [ ] `--respond` 跨进程回填是否真的生效（rpcId 是否与事件流同源）
- [ ] `tool_call_timeout=120` 下，工具"立刻返回"路径是否真的不被掐断
- [ ] AstrBot 重启后 `@filter.llm_tool` 是否被正确注册（看启动日志）
- [ ] 群内审批提示是否会造成打扰（节流与合并）

---

*维护：DSH ｜ 实施完成后在文末补「实施结果」。*
