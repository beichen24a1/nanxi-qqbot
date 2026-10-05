# 计划：mas 答疑改用「分支会话」（fork）

> 生成 2026-09-18 ｜ 状态：**目标已记录，待主人确认源会话后实施**
> 相关：`阶段1-DSH桥接增强-计划.md`、`AGENTS.md`、`astrbot_plugin_dsh\main.py`

---

## 一、问题（主人 2026-09-18 指出）

`/mas` 答疑目前是**在 `<WORKSPACE_MAS>` 工作区新开一个会话**（sessionKey = `nanxi:mas:v2`，由 SHA-256
派生固定 id，所以其实是"固定但每次都是全新的空上下文"）。三个痛点：

| 痛点 | 说明 |
|---|---|
| **慢** | 空上下文，agent 每次都要重新翻 mas 项目文件才能回答 |
| **吃不到缓存** | 新会话前缀为空，prompt cache 命中率 ≈ 0 |
| **浪费 token** | 同样的问题、同样的文件，反复读、反复喂 |

**根因**：DSH 的会话复用只认 `sessionId`（且判重按 cwd），**"新建"就等于零上下文**；
而换成"复用旧会话"又会把不同问题的历史混在一起、越滚越长。

## 二、目标

让 mas 答疑**从一个已有充分上下文的会话「分支」出来**：

1. **命中 prompt cache** —— fork 出的会话带着源会话的历史前缀，前缀相同即可命中 → 又快又省；
2. **复用已积累的知识** —— 不必每次重读 mas 项目文件；
3. **可重复** —— 需要重新开始时，再从合适的源会话分一次即可（而不是重头读文件）。

## 三、方案：DSH 的 `session.fork`

**API**（`dsh-host-apiproxy\lib\types\api\sessions.d.ts:342-361` 已核对）：

```
POST /api/session.fork       // 客户端方法：api.sessions.fork({ sessionId, atSeq? })
  请求: { sessionId: <源会话>, atSeq?: number }
  返回: { sessionId: <新会话> }
```

语义（文档原文要点）：
- 从源会话的**已完成回合前缀**分叉；`atSeq` 锚定切点（取该 seq 处或之后的第一个 `turn/end`）；
- 不传 `atSeq` → 回退到源会话**最后一个已完成回合**；
- 在途回合作切点会报 `fork-unavailable`（不会往前裁剪）；
- 子会话**继承源的 cwd、最新模型目标、`parentSessionId` 血缘**，seed 前缀带源标题；
- 读取源会话**不会**占用/唤醒它的 Agent。

⇒ 正因为带着 seed 前缀，**fork 出的会话才是能命中缓存的那种"续写"**。

## 四、实施要点（待做）

1. **`dsh_cli.js` 加 `--fork <sourceSessionId>`**（可再给 `--fork-at <seq>`），成功时输出新 sessionId。
2. **`/mas` 的会话获取顺序改为**：
   - ① 已持久化的 mas 分支会话存在且可用 → 直接用；
   - ② 否则 → 从配置的**源会话** fork 一个 → 把新 id 持久化；
   - ③ 源会话不存在 / fork 失败 → 退回现在的"新建"路径（并记日志说明）。
3. **持久化**：把 mas 分支会话 id 写到一个本地小文件（如 `nx_dsh\mas会话.json`，不进 git），
   避免每次重启插件都重新 fork。
4. **"训练"**：持续用这个分支会话答疑 → 上下文越积越厚、越答越准；
   但**要设膨胀阈值**（上下文太长就该重新 fork 一次，或换更干净的源会话）。
5. 可选：给 `/dsh` 也提供 `--fork`，用于"接着某个会话继续干"。

## 四·补 · fork 机制已实测（2026-09-18）

在源会话 `2af2779b-a4d7-0615-d06d-50b44298273b`（cwd = `<WORKSPACE_MAS>`，5277 条事件）上实跑：

```
源会话: 2af2779b-a4d7-0615-d06d-50b44298273b   cwd = <WORKSPACE_MAS>   事件数 5277
[OK]    fork 成功 -> session-6f9c5971-c92e-4e17-8204-add37ada9af1
[检查]  新会话事件数: 5278   => 继承了历史前缀（可命中缓存）
[检查]  新会话 cwd = <WORKSPACE_MAS>   parentSessionId = 2af2779b-…   agentPreset = standard
```

**结论**：`session.fork` 可用 —— 子会话确实带源前缀（5278 = 源 5277 + fork 自身 1 条），
cwd / 血缘 / preset 全部继承。**"从已有会话分支"这条路机制上完全走得通。**
（验证脚本：`_scripts_archive\probe_fork.mjs`，用法 `node probe_fork.mjs <sourceSessionId>`）

⚠️ **同时暴露一个必须权衡的点**：上面这个源会话有 **5277 条事件** —— 前缀越长，每次请求要带的
上下文越多（命中缓存便宜得多，但并非免费）。所以：

- **源会话要挑干净的**：最好是"已经能答 mas 问题、但上下文不臃肿"的那种；
- **分支会话要设膨胀阈值**：上下文超过某个量就**重新 fork**（或挑一个更短的源），而不是无限滚下去。

## 五、候选源会话（主人说的"debug 这个会话"待确认）

`session.list` 里所有会话的 title 都是空的，所以只能按工作区 / cwd / 时间判断：

| sessionId | 工作区 | cwd | 最后活跃(UTC) | 备注 |
|---|---|---|---|---|
| `2af2779b-a4d7-0615-d06d-50b44298273b` | mas | `<WORKSPACE_MAS>` | 13:53 | **最新的 mas 工作区会话**（疑似 mas 答疑自动测试建的） |
| `session-4fc15bc6-b378-4822-8470-c66940eb738c` | mas | `<WORKSPACE_MAS>` | 13:28 | 较早的 mas 工作区会话 |
| `14bccf26-64c2-4d7c-a59c-5723c4d1dc10` | （未归组） | `<WORKSPACE_MAS>` | 13:29 | 未归组 |
| `session-85cb40a8-42d0-4f76-b414-8a7115220742` | QQbot | `<PROJECT_ROOT>` | 13:58 | **当前这次对话的会话**（一直在改 mas 答疑功能） |

**待主人指名**：他说的"debug 这个会话"是哪一个。
- 若是**想让 mas 答疑继承"开发 mas 答疑时积累的知识"** → 选最后一个（当前会话）；
- 若是**想让 mas 答疑继承"mas 项目本身的知识"** → 选 `<WORKSPACE_MAS>` 工作区里那个。

## 六、风险

- **前缀越长，每次请求带的上下文越多** —— 但**能命中缓存**，总体仍比"每次重读文件"划算；
- **上下文膨胀** —— 需设阈值，超了就重新 fork（或挑一个更短的源会话）；
- **`atSeq` 用法**要实测确认（不传时取最后一个已完成回合，未必是我们想要的切点）；
- fork 只是**复制前缀**，不是共享状态：源会话后续的更新不会同步到分支。

## 七、实施记录（2026-09-18 当日完成）

主人指定源会话 = `session-4fc15bc6-b378-4822-8470-c66940eb738c`，已按本文档方案落地：

1. **`dsh_cli.js` 新增两个子命令**
   - `--fork <sourceSessionId>` → 输出 `{type:'forked', source, sessionId, ok}`
   - `--session-id <sessionId>` → 直接用指定会话（不派生、不新建）—— 这是 `--key` 之外**第三条**会话来源
2. **fork 结果**：`session-4fc15bc6…` → **`session-bb566ab6-95cd-4765-ae70-1d08ea6264ee`**
   （实测继承：cwd=`<WORKSPACE_MAS>`、归组在 **mas 工作区**、parentSessionId 血缘正常）
3. **`/mas` 改造**：新增 `_mas_session_id()` —— ① 读持久化文件；② 没有就 fork 并落盘；③ fork 失败退回按 key 新建。
4. **持久化**：`nx_dsh\mas会话.json`（已在本次写好 fork 出的会话 id；该目录被 gitignore，不进库）。

### 关键实测：分支会话确实"带着源的知识"

在分支会话上提问，并在 prompt 里**明确禁止读文件**：

> 请**不要**读任何文件（不要用工具），直接凭你已有的上下文回答：mas 是什么项目？支持哪些游戏？配置文件叫什么、在哪里？

**结果（13.2 秒）**：完整答出了 mas 的多脚本管理器定位、覆盖的 9 个游戏（MAA / MaaEnd / M9A / HSR / ok-ww / ok-nte / BAAH / BetterGI …）、
`config/` 下 `Config.json` / `ScriptConfig.json` / `EmulatorConfig.json` / `QueueConfig.json` / `PlanConfig.json` 的分工、
以及 `data/<脚本ID>/<用户ID>/` 的用户数据布局。

⇒ **一个文件都没读**，知识全部来自 fork 继承的会话前缀 —— 正是"分支会话"要的效果（快、省、无需重读）。
验证脚本：`_scripts_archive\probe_fork_use.py`。

### 仍待做

- **膨胀阈值**：分支会话越聊越长，需要设上限（超了就重新 fork / 换更干净的源）。
- 可选：`/dsh` 也支持"接着某个会话继续干"（`--session-id` 已具备，只差上层入口）。

---

*维护：DSH ｜ 目标与方案已落地，后续改动请续写「实施记录」。*
