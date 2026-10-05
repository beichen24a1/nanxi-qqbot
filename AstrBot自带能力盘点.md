# AstrBot 自带能力盘点

> 生成 2026-09-18 ｜ 目的：**动手前先查上游有没有现成的**。
> 起因：做"长回复转合并转发"时发现 AstrBot 自带 `forward_threshold`，而**我自己写的分片逻辑反而把它废掉了**
> （我先把长文本切成每片 <1800 字的多条消息发出去，每片都够不着 1500 的阈值，上游永远没机会转）。
> 同类教训本项目踩过不止一次（`stop` 命令也是自带）。所以把上游能力盘一遍，避免重复造轮子。

---

## 一、内置插件

路径：`astrbot\astrbot\builtin_stars\`

| 插件 | 作用 |
|---|---|
| `astrbot` | 核心功能插件 |
| `builtin_commands` | 内置命令（下面第三节） |

## 二、内置命令（`builtin_commands\main.py`）

| 命令 | 作用 | 备注 |
|---|---|---|
| `/help` | 帮助 | |
| `/sid` | 当前会话 id | |
| `/name` | 设置当前 UMO 的显示名 | 用 `GreedyStr`（见 `AGENTS.md` 那个默认值坑） |
| `/reset` | 重置对话历史 | |
| **`/stop`** | **停止当前会话正在运行的 Agent** | ⚠️ 插件长任务要**注册回调**才能被它停，见第五节 |
| `/new` | 新建会话 | |
| `/stats` | 统计 | |
| `/provider` | 模型 provider | |
| `/dashboard_update` | 更新面板 | |
| `/set` `/unset` | 设置 / 取消设置 | |

## 三、`platform_settings`：一堆现成的开关（★ 重点）

位置：`astrbot\data\cmd_config.json` 的 `platform_settings` 段（**不在顶层**）。

| 配置 | 本机当前值 | 作用 |
|---|---|---|
| **`forward_threshold`** | **1500** | **回复里 Plain 字数超过它 → 自动包成合并转发**（仅 `aiocqhttp` 平台） |
| `reply_with_mention` | `false` | 回复时 @ 发送者 |
| `reply_with_quote` | `false` | 回复时引用原消息 |
| `segmented_reply` | `enable=false` | **拟人化分段回复**：按标点切分、随机/对数间隔、可只对 LLM 结果生效 |
| `rate_limit` | 60 秒 / 30 条 / `stall` | 限流（`stall`=排队，`discard`=丢弃） |
| `unique_session` | `false` | 每个会话独立上下文 |
| `enable_id_white_list` / `id_whitelist` | `true` / 4 个群 | 白名单 |
| `id_whitelist_log` | `true` | 白名单命中打日志 |
| `wl_ignore_admin_on_group` / `_on_friend` | `true` | 管理员无视白名单 |
| `no_permission_reply` | `true` | 无权限时回一句提示 |
| `empty_mention_waiting` / `_need_reply` | `true` | 只 @ 不说话时等待补话 |
| `friend_message_needs_wake_prefix` | `false` | 私聊是否也要唤醒前缀 |
| `ignore_bot_self_message` | `false` | 忽略机器人自己发的消息 |
| `ignore_at_all` | `true` | 忽略 @全体 |
| `reply_prefix` | `""` | 回复前缀 |
| `path_mapping` | `[]` | 路径映射 |

## 四、其他值得知道的内置能力

### 消息组件（`core\message\components.py`）
`Plain` / `Image` / `Record` / `Video` / `At` / `AtAll` / `Reply` / `Poke` / `Forward` / `Node` / `Nodes` /
`Json` / `File` / `Location` / `Music` / `Share` / `Face` / `RPS` / `Dice` …

两个特别省事的：
- **`Image.convert_to_file_path()`** —— 把图片（URL / base64 / 本地文件）统一转本地路径，**网络图自动下载**；
- **`Reply.message_str` + `Reply.chain`** —— **被引用的消息 AstrBot 已经解析好填进来了**
  （纯文本在 `message_str`，消息段在 `chain`，含图），不用自己调 OneBot 的 `get_msg`。

### 消息管线阶段（`core\pipeline\`）
`waking_check`（唤醒/白名单）→ … → **`result_decorate`（合并转发 / @ / 引用 都在这）**

### 停止机制（`core\utils\active_event_registry.py`）
- 内置 `/stop` 按 `agent_runner_type` 分两支：第三方 → `stop_all()`（真掐断）；**`local`（本机）→ `request_agent_stop_all()`：
  只设 `agent_stop_requested` 标志 + 调已注册的停止回调**；
- 插件的正规接入点：`register_agent_stop_callback(event, cb)`（同步回调，异步动作要起线程），结束记得 `unregister`。

### 模型 / Agent
- `provider_settings.agent_runner_type`：`local` / `tool_loop` / `dify` / `coze` / `dashscope` / `deerflow` …（本机 = `local`）
- `provider_settings.default_personality`、`identifier`（让 AI 看到发送者 ID/昵称）
- `provider` / `provider_sources`：模型供应商配置

### t2i（文字转图片）
`t2i` / `t2i_word_threshold` / `t2i_strategy` 等 —— 超长文本可转成图片发（本机相关开关未启用）。

## 五、对我们项目的直接影响（已经改过的）

| 我们原本自己做的 | 上游其实自带 | 处理 |
|---|---|---|
| 把长回复切成分片、逐条发 | `platform_settings.forward_threshold` 自动合并转发 | ✅ 已去掉本地分片，交给上游（`_chunk_markdown` 保留作备用） |
| 自己注册 `stop` 命令 | 内置 `/stop` + `register_agent_stop_callback` 接口 | ✅ 已改为接回调（避免与原生命令**双触发**） |
| 自己解析引用消息 | `Reply.message_str` / `Reply.chain` | ✅ 直接取用 |
| 自己下载图片 | `Image.convert_to_file_path()` | ✅ 直接调用 |

## 六、还没用上、但可能有用的（备忘）

- **`segmented_reply`** —— 让南汐像真人那样分多条、带间隔说话；可能适合**闲聊**，不适合任务结果（结果要一次看清）；
- **`reply_with_quote`** —— 任务回复带上引用，群里能一眼看出在回谁；
- **`t2i`** —— 极长文本转图片（比合并转发更"一眼看完"）；
- **`rate_limit`** —— 目前 60 秒 30 条，防止刷屏；
- 内置命令 `/sid`、`/stats` —— 排查会话/用量时有用。

---

*维护：DSH ｜ 上游升级后能力可能有变，以实际源码为准（路径都写在表里了）。*
