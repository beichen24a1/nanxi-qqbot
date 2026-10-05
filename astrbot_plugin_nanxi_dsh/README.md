# 南汐 · 自主调用 DSH（astrbot_plugin_nanxi_dsh）

让南汐**自己判断**什么时候该把事情交给 DSH 执行代理去做 —— 不再靠用户手打 `dsh ` 前缀
（那是 `astrbot_plugin_dsh_relay`／星驿那条路），也不靠正则猜意图。

## 它在哪一层

```
QQ 群 → SnowLuma → AstrBot（南汐的人设 + DeepSeek）
                      │  南汐自己决定「这事得动手」
                      ▼
                 @filter.llm_tool  dsh_task   ←── 本插件
                      │  HTTP + SSE（星驿桥接，bridgeVersion 7）
                      ▼
                 DSH agent（真实机器上的完整工具）
```

南汐是主 agent，DSH 是它的执行子代理。两者的对话键都是同一会话里那个
`onebot-qq:GroupMessage:<群号>`，所以**自主调用和 `dsh ` 前缀触发共用同一个 DSH 会话**，
上下文是连续的。

## 行为

| 场景 | 群里会看到什么 |
|---|---|
| 长任务（DSH 输出超过 `flush_chars`） | 南汐先说一句过渡话 → `· DSH 正在用 xxx` 进度 → DSH 正文按节流分片陆续出现 → 南汐用自己口气收尾（不重复正文） |
| 短任务（DSH 输出很短，没触发分片） | 南汐先说一句过渡话 → 进度 → 南汐**用人设转述**结果（群里只有南汐一条正式回复，最自然） |
| 非主人调用 | 工具直接拒绝，南汐用自己口吻礼貌回绝（不暴露"工具""DSH"这些词） |
| 用户发 `@南汐 stop` | **约 1 秒内**中断这一轮 DSH 任务，群里先收到「（已经叫停了）」 |
| 桥接没起来 | 返回可读的失败原因，南汐转述给用户，不会静默卡住 |

**为什么要有两种口径**：DSH 的内容一旦已经流式发到群里，再让南汐复述一遍就是群里出现两遍；
反过来，短任务如果也先发原文再让南汐收尾，就成了两条消息说同一件事。
判定依据是 `emitted`（工具内是否真的发出过正文分片）。

**过渡话从哪来**：不是插件发的。模型**带 tool_calls 的那次响应里若有正文**，那段正文
AstrBot 也会发给用户（`tool_loop_agent_runner.py:925-936` 在工具分支之外），
所以南汐能自然地说一句"那我让 dsh 去看看"再交活。

## 急停

复用 AstrBot 内置的 `stop` 命令（**不自己注册同名命令** —— 会与内置命令双触发、回两条）：

```python
active_event_registry.register_agent_stop_callback(event, cb)   # cb 是同步函数，不能 await
```

回调里 `loop.call_soon_threadsafe(stop_event.set)`，主流程则让
`_run_turn()`（SSE 消费）与 `stop_event.wait()` 赛跑，谁先到算谁。

> ⚠️ 被叫停时取消的是**子协程**，不是当前 task。被取消的 task 里再 `await` 会被立刻二次取消，
> 那样连"已经停下来了"这句话都发不出去。

## 配置

`data/config/astrbot_plugin_nanxi_dsh_config.json`（gitignore，不进库）：

| 键 | 说明 |
|---|---|
| `enable` | 总开关 |
| `owner_only` | 默认 `true`。**强烈建议保持开启** —— DSH 在本机是完全文件权限 |
| `owner_qq` | 主人的 QQ 号 |
| `bridge_url` | 必须与星驿插件 **填同一套**：`http://127.0.0.1:3080/astrbot-relay` |
| `bridge_token` | 必须与星驿插件的 `bridge_token` **完全一致**（本机 43 字符） |
| `flush_chars` / `throttle_ms` / `chunk_size` | 流式分片节流与单条上限 |
| `request_timeout` | 单轮 DSH 任务最长等待（秒） |

> `bridge_token` 是唯一的一处密钥，两处插件各存一份；改 token 时要一起改，改完重启 AstrBot。

## ⚠️ 四个会让人白查半天的坑

1. **人格的 `tools` 白名单**。`astr_main_agent.py:602` 的判定是
   `if (persona and persona.get("tools") is None) or not persona:` → 给全部工具；
   **否则只给白名单里的**。而 `[]` 是 falsy ⇒ `tools = []` 等于**一个工具都不给**，
   模型只能回答"我看不到你的电脑"。
   本机就踩过这个：插件加载正常、`Added llm tool: dsh_task` 也打了，但群里毫无反应。
   修法（二选一）：把人格 `tools` 设成 `null`（给全部工具，不推荐），
   或显式列出 `["dsh_task"]`（推荐，正好符合"南汐只聊天、干活交给 DSH"的定位）。
   本机用的是后者：`UPDATE personas SET tools='["dsh_task"]' WHERE persona_id='南汐'`。
   改完**必须重启 AstrBot**（人格有内存缓存）。

2. **模型会"学着演"上下文里出现过的每一句话**。这是最坑的一条：
   上下文里只要出现过一次"我看不到你的电脑"，**之后它就会继续这么演** ——
   本机实测：非主人被拒一次之后，**连主人的请求它也回"这个真做不了"**，
   而 `dsh_task` 其实一直好好地在工具集里（`on_llm_request` 钩子能看到）。
   两手对策（都已落地）：
   - 拒绝时明确告诉模型「**这个能力你是有的**，只是不给他用而已」；
   - 每次请求都往 `req.system_prompt` 追加一句「你有 DSH 这双手，需要碰机器就调用
     `dsh_task`，绝不要说『我看不到你的电脑』」——**只靠工具描述不够**，
     那是弱注意力区（第一版就只靠描述，结果模型面对"数一下有几个 .md"照样推脱）。

   排查这类问题时**务必先拿到干净上下文**：本机 `provider_settings.wake_prefix` 是**空串**，
   AstrBot 内置命令**不能带斜杠**（发 `/reset` 只会换来南汐一句"reset是什么指令呀"，
   因为 `CommandFilter` 判的是 `message_str == "reset"`）；发 `reset` 又会被
   "需要 admin" 挡掉（测试小号不是 AstrBot admin）。**最省事的办法**是直接清
   `astrbot/data/data_v4.db` 里该会话的 `conversations.content`：

   ```python
   UPDATE conversations SET content='[]' WHERE user_id='onebot-qq:GroupMessage:<TEST_GROUP_ID>'
   ```

   清完重启 AstrBot，自主调用**立刻恢复**（本机实测）。

3. **工具描述决定模型会不会调用**。描述里必须写死「**只要需要碰到这台机器就必须调用，
   不要回答"我看不到你的电脑"，也不要让用户自己去敲命令**」。**别为了"礼貌"把描述写软。**

4. **顺序是硬要求：先连 SSE 再 POST /message**。`text/delta` 是瞬时事件，
   没有订阅者时永久丢失；反着做会丢掉开头几个 token。
   `GET /events` 还必须带 `?conversation=<UMO>`，否则 HTTP 400。

## 排查

日志里认这几行（插件名 `astrbot_plugin_nanxi_dsh`）：

- `南汐自主调用（<UMO>）：<任务前 80 字>` —— 工具真的被调用了；
- `非主人（<QQ>）尝试调用工具，已拒绝` —— 闸门生效；
- `dsh_task 不在本次请求的工具集里（…）` —— **警告**，说明坑 1 又犯了；
- `注册停止回调失败（这轮任务将无法被 @南汐 stop 叫停）` —— 急停没接上。

想看模型到底拿到了哪些工具、system prompt 追加了什么，把本插件的日志级别调到 DEBUG。

## 源码与部署

- **源码（进 git）**：`<PROJECT_ROOT>\astrbot_plugin_nanxi_dsh\`
- **部署副本（AstrBot 实际加载的）**：`astrbot\data\plugins\astrbot_plugin_nanxi_dsh\`

改完源码要拷过去（`astrbot\` 整个目录被 gitignore，副本不入库），再重启 AstrBot。

## 与星驿（astrbot_plugin_dsh_relay）的关系

本插件**不碰**星驿的任何代码，只在同一套桥接协议上做客户端：

- 星驿：前缀触发（`dsh <指令>`），把过程直接回帖到会话，**没接急停**；
- 本插件：模型自主判断触发，把过程回帖 + 把结果交还给南汐转述，**接了 `@南汐 stop`**。

两者可以共存，共用同一个 DSH 会话。
