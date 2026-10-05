# 教程：让 AUTO-MAS 的通知自动发到 QQ 群（经 AstrBot）

> 面向：**已经跑起 AUTO-MAS、也有 AstrBot（已接入 QQ）**的人。
> 效果：mas 跑完日常后，**自动**往你指定的 QQ 群发一条报告，长这样：
>
> ```
> 09-26 | MAA的自动代理任务报告
>
> 任务开始时间: 2026-09-26 08:00:00, 结束时间: 2026-09-26 08:12:34
> 已完成数: 1, 未完成数: 0
>
> 明日方舟: 08:00 - Success!
> AUTO-MAS 敬上
> ```
>
> 实测环境：Windows + AstrBot v4.2x + AUTO-MAS v5.6.0-beta.1。

---

## 一、原理（先看懂这张图，后面就不会迷路）

```
AUTO-MAS 跑完任务
    │  它自带「自定义 Webhook」：往你指定的网址 POST 一段 JSON
    ▼
AstrBot 的 Open API：  POST http://localhost:6185/api/v1/im/message
    │  （AstrBot 已经用 OneBot 接上了你的机器人 QQ）
    ▼
你的 QQ 群
```

也就是说：**mas 负责"发出来"，AstrBot 负责"转发到群"**，中间用一条 Webhook 连起来。

---

## 二、准备工作

| 需要什么 | 说明 |
|---|---|
| **AUTO-MAS** | 能正常跑任务即可；本文按 v5.6 的界面写（老版本可能没有"自定义 Webhook"） |
| **AstrBot** | **v4.18.0 及以上** —— HTTP API 是从这个版本开始提供的 |
| **已接入 QQ** | AstrBot 里已经用 OneBot v11（NapCat / Lagrange / SnowLuma 等）登录了机器人 QQ |

---

## 三、第 1 步：在 AstrBot 里创建一个 API Key

1. 打开 AstrBot 的 WebUI（默认 `http://localhost:6185`）
2. 进 **设置 → OpenAPI**
3. 点 **创建 API Key**，起个名字，比如 `mas通知`
4. **scope 勾上 `im`** —— 发消息就靠它（只勾 `im` 就是最小权限，够用）
5. 保存后会得到一串以 **`abk_`** 开头的东西，**立刻复制存好**（这类 key 通常只显示一次）

> 这一步是整条链路的前提：**没有 key，后面 mas 发过来的请求会被 AstrBot 拒掉。**

---

## 四、第 2 步：查到你自己 AstrBot 的「平台 ID」

AstrBot 发消息要指明"发给谁"，用的格式叫 **UMO**：

```
<平台ID> : <消息类型> : <会话ID>
   例：onebot-qq : GroupMessage : 123456789
```

**平台 ID 每个人可能不一样**，用这条命令查（把 `abk_xxx` 换成你第 1 步的 key）：

```bash
curl -H "Authorization: Bearer abk_xxx" http://localhost:6185/api/v1/im/bots
```

返回示例：

```json
{"status":"ok","data":{"bot_ids":["onebot-qq"]}}
```

→ 里面那串 **`onebot-qq`** 就是你的平台 ID（**以你实际返回的为准**）。

那么"发到 QQ 群"的 UMO 就是：

```
onebot-qq:GroupMessage:你的群号
```

> `GroupMessage` 是固定写法（群聊）；私聊是 `FriendMessage`。
> 不确定平台 ID 时，千万别照抄本文的 `onebot-qq`。

---

## 五、第 3 步：在 AUTO-MAS 里添加「自定义 Webhook」

1. 打开 AUTO-MAS → **设置 → 通知设置**
2. 拉到 **自定义渠道 → 自定义 Webhook**，点**添加**
3. 按下表填（**四处要改成你自己的**）：

| 字段 | 填什么 |
|---|---|
| 名称 | 随便，如 `mas通知` |
| **Url** | `http://localhost:6185/api/v1/im/message` |
| **Method** | `POST` |
| **Headers** | `{"Content-Type":"application/json","Authorization":"Bearer abk_xxx"}` |
| **Template** | `{"umo":"onebot-qq:GroupMessage:你的群号","message":[{"type":"plain","text":"{title}\n\n{content}"}]}` |

**要改的四处**：`abk_xxx` → 你的 key；`onebot-qq` → 你的平台 ID；`你的群号` → 目标群号；名称随意。

⚠️ 三个注意点：

1. **`Headers` 必须是合法 JSON** —— 就是上面整行，别漏引号、别用中文引号。
2. **配「全局」这一个就够了**。mas 官方文档原话：*"全局通知在 设置 > 通知设置 里配，管所有任务。一般配这一个就够了。"*
   （「用户通知」在「用户配置 → 通知设置」里，是**额外多发一份**、不覆盖全局 —— 一般不需要。）
3. mas 要求接收方返回 **2xx** 才算推送成功；AstrBot 正常返回 200，放心。

---

## 六、第 4 步：测试

1. 在 mas 的通知页面点 **「发送测试通知」**（或这条 Webhook 的测试按钮）
2. 群里应该收到一条测试消息 —— **成功！**

收不到就往下看。

---

## 七、排障：先分清是"哪一头"的问题

**别一上来就怀疑 mas**。先直接用命令打 AstrBot（绕开 mas），就能立刻定位：

```bash
curl -X POST http://localhost:6185/api/v1/im/message \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer abk_xxx" \
  -d "{\"umo\":\"onebot-qq:GroupMessage:你的群号\",\"message\":[{\"type\":\"plain\",\"text\":\"测试\"}]}"
```

- **这条能发到群里** ⇒ AstrBot 侧没问题，去查 mas 的 Url / Headers / Template。
- **这条也发不出去** ⇒ 看下面的表。

| 现象 | 原因 / 怎么解决 |
|---|---|
| `401 Invalid API key` | key 抄错了 / 被删了 → 重新建一个 |
| `403 Insufficient API key scope` | 建 key 时**没勾 `im`** → 重建，勾上 `im` |
| `404 Not Found` | Url 写错（确认是 `/api/v1/im/message`，端口是 6185） |
| `Bot not found or not running for platform` | UMO 里的**平台 ID 不对** → 回第 2 步重查 |
| 连接被拒 / 无响应 | AstrBot 没在运行，或端口不是 6185 |
| **curl 能发，mas 发不出** | ① mas 的 `Headers` 不是合法 JSON；② Url / UMO 填错；③ mas 版本太老没有自定义 Webhook |
| 接口返回 ok，但群里没消息 | ① 机器人 QQ **掉线**了；② 这个群不在 AstrBot 的**白名单**里（`id_whitelist`）；③ 群号写错 |

---

## 八、几个常见问题

**Q：`/api/v1/im/message` 和 `/api/v1/im/messages` 哪个对？**
A：都行，后者是前者的别名。

**Q：一次跑完收到好几条通知，正常吗？**
A：正常。mas 的「代理结果」和「统计信息」是**两次独立通知**，多个脚本/账号会各发一次。
想少收点就在 mas「设置 → 通知设置」里关掉**推送统计信息**。

**Q：机器人会不会把这些通知当成聊天、拿 AI 去处理？**
A：不会。这是 AstrBot 的 **Open API 直接发消息**，不经过对话/AI 流程。

**Q：AstrBot 没开的时候会怎样？**
A：通知发不出去（mas 侧会记一条失败），但**游戏任务照常跑**。想让通知稳定，AstrBot 保持常开。

**Q：模板里还能写什么？**

| 变量 | 含义 |
|---|---|
| `{title}` | 报告标题，如 `09-26 \| MAA的自动代理任务报告` |
| `{content}` | 报告正文（**末尾自带 `AUTO-MAS 敬上`**） |
| `{datetime}` / `{date}` / `{time}` | 当前时间 |
| `{gamedate}` | 游戏日（东四区） |

比如想在末尾加时间，就把 `text` 写成：
`{title}\n\n{content}\n\n（{datetime}）`

> 注：那句 `AUTO-MAS 敬上` 是 mas **自己拼在正文里的**，模板去不掉（除非自己在中间加一层转发程序处理，一般没必要）。

---

## 九、一页速查（配好后想改就照这个）

```
AstrBot 侧：设置 → OpenAPI → 创建 API Key（勾 im）   →  得到 abk_xxx
            查平台ID：curl -H "Authorization: Bearer abk_xxx" \
                      http://localhost:6185/api/v1/im/bots

mas 侧：设置 → 通知设置 → 自定义渠道 → 自定义 Webhook
        Url      http://localhost:6185/api/v1/im/message
        Method   POST
        Headers  {"Content-Type":"application/json","Authorization":"Bearer abk_xxx"}
        Template {"umo":"<平台ID>:GroupMessage:<群号>",
                  "message":[{"type":"plain","text":"{title}\n\n{content}"}]}
```

---

*依据：AstrBot 官方文档 [HTTP API](https://docs.astrbot.app/dev/openapi.html)（"设置 → OpenAPI → 创建 API Key"、`POST /api/v1/im/message`）；AUTO-MAS 官方文档 [通知](https://doc.auto-mas.top/docs/advanced-features/notification.html)。*
