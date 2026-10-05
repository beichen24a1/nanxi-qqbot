# dsh-qq-notify（= 改造后的 DSH 插件 `dsh-email-notify`）

> **本目录只是"源码存档副本"**，不是插件真正运行的位置。真正被 DSH 加载的是：
> `<DSH_WORKSPACES>\dsh\plugins\dsh-email-notify\`
> （DSH 的 web profile `%USERPROFILE%\.dsh\profiles\web\package.json` 里以
> `"dsh-email-notify": "link:<DSH_WORKSPACES>/dsh/plugins/dsh-email-notify"` 链接过去。）
>
> 之所以复制一份到本仓库：原始插件目录**不在任何 git 仓库里**，DSH 升级/重装时容易被覆盖回"发邮件版"，此处留底便于随时还原。

---

## 1. 它做了什么

把原插件"任务完成后发**邮件**"改造成"任务完成后发 **QQ 消息**"：

- 注册工具 **`notify_owner(message)`**（原 `send_email` 已不再使用，SMTP 代码保留但不被调用）；
- 调用时 `POST http://127.0.0.1:6185/api/v1/im/messages`，`Authorization: Bearer <im_scope_key>`，
  body：`{"umo":"onebot-qq:GroupMessage:<TEST_GROUP_ID>","message":[{"type":"plain","text":"..."}]}`
  → 由 AstrBot 让机器人（南汐 QQ `<BOT_QQ>`）**主动发到群 `<TEST_GROUP_ID>`**；
- 同时挂一段系统提示词（section 名 `dsh-qq-notify`），告诉模型：**任务真正完成、要给用户最终结论时**才调用 `notify_owner`，不要在中间步骤反复发。

## 2. 配置（密钥不写进代码）

读 **`%USERPROFILE%\.dsh\dsh-qq-notify.json`**（每次调用时读，改完无需重启即对新调用生效）：

```json
{
  "astrbot_url": "http://127.0.0.1:6185",
  "im_api_key": "abk_……（AstrBot 的 im scope key，见 游戏通知/config.json）",
  "umo": "onebot-qq:GroupMessage:<TEST_GROUP_ID>"
}
```

- `umo` 格式 = `<平台id>:<MessageType>:<id>`；群用 `GroupMessage`，私聊用 `FriendMessage`
  （**没有** `PrivateMessage` 这个值，写错会 HTTP 400）。
- 平台 id 当前是 `onebot-qq`（见 `astrbot\data\cmd_config.json`）。
- 配置缺失时工具会直接报错提示路径，不会静默失败。

## 3. 改完怎么生效

插件是宿主侧 Node 模块，**热更新不生效**，必须**重启 DSH（web profile）**，新会话才会加载新代码与新的系统提示词。
（重启前已开的会话仍用旧提示词。）

## 4. 快速自检

```powershell
# 1) 语法检查（ESM，先复制成 .mjs 再 check）
Copy-Item "<DSH_WORKSPACES>\dsh\plugins\dsh-email-notify\index.js" "$env:TEMP\t.mjs" -Force
& "C:\Program Files\nodejs\node.exe" --check "$env:TEMP\t.mjs"

# 2) 直接验证发送链路（等价于工具干的事；密钥从 游戏通知\config.json 读，不在脚本里）
<PROJECT_ROOT>\venv312\Scripts\python.exe <PROJECT_ROOT>\发送qq通知.py "自检：链路正常"
#    成功 → HTTP 200，群里应立刻看到那条消息
```

## 5. 若被 DSH 升级覆盖了怎么办（还原）

```powershell
Copy-Item "<PROJECT_ROOT>\dsh插件\dsh-qq-notify\index.js"        "<DSH_WORKSPACES>\dsh\plugins\dsh-email-notify\index.js" -Force
Copy-Item "<PROJECT_ROOT>\dsh插件\dsh-qq-notify\package.json"    "<DSH_WORKSPACES>\dsh\plugins\dsh-email-notify\package.json" -Force
Copy-Item "<PROJECT_ROOT>\dsh插件\dsh-qq-notify\cordis.patch.yml" "<DSH_WORKSPACES>\dsh\plugins\dsh-email-notify\cordis.patch.yml" -Force
# 然后重启 DSH
```

---

*维护：DSH ｜ 2026-09-12 ｜ 与 `AGENTS.md`、`南汐自主智能体-目标与路线图.md` 中的"DSH 任务完成通知通道"一节保持一致。*
