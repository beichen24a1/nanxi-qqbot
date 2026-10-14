# 南汐 · QQ 猫娘机器人

一只跑在 QQ 上的猫娘机器人「南汐」。说人话的部分交给大模型，**真动手**的部分交给一个本机 agent
—— 她能读文件、跑命令、开浏览器，然后把结果用自己的口气讲出来。

这个仓记录了她从零搭起来、一路踩坑的全过程。

> **当前状态：精简模式。** AI 聊天与群聊图片描述已关闭，保留「摸头生成」「网易云点歌」和主动通知通道。
> 当前运行口径与安全关闭脚本，见 [AGENTS.md](AGENTS.md) 文首；日常维护见 [维护笔记.md](维护笔记.md)。

## 架构与当前运行范围

当前 QQ 交互在 AstrBot 插件内完成；DSH 接受任务的箭头是保留的历史能力，当前暂停。DSH 主动通知与 mas Webhook 直接调用 AstrBot im 接口。

```
QQ 群（@南汐）
   │
   ▼
SnowLuma（Docker 容器）        QQ 登录 / 协议端，转成 OneBot v11
   │  OneBot 反向 WebSocket
   ▼
AstrBot（Python 进程）         聊天大脑：人格、白名单、function calling
   │  星驿桥接（HTTP + SSE，插件跑在 DSH 进程内）
   ▼
DSH（DeepSeek Harness）       她的"手"：读写文件、跑命令、开浏览器
```

## 这个仓里有什么

| 想看的 | 去哪 |
|---|---|
| **接手必读**（当前状态 + 全部踩坑，含证据） | [AGENTS.md](AGENTS.md) |
| 三层的部署与启停 | [部署说明-南汐QQ机器人.md](部署说明-南汐QQ机器人.md)、`启动/` |
| 她自己的浏览器（纯 Python 驱动 Chrome CDP，不用 playwright） | `astrbot_plugin_nanxi_dsh/browser.py` |
| DSH 桥接（星驿） | `dsh插件/` |
| 摸头生成 | `astrbot_plugin_petpet/` |
| 一步步做出来的过程 | `计划-*.md`、`复盘-*.md`、`更新记录.md` |
| 测试小号 / 自动化验收 | [南汐测试bot-使用说明.md](南汐测试bot-使用说明.md)、`tools/nanxi-test.ps1` |

## 本地验证

```powershell
python tools/shutdown_nanxi_ai.py --dry-run
python tools/test_lite_config.py
python tools/test_card_parse.py
node tools/test_relay_session_title.mjs
```

关闭脚本保留摸头和点歌，并一并关闭图片描述；默认预览，实际写入前必须先停 AstrBot，支持 `--config` 指定配置路径。
两个启动入口共用 ffmpeg 探测，避免“重启能发语音、下次一键启动却不能”。

## 保留的历史技术实现

- **她的"手"不在自己进程里**：AstrBot 只管聊天；真要动文件、跑命令时，通过一个
  **跑在 DSH 进程内**的桥接插件把活投给本机 agent —— 不碰 DSH 的 Web API，也就绕开了它的认证体系。
- **浏览器是自己写的**：纯 Python 打 CDP（HTTP `/json/list` + WebSocket 发
  `Page.navigate` / `Runtime.evaluate` / `Page.captureScreenshot`），**零新依赖**
  （复用 AstrBot 自带的 aiohttp，它自带 `ws_connect`）。截图会**同时**发给用户和回给模型自己，
  所以她"亲眼看得见"页面。
- **点击是照 `dsh-ego-browser` 抄的**：真鼠标事件（`Input.dispatchMouseEvent`，跟 Playwright 一样，
  不用 JS 的 `el.click()`）＋ `elementFromPoint` 命中测试 ＋ 按文字取"最内层元素"
  （Playwright `text=` 的语义）。`tools/click-fixture.html` 是配套的离线复现件。
- **陪她调试踩过的坑**（每条都有实测证据，见 AGENTS.md）：Chrome 的单例交接让"进程还活着吗"
  这个判据失效、模型会"学着演"上下文里出现过的失败、技能白名单写成 `[]` 等于一个工具都不给
  …… 都写下来了。

## 想一起开发？

- **先读 [AGENTS.md](AGENTS.md) 文首那一节** —— 当前状态、怎么启停、哪些坑已经踩过，
  能省你大量时间。它是给"接手的人（或 AI）"写的。
- **本仓不含任何凭据**，也**不含你需要的真实 QQ 号 / 群号**：文档里一律是
  `<BOT_QQ>` / `<OWNER_QQ>` / `<TEST_GROUP_ID>` 这类占位符；代码里的号码改成从**环境变量**读
  （如 `NANXI_BOT_QQ`、`NANXI_OWNER_QQ`、`NANXI_TEST_GROUP`），没设就用示例值。
- **跑起来需要本地环境**：Docker（SnowLuma）+ AstrBot + DSH，还有 QQ 登录态。
  `astrbot/`、`snowluma/` 这些上游本体按 `.gitignore` 不入库，要自己按 `部署说明-*.md` 装。
- **改 AstrBot 插件后必须重启 AstrBot**（工具的 docstring 只在启动时读一次）；
  **改 `astrbot_plugin_nanxi_dsh/` 记得同步部署副本** `astrbot/data/plugins/` 下的那份。
- 提交信息用中文、按 `fix(范围): 说明` 的格式，和现有历史保持一致。

## 说明

- 完整开发仓保留历史；公开分享仓从脱敏快照起步，两者独立维护。凭据、运行数据和旧历史不随文件同步公开。
- 个人项目，代码以"能跑起来"为准，不追求工程完备。
