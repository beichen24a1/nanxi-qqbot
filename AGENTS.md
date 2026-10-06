# AGENTS.md — 南汐 QQ 机器人项目对接手册（给下一个模型）

> 这是本项目给**新接手的 agent/模型**的速读手册。花 5 分钟读完，能省下大量"考古"时间。
> 口径以本文档为准。其它文档若与本文档冲突，**一律以本文档为准** —— `部署说明-南汐QQ机器人.md`
> 与 `南汐自主智能体-目标与路线图.md` 属早期产物（已部分过时，2026-09-18 做过一轮修正），
> `调研报告-南汐QQ机器人.md` 只是选型留档。

---

## 🚨 最新状态（2026-10-03 全面勘察，接手先读这一节）

**🛑 2026-10-05（最新，最优先读）：南汐已切到【精简模式】—— AI 聊天关闭，只留「摸头」+ 通知通道。**

- **主人拍板**：「没招了，效果一直不好，先关掉吧」，随后明确保留三样：
  **① 摸头生成**（`astrbot_plugin_petpet`）、**② DSH/我能用南汐账号主动发通知**
  （`notify_owner` → AstrBot 的 `im/messages`）、**③ mas 的游戏通知走南汐账号**。
  其余能力（人格聊天、`dsh ` 前缀、联网搜索、那 17 个工具）**全部停止生效**。
- **怎么关的（两个配置项，零文件改动）** —— `astrbot\data\cmd_config.json`：
  1. `provider_settings.enable = false` —— AstrBot 官方的**"不启用 AI 能力"总开关**。
     `core/pipeline/process_stage/stage.py:53` 与 `.../method/agent_request.py:37` 都判它，
     为 False 时只打一行 debug 日志然后 `return`，**不报错、不刷屏**。
  2. `plugin_set = ["astrbot_plugin_petpet"]` —— 官方**"插件集"**，语义是
     **"哪些插件注册的消息 handler 会被激活"**（`core/pipeline/waking_check/stage.py:158-170`
     拿它给 `get_handlers_by_event_type(..., plugins_name=…)`；`["*"]` = 全部启用）。
     于是 `dsh `（星驿）、`搜索`（anysearch）、内置命令**全部不再响应**。
- **⚠️ 生效边界（别误解，也别"帮忙加载不成功"）**：`plugin_set` **不阻止插件加载** ——
  启动日志里四个插件照旧加载、17 个工具照旧注册（`plugins: 17 llm tools registered`）。
  **是"不响应"，不是"不加载"。** 真正让聊天没反应的是 `provider_settings.enable=false`。
- **✅ 实测验收（2026-10-05 14:03~14:04，测试群 `<TEST_GROUP_ID>`）**：
  `@南汐 你今天心情怎么样喵` → 消息**进了** AstrBot（`core.event_bus` 有记录）→ **之后什么都没有**；
  `@南汐 摸摸头` → 进事件 → 0.6 秒后 `respond.stage: Prepare to send - [图片]`（**出图**）。
  全场 `Prepare to send` **只有摸头那一次**、`Agent 使用工具` **0 次** ⇒ LLM 一次都没跑。
  `notify_owner` 实测**仍能发到群**（以 `<BOT_QQ>` 发）⇒ 通知通道不受影响。
- **一键关停脚本**：`C:\Python310\python.exe tools\shutdown_nanxi_ai.py --dry-run|--apply`
  （幂等；**发现 6185/3002 还在监听就拒绝执行** —— 必须先停 AstrBot，否则它退出时会用内存里
  那份覆盖你的改动；`--apply` 自动把配置备份到 `_backup\20261005\`）。
- **怎么恢复（就两行）**：`provider_settings.enable = true` + `plugin_set = ["*"]`，重启 AstrBot。
  配置备份：`_backup\20261005\cmd_config.json.bak-before-ai-off-20261005-140322`。
- **☠️ 教训（2026-10-05 我自己踩的，务必记住）**：主人说「**先关掉**」，
  我却用 `Move-Item` 把三个插件目录搬去了 `_disabled_plugins\` —— 他立刻质问
  「**怎么直接删了，不是让你停吗？我还想推到远端 github 上呢**」。
  **「停」= 配置层面不生效，不是动文件系统。** 后来已全部搬回原位（`main.py`/`browser.py`/
  `metadata.yaml` 哈希与仓库根源码一致、`chrome-profile` 1277 文件 / 195 MB 登录态完整）。
  ⇒ 以后遇到"停用／关掉／禁用"，**先找官方配置开关**（`plugin_set`、`provider_settings.enable`
  这类），配置确实做不到时才动文件，而且**动之前先问一句**。
- **推送 GitHub 前的体检口诀**（本次实测有效）：`git count-objects -vH` 看体积、
  `git ls-files | Select-String '凭据|credential|secret|\.env|token|\.key$|\.pem$|\.db$|password'`
  扫敏感文件、再看 `git check-ignore -q <关键路径>` 是否都 ignored。
  本次结果：158 文件 / 233 KiB、无敏感文件、无大文件、`astrbot/`+`_backup/`+`logs/`+
  `本地凭据-勿入库.md` 全数忽略 ⇒ **可安全推公开仓**。
  ⚠️ 但本仓**没有配 remote**（`git remote -v` 为空），要推得先 `git remote add origin <url>`。
  ⚠️ **光按文件名扫是不够的** —— 本次真去扫**内容**，才发现 **7 处真凭据**（不是占位符）：
  `_scripts_archive/` 里 5 个脚本硬编码的 **AstrBot 仪表盘密码明文**，以及
  `南汐测试bot-使用说明.md` 与 `启动/恢复测试bot.ps1` 里的 **VNC 密码**。
  ⚠️ **`_scripts_archive/` 有 67 个文件早在库里** —— `.gitignore` 里虽然写了它，
  但**对已跟踪文件无效**（gitignore 只管未跟踪的）。这是最容易漏的一类。
  正解：`python tools\redact_secrets.py --secret "明文=占位符" [--apply]`
  （它**刻意不内置任何明文** —— 第一版我把两个密码写进了它的 `REPLACEMENTS` 字典，
  那等于"脱敏工具自己就是泄漏源"，一提交就白干；凭据只能从 `--secret` 或仓外的
  `--secrets-file` 进来）。它会保持 `.ps1` 原有的 **UTF-8 BOM** 状态。
  ⚠️⚠️ **只改当前文件远远不够：git 历史里还带着原文。**
  `git log --all -S "<串>" --oneline` 能查出哪几笔提交带毒 ——
  本次那个 VNC 密码出现在 4 笔提交、仪表盘密码出现在 init 提交 `c8ffd3c`。
  ⚠️ **写文档时最容易手滑**：本节第一版我把密码**原样写进了文档**，是提交后复查才抓到的
  （自查时又违反了一次"入库文档绝不写明文凭据"）。⇒ **顺序必须是「先扫、再提交」**：
  `git grep -n -I -E '<凭据串>' -- .` 在 `git commit` **之前**跑，别提交完才扫。
  ⇒ **推公开仓要用「干净单提交」导出**（原仓历史原地完整保留，两头都不亏）：
  ```powershell
  git archive --format=zip -o "$env:TEMP\share.zip" HEAD   # 只含被跟踪的内容
  Expand-Archive "$env:TEMP\share.zip" -DestinationPath <SHARE_REPO>
  cd <SHARE_REPO>; git init -b main; git add -A; git commit -m "..."
  gh repo create <名字> --public --source=. --push
  ```
  **别直接 `git push` master** —— 那样历史里的明文密码会一起公开，别人
  `git log -p` 一翻就有。（`git archive` 的好处：它**精确等于 HEAD 的被跟踪文件**，
  绝不会顺手带上 `astrbot/`、`_backup/`、`logs/` 那些。）
  ✅ **2026-10-05 已按这个流程推成功**：**https://github.com/beichen24a1/nanxi-qqbot**（公开）。
  实测记录与两个细节：
  1. **本地工作副本在 `<SHARE_REPO>`**（已配好 `origin`）—— 以后要更新分享仓，
     在**那里**改并推，别再从原仓导一次（原仓是"含历史的完整开发仓"，两者定位不同）。
  2. **`_scripts_archive/` 那 67 个文件没进分享仓** —— 因为分享仓是**全新仓**，
     `.gitignore` 这次**真的生效**了（在原仓里它们"已跟踪"所以挡不住，在新仓里是全新文件
     所以挡得住）。这反而更干净：那些一次性配置/抓取脚本本来就不该入库。
     于是分享仓 = **96 个文件**（工作区 163 个），推上去的正是项目本体。
  3. **署名用 GitHub 的 noreply 邮箱**保护真实邮箱：
     `git -c user.name="北晨" -c user.email="262405272+beichen24a1@users.noreply.github.com" commit …`
     （`262405272` 是 `gh api user --jq .id` 拿到的账号 id，前缀它提交才会关联到账号）
  4. **推完必做的一致性验证**：`git rev-parse "HEAD^{tree}"` 与
     `gh api repos/<owner>/<repo>/commits/main --jq '.commit.tree.sha'` **必须相等** ——
     相等才证明"远端的字节 = 你本地扫过的那份"。本次两边都是 `71f231002bce…` ✓
  ⚠️ 分享仓里**仍然包含**机器人 QQ、主人 QQ、群号等（AGENTS.md 与各文档里到处都是）——
  这是主人知情的分享内容，但**下一个接手的人别再往里加更多个人信息**。

  ⚠️⚠️ **脱敏/改脚本时顺带踩的两个 PowerShell 坑**（都是"动一下就坏"，记牢）：
  1. **`$x = if (...) { ... } else { ... }` 是 PowerShell 7 语法，Windows PowerShell 5.1 上不成立** ——
     变量会**静默变成空**，不报语法错。本项目 `tools/nanxi-test.ps1`、`启动/恢复测试bot.ps1`
     都要求 5.1 兼容，必须写成两步：
     `$x = $env:FOO; if (-not $x) { $x = '默认值' }`。
     症状极隐晦：报 `onebot_.json: No such file or directory`（因为插值成了空串）。
  2. **原本 ASCII-only、没有 BOM 的 `.ps1`，一旦加入中文注释就会在 5.1 下解析异常。**
     本次现象很怪：**报错行号比实际行号少 4 行**，脚本行为完全不对（`$TestBotUin` 读成空）。
     修法：`[System.IO.File]::WriteAllText($p, $text, (New-Object System.Text.UTF8Encoding($true)))`。
     ⇒ **给这类脚本加中文注释时，顺手把 BOM 一起加上**（判据：`ReadAllBytes()[0..2]` 是不是 `239,187,191`）。

**✅ 2026-10-06：新功能【网易云点歌】—— @南汐（并引用一条含链接的消息，或直接把链接发给她），歌就发进群。**

- **两种触发方式**（都实测过）：① **引用**一条含网易云链接的消息 + `@南汐` —— 纯文本分享、
  QQ 的**音乐卡片**（`com.tencent.music.lua`）都认；② **直接 @**：`@南汐 https://music.163.com/song?id=…`，
  不用引用。取链接的优先级是「先看被引用的那条，没有可用的再看本条」（`event.message_str` 是摘掉 At 段后的纯文本）。

- 代码在 `astrbot_plugin_netease_pick\`（仓库根；部署副本在 `astrbot\data\plugins\`，**改完要同步 + 重启**）。
  ⚠️ **它必须列进 `plugin_set` 才会响应** —— 新工具
  `python tools\plugin_set.py --add <插件名> --apply`（**先停 AstrBot**，它内存里握着配置）。
- **七个坑的完整说明写在插件自己的 `main.py` docstring 里，改这个插件前先读它。**
  最容易栽的三个：
  ① 下载**必须带浏览器 UA**（默认 UA 会被网易云回 83 字节的 `{"code":-460,…网络环境存在风险}`）；
  ② **HTTP 200 完全不可信** —— 歌不存在时是 `200 + text/html` 的 104 KB 404 页面，
     必须**三判据一起卡**：`Content-Type` 是 `audio/*` + 最终 URL 落到 `music.126.net` + 体积 > 200 KB；
  ③ **`async def` 处理器里"多次 `yield` + 中间干活"会被静默截断** —— AstrBot 在 `stop_event()`
     之后**不再迭代生成器**，于是"收到喵"发出去了、后面的下载**一行没跑且不报错**。
     中间反馈要用 `await event.send(MessageChain([...]))`，**最后只 yield 一次**（petpet 那种形态）。
- **路线是主人指定的官方外链**：`http://music.163.com/song/media/outer/url?id=<歌曲ID>.mp3`
  —— 零依赖、免 key、免登录，不会因第三方服务挂掉而失效；代价是**拿不到 VIP / 版权受限的歌**。
  社区那三个点歌插件（`Aoi-Karlin/…_pro_max`、`Dayanshifu/astrbot_plugin_music_pro`、
  `ApproLight01/astrbot_netease_mus`）**2026-10-06 调研后都没用**：它们全是"搜歌名 → 第三方 API"路线，
  分别要自建 API 服务 + Cookies / 注册 API key + 公开音源站 / 只解析不下载（详见插件 docstring）。
- ⚠️ **语音（`Record`）依赖宿主机 ffmpeg**：AstrBot 发语音前会 `ensure_wav()` 转码，
  它只从 PATH 找 `"ffmpeg"`，宿主机原本没装 ⇒ `Exception: ffmpeg not found`。
  已 `winget install Gyan.FFmpeg`，并在 **`启动\restart-astrbot.ps1` 里加了 PATH 探测** ——
  因为 winget 写的是**注册表** PATH，而 DSH 及其子进程继承的是**旧环境**，
  必须显式 prepend `%LOCALAPPDATA%\Microsoft\WinGet\Links`。
- **默认【语音 + mp3 文件】两个都发**（配置 `send_as` 默认 `record,file`，填单个就只发那个）。
  两条路原理不同：**语音**走 AstrBot 的 `Record` 组件（适配器读**宿主机**文件转 base64 内联，
  与容器无关）；**mp3 文件**走 OneBot 的 `upload_group_file`（读**容器内**路径，所以要先 `docker cp`）。
  ⚠️ **群里顺序固定是「文件在上、语音在下」，这是被框架逼出来的** —— 语音必须走
  **最后一次 `yield`**（`yield` 之后框架就不再执行后续代码了，见坑 ③），所以文件只能在它之前 `await` 发完。
  ⚠️ **别用 AstrBot 的 `File`（群文件）组件**：它的 `file` 是 property，会在 **AstrBot 本机**
  查 `os.path.exists()`，而 SnowLuma 容器的挂载**全是命名卷**、没有绑定宿主目录 ⇒ 必然失败。
- **文件名里的歌名有两个来源**（按优先级）：① **卡片里有就挖卡片的** —— `meta.music.title` + `desc`
  ⇒ `兄弟难当 - 杜歌.mp3`；② **没有卡片（直接 @ 就是这种）**就去读歌曲页的 `<meta property="og:title">`
  ⇒ `直到大地变成一颗酸橙.mp3`（服务端渲染、免登录，2026-10-06 实测 200 / 135 KB）。
  ⚠️ ②是**纯尽力而为**：任何异常都静默降级成歌曲 id，**绝不能因为"起名字"失败把下好的歌吞掉**。
  ⚠️ 文件名统一过一遍 `re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", …)`（Windows/QQ 不接受的字符）。
- **实测验收（2026-10-06 00:43，测试群 `<TEST_GROUP_ID>`）**：小号发 `https://163cn.tv/bhu1nHlF`
  → 引用它 + @南汐 → 日志 `短链解析…id=3410744228` / `下载完成 3673005 字节` / `已用语音发出`，
  群里出现 `[record]`；ffprobe 确认下载到的是完整一首歌（`duration=229.5 秒`、`128 kbps`、`mp3`）。
- **实测验收 · 卡片式（2026-10-06 12:35，主人截图）**：小号**引用**群友的 `[分享]兄弟难当` 音乐卡片
  + @南汐 → 南汐 `收到喵，去找这首歌…` → `兄弟难当 - 杜歌.mp3`（3.84 MB）+ **4'12"** 语音，两条都进群。
  ⇒ 卡片路径（`data.data` 里再套一层 JSON 字符串那种形态）**确认可用**。
- **实测验收 · 直接 @（2026-10-06 12:53 / 12:55，测试群 `<TEST_GROUP_ID>`）**：小号发
  `@南汐 https://music.163.com/song?id=3413072220&uct2=…`（**不引用**）→
  日志 `链接来源=本条  组件=['At', 'Plain']` / `下载完成 3847725 字节` / `已发出 mp3 文件`；
  群里 `[file]{name=直到大地变成一颗酸橙.mp3}` + `[record]` 各一条，**顺序仍是文件在上、语音在下**。
  ⇒ 两条触发路径、两个歌名来源**都跑通了**。
- ☠️ **坑（2026-10-06 抓到，静默得可怕）：插件配置必须从 `__init__` 的【第二个参数】拿。**
  AstrBot 把**本插件**的配置对象（`data/config/<插件名>_config.json`）作为 `config` 注入
  `Main(context, config)`；而 `self.context.get_config()` 返回的是**全局**配置，
  里面**没有**本插件的段 —— 于是 `_cfg()` 每一次读都落进 `except`/默认值分支，
  **永远返回代码里的默认值，且不报任何错**。症状与"配置没保存"一模一样：
  配置文件写着 `send_as: "file"`，群里却照样收到「语音 + 文件」两份。
  正解（照 `astrbot_plugin_anysearch` / `astrbot_plugin_nanxi_dsh` 的写法）：
  ```python
  def __init__(self, context: star.Context, config=None) -> None:
      super().__init__(context)
      self.config = config or {}
  ```
  ⚠️ 排查这类"配置不生效"的第一件事：**看插件是不是只接了 `context`**。
- **`container` 现在留空 = 跳过 `docker cp`、直接传路径**（2026-10-06 通用化，为开源做准备）。
  配了就 `docker cp`（本项目配的是 `snowluma`，所以行为不变）；留空则直接把宿主机路径交给协议端 ——
  这是给「AstrBot 自己也跑在容器里」（官方 Docker Compose 部署，容器内没有 `docker` CLI）
  或协议端与 AstrBot 共享挂载卷的场景用的。新增 `enable` 现在**真的**能关掉点歌（之前那个字段没人读）。
  ⇒ 判据性实测：把 `container` 的代码默认值改成空串后重启，日志里**没有**出现
  「未配置 container，直接把路径交给协议端」⇒ 说明配置确实读到了 `snowluma`，修复生效。
- **这个插件已单独开源**：**https://github.com/beichen24a1/astrbot_plugin_netease_pick**（MIT）。
  本地工作副本在独立目录（不在本仓里）—— 它是**插件本体**仓，只有
  `main.py` / `_conf_schema.json` / `metadata.yaml` / `README.md` / `LICENSE` /
  `requirements.txt` / `tests/`，给别人直接 `git clone` 到 `AstrBot/data/plugins` 就能装。
  ⚠️ 本仓与插件仓的 `metadata.yaml` **刻意保持一致**：`repo` 都指向**插件仓自己**
  （它的根目录就是插件，AstrBot 能直接 clone 装；指向本仓的话根目录不是插件，装不上），
  `author` 是 GitHub 用户名。改动插件时**两边都要同步**。
  ⚠️ 插件仓的测试在 `tests/test_parse.py`（本仓里同名脚本在 `tools/test_card_parse.py`），
  路径做成了自适应的：`main.py` 在旁边就用当前目录，否则退回 `astrbot_plugin_netease_pick/`。

**DSH 已升级到 `0.2.0-rc.2`，给 Web 全面加了认证 ⇒ `/dsh` 当前【已失效】。**

- **症状**：任何 DSH API 调用都返回 **HTTP 401**（`/api/workspace.list`、`/api/session.create`…
  连 `GET /` 都是 `dsh web authentication required; reopen the URL printed by dsh web.`）。
- **根因（两层）**：
  1. DSH 0.2.0 要求**签名会话 Cookie**：`dsh web` 启动时打印带一次性 token 的 URL，用 token 换 Cookie
     （`dsh-auth-*`，HttpOnly / SameSite=Strict），此后**所有 API / RPC / WebSocket 请求都要求它**；
  2. 我们的 `dsh_cli.js` 用的是 `qq-bridge` 里的**旧客户端**（`dsh-host-apiproxy@0.1.1-rc.2`），
     而 **`dsh-host-apiproxy` 这个包在 0.2.0 里已经不存在**（API 层换成了 `dsh-api-gateway` /
     Typert Remote 体系）。
- **⚠️ 不要从日志抓 token**：启动 token 自 0.1.7 起**只存在内存**（`processLaunchToken()` 随机数，
  不落盘、不可推导），`~/.dsh/guard/logs/server-*.out.log` 里是**上一个进程的陈旧 token**，
  拿它换 Cookie 一律 401。（本项目 2026-10-03 勘察时先踩了这个坑。）
- **正解**：用本机**持久化签名密钥离线铸造 Cookie** ——
  `discoverDshSessionCookie(baseUrl)`（实现于 `qq-bridge` 上游 `src/dsh-client.js`），
  密钥来源 `~/.dsh/.credentials.yaml` 的 `client-connection/browser-session`。
- **0.2.0 的协议也变了**（不止认证）：`POST /api/<endpoint>`，信封
  `{ type:'client-request', rpcId, method, payload:{ args } }`；
  流端点由 `/api/events.mux` 改为 **`/api/remote.mux`**（WebSocket，带 cookie）。
- **现成轮子**：`qq-bridge` 上游已发布 **`v0.2.0-r3`（专门适配 0.2.0-rc.2）**，
  本地还停在 `c9e1f27`（0.1.x 世代）——**这就是修复 `/dsh` 的路径**。
- 详细勘察：`环境勘察报告-20261003.md`｜下一步方案：`计划-南汐与DSH分层协作.md`。

**✅ 2026-10-03 晚：星驿（astrdsh-relay）链路【已端到端打通】—— 这是南汐用 DSH 的正式路径。**

> 上面那套 `/dsh`（自建插件 + `dsh_cli.js` + DSH Web API）**不再是主力**；星驿走的是另一条腿，
> 所以它**完全不受 0.2.0 认证问题影响**。

- **为什么它不用 Cookie**：星驿的 DSH 侧是一个**跑在 DSH 进程内**的 cordis 插件
  （`dsh-astrbot-relay`，由 `~/.dsh/profiles/web/package.json` 引入），它**自己**在
  `http://127.0.0.1:3080/astrbot-relay/*` 上开端点，并在**进程内**把消息投给 agent ——
  全程不碰 DSH Web API，只用自己那份 `bridge_token`。
- **握手要求**：两侧 `bridgeVersion` 必须都 = **7**（当前 AstrBot 侧插件 0.9.7），
  不匹配**拒绝启用**（不是降级）；`allow_insecure_http=true` 必填（环回明文 HTTP 否则被拒）。
- **闭环实测（2026-10-03 22:1x，测试群 `<TEST_GROUP_ID>`）**：
  `@南汐 dsh 只回复八个字：星驿链路已连通` → 群里 **4 秒**收到 `星驿链路已连通`。
- **流式是真的**：星驿把 DSH 的 `text/delta` 按 `throttle_ms=2500` / `flush_chars=200` 分片
  **边写边发**（实测一篇 400 字短文在群里呈现为**三条渐进消息**），最后再补一条收敛回帖。
- **⚠️ 最容易踩的坑：星驿【不】在后台常驻消费 SSE。** `queue` 是 `_handle_task()` **内部**的
  局部队列（`main.py:1229`），每条 QQ 消息**现连一次** SSE，且顺序是硬要求
  （**先连 SSE 再 POST /message**，反了会永久丢掉开头的 `text/delta`）。
  ⇒ **绕过 AstrBot 直接 `POST /astrbot-relay/message` 是无效的**：DSH 会照常跑完、SSE 也照常推帧，
  但**没有 QQ 事件在消费那条队列**，群里一个字都不会有 —— 这**不是 bug**
  （本项目 2026-10-03 据此误判过一次，白查了半天）。
- **`GET /astrbot-relay/events` 必须带 `?conversation=<UMO>`**，否则 **HTTP 400**
  （`{"error":{"code":"unsupported","message":"缺少 conversation 查询参数…"}}`）。
- **触发方式**（`main.py:1083-1093`）：消息**以 `trigger_prefix`（当前 `dsh `，注意尾空格）开头**
  ＋ 发送者通过 `allow_from`。**没有**旧 `/dsh` 插件的 `_invoked_by_at_bot()` 闸门 ——
  @ 不 @ 都行（被 @ 时 AstrBot 已把开头的 At 段从 `message_str` 摘掉）。
- **`allow_from` 填法**（`allowlist.py`，比旧文档宽松得多）：`*` 全部 ／
  **纯 QQ 号 = 发送者本人（私聊群聊都算）** ／ `user:<qq>` ／ `group:<群号>` ／
  **`group:<群号>@<qq>`（只许某人在某群）** ／ `umo:<platform>:<type>:<id>`（精确 UMO）。
  空列表 = 全部允许；**被挡下会记一行 INFO**（不再静默失败）。
- **审批（`dsh approve <code>` / `dsh reject <code>`）没有独立的 owner 闸门** ——
  能批的人 = 能在该会话发出 `dsh ` 的人 = `allow_from` 命中者。
  但 **code 按 `(unified_msg_origin, code)` 绑定**（`main.py:1867`），**别的群/私聊拿到 code 也批不了**，
  所以默认配置（`allow_from=["<OWNER_QQ>"]`）下「**仅主人可批**」成立。
  ⏳ 审批链路本身（DSH 主动请求提权 → 转述 → 回执）**尚未实测**：需要 DSH 侧 approval policy 为 `ask`，
  当前是 `never`。
- **本项目当前白名单**（`astrbot\data\config\astrbot_plugin_dsh_relay_config.json`，该文件 gitignore）：
  `["<OWNER_QQ>", "group:<TEST_GROUP_ID>@<TEST_BOT_QQ>"]` —— 第二条是**专为自动化验收开的窄口子**
  （只在测试群、只许测试小号），让星驿链路的端到端回归能被 agent 自动跑；
  ⚠️ 代价是**测试小号在该群里也能批准审批**。不想要就删掉它（改完必须重启 AstrBot）。
  备份：`_backup\20261003\astrbot_plugin_dsh_relay_config.json.bak-before-test-allowlist`。

**✅ 2026-10-03 深夜：南汐【自主判断】调用 DSH 打通 —— 新插件 `astrbot_plugin_nanxi_dsh`。**

> 这是"南汐是主 agent、DSH 是执行子代理"这个定位**第一块真正落地的拼图**：
> 不再需要用户手打 `dsh ` 前缀，南汐自己决定"这事得动手"。

- **机制**：AstrBot 的 `@filter.llm_tool`（function calling），工具名 **`dsh_task`**。
  插件内部连星驿那套桥接（HTTP + SSE，`bridgeVersion 7`），**不碰星驿的代码**；
  两者共存、**共用同一个 DSH 会话**（conversation = 该群/私聊的 UMO）。
- **实测（测试群 `<TEST_GROUP_ID>`，2026-10-03 22:2x）**：
  - 自然语言「读一下 `<PROJECT_ROOT>\AGENTS.md` 的第一行，原样告诉我」→
    南汐先说一句过渡话 → `· DSH 正在用 read` → 南汐用人设转述结果。**全程没提工具名**；
  - 长输出（数根目录 `.md`）→ DSH 正文按 `throttle_ms` / `flush_chars` 分 **3 片**陆续发出
    → 南汐只用**一句**人设化收尾，**不重复正文**；
  - 非主人调用 → 工具直接拒绝，日志 `非主人（<TEST_BOT_QQ>）尝试调用工具，已拒绝`。
- **返回口径（⚠️ 2026-10-04 晚修正过，务必看）**：DSH 的正文由插件 `_send_body` **直接发进群**
  （不过 LLM），**同时把同一份正文塞进 tool result** 交还给南汐 —— 于是她「手上有一份、群里也有一份」，
  但 prompt 用最硬的措辞禁止她再复述（**防群里出现两份**，群里始终只有插件发的那一份）。
  ⚠️ **这个"同时"是修出来的**：修复前 tool result 只回一句「已经发到群里了，别重复」，
  南汐的上下文里**只剩"干完了"三个字**，用户回头问内容她只能现编、或绕远去翻群历史 ——
  2026-10-04 主人一句「dsh 的东西没有返回给南汐吗？」把它问了出来。
  **教训：「不必再说一遍」≠「不必知道」；「交付给群」和「交付给 LLM」是两件事，不能顺手一起做掉。**
  改的是 `astrbot_plugin_nanxi_dsh\main.py` 的 `if emitted:` 分支（仓库根源码 + `data\plugins\` 部署副本要一起同步，改完重启 AstrBot）。
  另注：文件末尾那段「短任务把原文交给 LLM 转述」的分支**实际几乎走不到** ——
  只要 DSH 吭过一声 `text/delta`，`emitted` 就非空、正文就已被 `_send_body` 直发群了。
- **实测（2026-10-04 19:5x，修复后，测试群 `<TEST_GROUP_ID>`）**：让 DSH 读 AGENTS.md 某节并总结 →
  群里一张 **3838 字**合并转发卡片 ＋ 南汐一句收尾（**不重复正文**）；紧接着追问
  「那节里那个免 Key 的插件叫什么、给你注册了哪几个工具」→ 她 **4 秒**答出
  `astrbot_plugin_anysearch` / 作者 AgIzT / v0.3 / 三个工具名与参数细节，
  而日志里**本轮零工具调用**（没翻群历史、没再调 DSH）⇒ 证明正文确实进了**她的上下文**，不是靠外查。
- **顺带确认的一条 AstrBot 事实**：模型**带 tool_calls 的那次响应里若也有正文**，
  那段正文**会**发给用户（`tool_loop_agent_runner.py:925-936` 在工具分支之外）。
  所以南汐能自然地说一句"那我让 dsh 去看看"再交活，插件**不需要**自己发开工提示。
- **⚠️ 坑 1（最坑）：人格的 `tools` 白名单。** `astr_main_agent.py:602` 只在
  `persona["tools"] is None` 时给全部工具；**`[]` 是 falsy ⇒ 一个工具都不给**，
  模型于是只能回"我看不到你的电脑"。南汐人格原本正是 `[]`，已改成 `["dsh_task"]`：
  `UPDATE personas SET tools='["dsh_task"]' WHERE persona_id='南汐'`（**改完必须重启 AstrBot**，
  人格有内存缓存）。备份：`_backup\20261003\data_v4.db.bak-before-persona-tools`。
- **⚠️ 坑 2：工具描述决定模型会不会调用。** 第一版描述只写"它有一台真实机器"，
  模型面对"帮我数一下某目录下有几个 .md"仍回"我看不到你本地 D 盘"，
  除非用户**点名** `dsh_task` 才肯调用。第二版把
  「**只要需要碰到这台机器就必须调用，不要回答"我看不到你的电脑"，也不要让用户自己去敲命令**」
  写进描述，自然语言场景一次通过。**别为了"礼貌"把描述写软。**
- **急停已接（实测）**：复用 AstrBot 内置 `@南汐 stop`
  （`active_event_registry.register_agent_stop_callback`，**不自己注册同名命令**）。
  ⚠️ **回执只能有一条，而且只能是【内置】那一条**（2026-10-04 改）：内置 `stop` **无论有没有任务都一定回一句**
  （`builtin_commands/commands/conversation.py:210-220`），所以插件在停止回调里**再 `_say` 一次就是两条** ——
  实测群里曾经是 `✅ Requested to stop 1 running tasks.` ＋ `（已经叫停了）`。现在两手：
  ① 插件那条 `_say` 已删（源码里留了注释说明为什么）；② 内置那两句英文靠仓库根
  **`patch_astrbot_stop_reply.py`** 改中文（`（已经叫停了 N 项任务）` / `（这边没有正在跑的任务）`，
  幂等、带 `--revert` / `--dry-run`，**升级 AstrBot 后要重跑** —— 它改的是 gitignore 掉的上游源码）。
  实测（2026-10-04 20:46，测试群 `<TEST_GROUP_ID>`）：长任务已经在 `dsh_task` 里跑 → `@南汐 stop` →
  群里**只有一条**「（已经叫停了 1 项任务）」，日志 `已叫停 DSH 会话 im-e551b7aa-…`
  ＋ `Agent execution was requested to stop by user.`。
  ⚠️ **回给 LLM 的那句「用户叫停了这一轮，请用你自己的口吻应一声」实际来不及说** ——
  内置 stop 会把整个 agent runner 停掉（`Agent execution was requested to stop by user.` 紧跟 Tool Result），
  所以群里**不会**出现南汐的人设收尾，只有内置那一条。别指望靠它补话。
  ⚠️ **2026-10-04 深夜「异步交活」之后，上面这条又变了**：后台任务不在 AstrBot 的活跃事件表里，
  内置 `stop` 必定回「（这边没有正在跑的任务）」—— **那句话是错的**（任务确实被停了）。
  所以现在插件**必须**补一句「· 已叫停后台任务（DSH 那边也停了）」，取消路径也换成了消息钩子
  （见本节 `dsh_task` 条目）。**别再照"插件一个字都不回"的旧结论改。**
  ⚠️ 被叫停时取消的是**子协程**而不是当前 task —— 被取消的 task 里再 await 会被立刻二次取消，
  连"已经停下来了"这句话都发不出去。
- **⚠️ 群里触发内置命令，必须 @【收到该事件的那个平台机器人自己】才算唤醒**（2026-10-04 实测澄清）：
  命令过滤器只管「命令在消息开头」，**唤醒检查在它之前**。所以测试小号发一条裸 `stop`（或 @ 错账号）
  会**静默无反应**（日志里能看到 `[onebot-qq] deepseek/<TEST_BOT_QQ>: stop` 这条事件，
  但既不进命令、也不进 LLM）。正确姿势是 `@<BOT_QQ>` 再紧跟 `stop`（At 段后面**不能有空格**：
  CommandFilter 判的是 `startswith("stop ")` 或 `== "stop"`，`" stop"` 直接失配）。
  ⚠️ 另外**自己发的消息不会被自己的 OneBot 上报** —— 所以用测试小号（<TEST_BOT_QQ>）在群里说话时，
  AstrBot 那侧只会有 `onebot-qq`（主号）收到；`onebot-qq-test` 那条线只对**别人**发进群、
  且 @ 到 <TEST_BOT_QQ> 的消息生效。想验主线行为就必须 @ 主号。
- **⚠️ 坑 3（最阴的一条）：模型会"学着演"上下文里出现过的话。**
  上下文里只要出现过一次"我看不到你的电脑"，**之后它就继续这么演** ——
  实测：非主人被拒一次之后，**连主人的请求它也回"这个真做不了"**，
  而 `dsh_task` 一直好好地在工具集里（`on_llm_request` 钩子能看到）。
  两手对策已落地：① 拒绝时明确告诉模型「**这个能力你是有的**，只是不给他用」；
  ② 每次请求往 `req.system_prompt` 追加「你有 DSH 这双手…绝不要说『我看不到你的电脑』」——
  **只靠工具描述不够**，那是弱注意力区（第一版只靠描述时，模型面对"数一下有几个 .md"照样推脱）。
  清掉 `data_v4.db` 里该会话的 `conversations.content` 再重启 AstrBot，**自主调用立刻恢复**。
  ⚠️ **2026-10-05 又踩了一次，而且这次看清了"真故障 + 演员"两层是叠在一起的：**
  我改 `browser.py` 时连出三个语法错（`unterminated string` / 参数类型 `integer` /
  `browser.py:626` 的 `invalid character '：'`），AstrBot 那三段窗口里插件**整个 import 失败**、
  工具集真的只剩 anysearch —— 于是她**如实**报了 `Tool web_open not found`（这层是真的）。
  可我修好、13:01 重启（17 个工具全注册）之后，13:02 再叫她用浏览器，她**一次工具都没调**
  （日志里 `Agent 使用工具` 计数为 0，整轮 3.3 秒）就回「工具直接回『找不到』」——
  那是**照着 5 分钟前的上下文演的**。两层要分开判：
  **「她说工具没了」不算数，去看那一轮日志里有没有 `使用工具` 这行**（有 = 真调用过；
  没有 = 她在演）。修法两条，**都要做**：
  ① 系统提示里加"**判断工具在不在，唯一办法是真的调用一次；没调用过就说工具没了是编的**"；
  ② 把被污染的那几条尾巴从会话里切掉 —— 现成脚本
  **`python tools\truncate_conversation.py <cid> <保留条数> [--apply]`**
  （干跑先看会删哪些；`--apply` 自动把 `data_v4.db` 备份成 `*.bak-before-truncate<cid>-<时间戳>`）。
  ⚠️ **改库前必须先杀掉 AstrBot**（它内存里握着会话，退出时会回写覆盖你的修改）；
  会话 → cid 的对应关系看 `python tools\inspect_conversations.py`（`onebot-qq:GroupMessage:<TEST_GROUP_ID>`
  就是 cid=1），`tools\grep_conversation.py <cid> <关键词…>` 用来定位"哪几条被污染了"。
  ⚠️ **`conversations` 表没有 `unified_msg_origin` 列**，UMO 存在 `platform_id` + `user_id`；
  而且 `SELECT rowid` 会**别名到 `inner_conversation_id`**（INTEGER PRIMARY KEY），
  别按 `rowid` 取值，否则 `IndexError: No item with that key`。
  ⚠️ 会话是**懒落盘**的：她刚回完那几轮，DB 里可能还没有 —— 别据此以为"没记上"，过几秒再读。
  ⚠️ 顺带两个正名：**`/reset` 在本机不生效** —— `provider_settings.wake_prefix` 是空串，
  内置命令判的是 `message_str == "reset"`（**不能带斜杠**，带了南汐会当闲聊接）；
  而发裸 `reset` 会被"需要 admin"挡掉（测试小号不是 AstrBot admin）。
- **源码在 `astrbot_plugin_nanxi_dsh\`（仓库根，进 git）**，部署副本在
  `astrbot\data\plugins\astrbot_plugin_nanxi_dsh\`。
  `bridge_url` / `bridge_token` 必须与星驿插件**填同一套**。
  详见该插件自己的 `README.md`。

**📋 2026-10-04：南汐的「会话调度」与 DSH 多实例 —— 计划已立档 → `计划-南汐会话调度与DSH多实例.md`**

- **要做什么**：让南汐像员工一样**自己挑工作台**（自己判断去哪个项目、用现成会话还是新开、要不要分支），
  并给她一个**独立的 DSH 实例**，别让她和主项目抢同一个进程。主人是项目经理，DSH 工作区是她的工位。
- **代码现状**（插件 `astrbot_plugin_nanxi_dsh` 已加）：`dsh_look`（工作台看板）、
  `dsh_task(task, at=…)`（跨项目出差）、`dsh_fork`（分支副本）、台账 `workbench.json`、
  黑白名单（项目 + 会话）、**干完自动回家**（默认工位 `nx_dsh`）——
  ⚠️ **除台账外全部尚未端到端验证**，源码在仓库根、部署副本在 `astrbot\data\plugins\`。
- **⚠️ 2026-10-04 事故（必读）**：测试时让她 `rebind` 到 **`mas`（AUTO-MAS 大项目）**数目录，
  **44 秒持续 IO 把 DSH Web 拖到无响应**——她和主项目会话跑在**同一个 DSH 进程**里；
  主人重启 DSH，**AstrBot 作为 `Start-Process` 的子进程被连带杀死**（6185/3002 全没）。
  ⇒ 两条铁律：**① 常驻服务让主人双击 `启动\一键启动.bat`**，别在 DSH 会话里 `Start-Process`
  （那样它会挂在 DSH 名下、陪它一起死）；**② 测试别用重任务**，别拿大目录当靶子。
- **多实例调研结论**：官方**没有**多实例章节、**无隔离边界声明**；`--from-default-profile` 只复制内置模板的
  bundle 列表（不复制依赖/patch）；凭据/sessions/storages **不在 profile 内**，同 `$DSH_HOME` 是共用根。
  **同一个 `$DSH_HOME` 下 `storages/` 官方明确「没有跨进程写锁，最后写入者胜」**（唯一的真坑），
  而 `sessions/` **有**跨进程锁（Windows 命名内核信号量）。端口必须不同，否则后启动的实例直接启动失败。
  推荐：**独立 DSH_HOME + 端口 3081 + `sessions/` 用 junction 共享 + `storages/` 独立**。
- **☆ 顺手验证到的一条 DSH 事实（fork 归组）**：`dsh-astrbot-relay/lib/index.js:2744` 的
  `forkWorkspace` 等价物 = `registry.list().find(e => e.sessionIds.includes(sessionId))` ——
  **fork 只把子会话挂到「源会话所在的工作区」**。源会话没归属（星驿用 cwd 裸建的），副本就也落「未分组」。
  实测：`rebind` 建的会话有归组，从它 fork 出来的**也带 `workspaceId`**。
- **✅ 2026-10-04 已落地：南汐的独立 DSH 实例（端口 3081）** —— 详细记录见
  `计划-南汐会话调度与DSH多实例.md` §4.5。
  - 独立 HOME `<NANXI_DSH_HOME>`，新 profile `nanxi`（只装 `dsh-astrbot-relay` + `dsh-interconnect`）；
    `sessions/`、`skills/` 用 **junction** 指向主 HOME（会话在主 GUI 可见、技能一致）。
  - **启动方式：双击 `启动\start-nanxi-dsh.bat`**。⚠️ **别用 agent 的 `Start-Process`** ——
    那样它挂在 DSH 的 Job 里，主 DSH 一重启就陪葬（今天的 AstrBot 就是这么死的）。
  - **互通已实测**：主实例 `main` ↔ nanxi，`interconnect_ping(instanceId="nanxi")` → `reachable`；
    peers/token **改完即热生效，不需要重启 DSH**。
  - AstrBot 侧两个插件的 `bridge_url` 已切到 `http://127.0.0.1:3081/astrbot-relay`（**改完要重启 AstrBot**；
    备份 `_backup\20261004\*.bak-before-3081`）。
  - **⚠️ 三个新踩的坑（都能让 dsh 起不来、或让工具全废）**：
    ① **`DSH_INTERCONNECT_TOKEN` 不能写进 `$DSH_HOME\.env`** —— dsh 0.2.0 明确拒绝
    （*"only the launching environment may set"*）；正解是写进 `$DSH_HOME\.credentials.yaml` 的 **`refs:` 段**。
    ② **`dsh --profile <name>` 后面不能再跟 `web`** —— `web` 是内置 profile 名，换 profile 要写
    `dsh --profile nanxi --port 3081 --no-open`（多写 `web` 报 `too many arguments ... got 1: web`）。
    ③ **`DSH_PERMISSION_MODE` 只认 `read-only` / `workspace-write` / `danger-full-access`** ——
    填别的（比如 `dsh-approval-gate` 的 preset 名 `auto-approve`）会让 `sandboxPolicy` 服务起不来，
    于是**整棵工具树链式残废**：`tool-fs: waiting for fs`、`tool-pwsh: waiting for shell`、
    `workflow-ptc: waiting for ptcRuntime, sandboxPolicy`；症状是星驿报 `投递失败`，那条 QQ 消息
    fallback 给聊天 LLM（群里回复变成一张转发卡片、内容是南汐自己编的长文）。**2026-10-04 真踩过。**
    **✅ 同日改：nanxi 现在用的是 `danger-full-access`** —— 写在 `启动\start-nanxi-dsh.ps1`
    的环境段里（与主实例对齐），主人拍板：「**不让南汐有操作电脑的权限这个想法是错的**」。
    默认的 `workspace-write` 会把正常活挡成 `spawn EPERM`（vitest 要起子进程），
    然后弹一个**主人不一定看得到**的提权审批，白卡好几分钟（当天实测挂了 4 分多钟）。
    ⚠️ 改权限模式**必须重启 DSH 实例**才生效；`start-nanxi-dsh.ps1` 是唯一入口，**别另建 `.env`**
    （该 HOME 下本来就没有 `.env`，`Copy-Item` 会直接报 path does not exist）。
  - **nanxi 的插件集（2026-10-04 装齐并验证）**：与主 profile 对齐 —— modsearch（搜索）、cost-meter（记账）、
    config-manager（配置备份）、recall、memory-evolve（记忆）、share、chat-import、web-artifact-designer、
    approval-gate（**必需**，审批靠它自动裁决）、better-sidebar / blue-fantasy / widgets / whale-widget /
    commercial-ui-ux（UI）、dshmarket、ego-browser、dsh-android ⇒ 共 **19 个依赖 / 21 个 bundle**。
    **有意排除 4 个**：`dsh-email-notify`（它就是 QQ 通知的实现者 —— 装了南汐的 agent 会自己往群里发通知，
    同一件事播报两遍）、`dsh-find-plugin`（与 0.2.0-rc.2 不兼容）、`dsh-instance-manager`（她是被管理的，
    且实测它认不出跨 HOME 的实例）、`dsh-astrbot-relay`/`dsh-interconnect`（本来就装了）。
    实测：装完后**读与写都正常**（`write` 工具写文件成功）。
  - **看她的 Web UI**：双击 `启动\open-nanxi-web.bat` —— 从实例日志读出**当前有效**的一次性 token URL
    并开浏览器（裸访问 `http://127.0.0.1:3081/` 是 **401**，token 每进程新铸，重启即失效）。
- **社区方案（全部社区作品，本机一个都没实测过）**：`dsh-interconnect`（35★，跨实例互通，
  持久 WS + 共享 token，**不需要额外 broker**，装完 hmr 秒级生效）、`dsh-instance-manager`
  （管本机多个 dsh web 实例，带 `instance_list/start/stop/logs/sessions` agent 工具）；
  与 `dsh-agent-relay`／`dsh-ask-peer` 的对比见上述文档 §4.3。

**✅ 2026-10-04 晚：南汐的【联网搜索】落地 —— 免 API Key，用社区插件 `astrbot_plugin_anysearch`。**

- **为什么是插件、而不是 AstrBot 内置**：内置联网搜索（`provider_settings.web_search`）的 6 个 provider
  （tavily/bocha/brave/firecrawl/baidu/exa）**全都要 API Key**，其中博查（Bocha）账户**无额度**，
  实测稳定返回 `403 You do not have enough money or package quota`（key 本身有效）。
  本机 AstrBot **4.27.4** 的核心里**没有** `anysearch`（docs 站点上那个 AnySearch 是更新版本才进核心的），
  所以只能走插件。
- **插件来源**：AstrBot 官方插件市场 → 搜「**Anysearch实时联网搜索**」（作者 **AgIzT**，v0.3，
  `https://github.com/AgIzT/astrbot_plugin_anysearch`）。装法：从 GitHub raw 拉
  `main.py`/`client.py`/`tools.py`/`metadata.yaml`/`_conf_schema.json`/`requirements.txt`/`LICENSE`/`logo.png`
  到 `astrbot\data\plugins\astrbot_plugin_anysearch\`，重启 AstrBot 即加载（**无需 pip 装东西** ——
  它只用 `aiohttp`，而 `astrbot\data\site-packages\aiohttp` 本机已有 3.14.3）。
- **「免 Key」是真的**：`api_key` 留空即走 **Anysearch 匿名访问**。实测工具调用
  `POST https://api.anysearch.com/mcp`（JSON-RPC `tools/call`）**直连 HTTP 200**，1~2.3 秒返回真实结果，
  **不要 Key、也不要代理**（本机直连与走 Clash `7897` 都通）。想要更稳的额度可去
  `https://anysearch.com/console/api-keys` 免费注册后填进插件配置。
- **三个 LLM 工具**（**必须加进人格 `tools` 白名单**，否则模型看不到 —— 见 §5.5 那个 `[]` 等于零工具的坑）：
  `anysearch_search`（通用搜索，支持 `freshness`/`content_types`）、
  `anysearch_extract`（把公开网页抓成 Markdown 正文）、
  `anysearch_batch_search`（并行 1~5 个查询）。
  人格 `南汐` 的 tools 现为
  `["dsh_task","dsh_look","dsh_fork","anysearch_search","anysearch_extract","anysearch_batch_search"]`。
- **⚠️ 必须同时关掉内置联网搜索**：`provider_settings.web_search` 已改回 **`false`**。两个原因 ——
  ① bocha 无额度必 403；② `_apply_web_search_tools` 会**绕过人格白名单**直接 `add_tool`，
  于是模型手上同时出现「必失败的 bocha 工具」和「可用的 anysearch 工具」，它很可能先挑前者、
  然后在群里报一串额度错误。
- **实测（测试群 `<TEST_GROUP_ID>`，2026-10-04 19:39）**：发「南汐，帮我上网搜一下 DeepSeek 最新发布的模型
  叫什么，把来源链接给我」→ 她**自主**决定联网，日志 `Agent 使用工具: ['anysearch_search']`、
  参数 `{'query':'DeepSeek 最新发布的模型','freshness':'month','max_results':8}`、
  返回 `## Search Results (8 results, 1115ms)` → **7 秒**回复一条合并转发，内容是
  「DeepSeek V4.1 Flash（2026-09-10 发布）552B MoE…」＋ 3 个可点来源链接，**人设完好**（结尾傲娇）、
  **全程不暴露工具名**。回归：闲聊「你今天心情怎么样喵」**4 秒**、日志**零工具调用**（没误触发）。
- **⚠️ 插件自带一个命令闸门缺口**：它注册了 `@filter.command("anysearch", alias={"搜索","websearch"})` ——
  按 §5.5「命令名后必须跟空格」那条规则，群里**任何人**发「搜索 xxx」（**完全不用 @南汐**）也会命中并触发搜索。
  私有测试群里无所谓；将来若放开白名单群要收紧，得给这个命令补 `_invoked_by_at_bot()` 闸门，
  或干脆删掉该命令、只保留 LLM 工具。
- 备份：`_backup\20261004\cmd_config.json.bak-before-anysearch-20261004-193733`、
  `data_v4.db.bak-before-anysearch-20261004-193733`。

**✅ 2026-10-04 晚（二）：南汐的【会话生命周期管理】—— 归档 / 撤回归档 / 撤回分支 / 撤回新建。**

- **她能做什么**：她现在有 **10 个** LLM 工具（人格白名单里逐个列着，**少一个模型就完全看不见那个工具**）
  - `dsh_task(task, at="")` —— **交活**。⚠️ **2026-10-04 起是【异步交活】**：工具**立刻返回**，
    DSH 在后台干（每个 IM 会话一条队列 + 一个 worker，**串行**消费 —— DSH 侧一个会话同时只跑
    一个 turn）。改的原因：同步等的时候一个长任务把南汐**整个 turn 占住**，主人再说话就得排队
    （实测让她改个名等了 **61 秒**）；异步之后实测 **4~6 秒**就能理人。
    - **事后发送必须走主动接口**：工具一返回，那个 event 就离开管线了，`event.send()` 会
      **静静地什么都不发**（不报错，最难查的那种）。所以插件的 `_say`/`_send_body` 全都改走
      `Context.send_message(umo, chain)`（封在 `_deliver()` 里）。**加新的"事后发送"时必须用它。**
    - **`@南汐 stop` 换了落点**：异步之后 `active_event_registry` 里注册的停止回调**永远等不到**
      （那个 event 已经不活跃），改由 `on_message_maybe_stop`（`@filter.event_message_type(ALL)`
      的钩子）认领：见到该会话的 `stop` 就取消后台 worker ＋ `session/cancel` 掉 DSH 那一轮。
      ⚠️ **内置 stop 看不见后台任务**（它数的是 AstrBot 自己的活跃事件），必回一句错的
      「（这边没有正在跑的任务）」⇒ 钩子要补一句「· 已叫停后台任务（DSH 那边也停了）」，
      **只在真的取消了时才补**（没任务时保持安静）。
    - 后台跑完群里会冒出 `· DSH 干完了（用时 N 秒）` —— 异步模式下 LLM 那一轮早结束了、
      没人在收尾，这句是"这次干完了"的信号。
    - ⚠️⚠️ **异步交活必须配两条回执，少一条就是「她瞎了」或「群里空的」**（2026-10-04 主人两次点名）：
      ① **给她**：worker 把 `_run_turn` 的返回值存进 `self._inbox[umo]`，`watch_request`
         （`on_llm_request` 钩子）在**她的下一轮请求**里把它 append 进 `req.contexts`
         —— **不是** `system_prompt`（后者每轮重算、用完即弃；进对话历史她才一直记得），取走即清。
         **缺这一步，她手上只有一句「已交出去」**，主人一问细节就抓瞎
         （主人原话：「刚刚 baah 计划表_南汐的返回你没看到吗」）。
      ② **给群**：`_run_turn` 的 `else` 分支（`emitted` 为空，典型是纯工具型的短活）
         原本写的是"请她用人设转述结果"—— **异步下没人转述**，群里只剩一句「干完了」。
         现在 worker 传 `announce=True`，那条分支**直接 `_send_body` 发进群**，
         返回值照样带正文（供 ① 存进 `_inbox`）。实测：改前群里只有 `· DSH 干完了（用时 2 秒）`，
         改后能看到 `[forward]` 正文卡片。
    - 实测（2026-10-04 22:1x~22:2x）：45 秒任务期间问她话 **4 秒**回（她说"手上确实有一件挂着"）；
      期间改名 **6 秒**完成（改前 61 秒）；后台结果以合并转发卡片进群 ＋「干完了（用时 56 秒）」；
      `stop` 能把后台任务和 DSH 那一轮一起叫停。
    - ⚠️ **会话忙时，这条消息会自动「插队」**：插件发现同一会话还有活在手上/排着队，就给请求体带
      `mode: "steer"` —— 星驿补丁把它透传给 DSH 的 **`agent.steer`**（"Submit steering for the
      nearest step"，投到当前 turn **最近的 step 边界**，不用等它跑完）；空闲时照旧 `followup`。
      **没打那个补丁也不会出错**：星驿会忽略这个字段，退化成排队。
      ⇒ 背景：DSH 的 agent handle 本来就是**一对**能力
      （`dsh-agent/lib/types/runtime-types.d.ts:192/200`：`followup` 排队 / `steer` 插队），
      而**星驿原版只用了 `followup`** —— 所以「她正忙时补一句话」原本只能干等，
      或者被背压挡回来（2026-10-04 主人实测截图：`409 该会话有投递或附着在途`，
      南汐还把它解释成"这是排队"）。补丁见 `patch_relay_steer.py`。
    - ⚠️ 附带一条速查：`dsh_task` 的报名步骤（`_go_home`/`_goto` 换工作台）**仍然是同步做的** ——
      否则"她现在在哪间"就说不清了；异步的只是"跑活"这一段。
    - ⚠️ **她还有一双眼睛和一只手：浏览器** —— DSH 侧装了 **`dsh-ego-browser 0.8.6`**：
      能**真的打开网页**、点按钮、填表单、滚动、截图。**没有命令行接口的东西**
      （Web 后台、在线看板、网页版的设置页、要登录的管理界面）就让她用浏览器去做；
      它甚至能打开 **DSH 自己的 Web 界面**（`http://127.0.0.1:3081`）去看会话状态 ——
      这是星驿链路出问题（审批/超时）时的一条兜底路。
      已写进插件的系统提示（`watch_request` 里那段「【你还有一双眼睛和一只手：浏览器】」）——
      **不写她就不知道自己有这双手**（2026-10-04 主人提出的方向）。
    - ⚠️ **这条消息里带的图也会一起送给 DSH**：插件从 `event.get_messages()` 取 `Image` 组件 → `convert_to_base64()` → **按字节魔数嗅探 `mediaType`**
    （星驿只认 png/jpeg/gif/webp 四种，而 AstrBot 只给裸 base64、不给类型）→ 塞进星驿 `/message` 的 `images[]`；
    星驿把 base64 存进 DSH 附件库、再以 **image 块**投给 agent。
    DSH 的 `deepseek-flash` 自己声明了 `inputModalities: ["text","image"]`，**是真能看图的**。
    ✅ 实测（测试群 `<TEST_GROUP_ID>`）：发一张「左红右蓝 + 白字 CAT-42」的图 → DSH 准确报出
    「左边红、右边蓝、正中分界、红底白字 CAT-42」；`im-e551b7aa` 会话里能查到 6 处 `type:"image"` 事件。
    - ⚠️ **现象：图会送两遍"意思"** —— AstrBot 会把图**落盘**（`astrbot\data\temp\media_image_*.jpg`）
      并把路径交到南汐的上下文里，于是她**还会顺手把路径写进 task**。结果 DSH 同时收到「图」和「路径」。
      这**不影响正确性，反而有用**：实测 DSH 用路径发现前两张 temp 副本已被 AstrBot 回收、改用**哈希**比对。
      已在 `dsh_task` 的描述里请她别再写路径，但**习惯难改**（她上下文里见过"写了也没错"）——
      要彻底去掉得在插件侧删文本，**不推荐**（会丢掉这个验证手段）。
    - ⚠️ 单图上限：插件按 **base64 后 ≤ 12 MiB** 过滤，超了就跳过那一张（星驿的请求体上限
      是按"三张 20 MiB 原图"反推的，`images[].data` 必须是**裸 base64**、不带 `data:` 前缀）。
    - ⚠️ 排查用日志：插件每次交活会打一行 `[nanxi_dsh] 这条消息的组件：[…]` ——
      想知道图有没有进消息链，看它就行（`Image(ComponentType.Image)` = 拿到了）。
  - **`web_open(url)` / `web_look()` / `web_click(target)` / `web_type(target, text)`** ——
    **南汐本人自己的浏览器**（2026-10-04 主人要的「南汐自己操控」，不是指挥 DSH）。实现见
    `astrbot_plugin_nanxi_dsh\browser.py`：**纯 Python 驱动本机 Chrome 的 CDP**
    （HTTP `/json/list` 拿调试目标 + WebSocket 发 `Page.navigate` / `Runtime.evaluate` /
    `Page.captureScreenshot`），**零新依赖**（用 site-packages 里已有的 aiohttp，它自带
    `ws_connect`）—— **不需要 playwright**。`headless=new` 不弹窗；profile 落在插件目录的
    `chrome-profile\`（**登录态留着，这是特性**）；懒启动、闲置 600 秒回收；一把锁串行。
    - `web_open` 开页面并读回正文；`web_look` **截图直接发群**（她"亲眼看见"的方式）；
      `web_click` / `web_type` 的 `target` 既吃 CSS 选择器、也吃**可见文字/placeholder**。
    - ⚠️ `browser.py` 是**动态加载**的（`importlib.util.spec_from_file_location`）——
      AstrBot **不会**把插件目录放进 `sys.path`，`import browser` 会 ModuleNotFoundError。
    - ⚠️ 工具 docstring 里**无参数的不要写 `Args:` 段** —— 写 `Args: 无。` 会被解析成一个叫
      "无"的参数（这坑踩过两次）。
    - ✅ 实测（2026-10-04 23:21，测试群 `<TEST_GROUP_ID>`）：她自己调 `web_open('https://example.com')`
      → 12 秒拿到标题与正文（含首次起 Chrome）→ 又自己调 `web_look` → **截图 39543 字节直接进群**
      （群里出现 `[图片]`）→ 人设收尾「截图给你了喵，自己看吧」。
    - **✅ 2026-10-05：「点不准」修好了 —— 照 `dsh-ego-browser` 抄了两件事，都实测过了。**
      她当时的原话是「进得去、看得见，但**点不准**……每一行的名字右边都蹲着一个「…」按钮，
      我一按「nx_dsh」这三个字，**落点就正好砸在那个「…」上**」。两个独立的毛病：
      ① **按文字找元素只搜了交互元素**（`a,button,input,[role],[onclick],[tabindex]…`），
      于是**裸 span 里的文字压根不在搜索面里** —— 实测 `web_click('nx_dsh')` 直接回
      「页面上没找到「nx_dsh」」（她用测试件复现时也是这句）。
      **正解是抄 `dsh-ego-browser` 的 `textElementsExpression()`**（在它的
      `runtime/ego-browser/dist/out/index.js` 里，约 1439-1451 行）：
      ```js
      document.querySelectorAll('body *')            // ← 搜【所有】元素，不是只搜交互元素
        .filter(el => match(el.innerText || el.textContent))   // 归一化空白后 includes
        .filter(el => !Array.from(el.children).some(c => match(c)))  // ← 子孙里没有也匹配的
      ```
      也就是 Playwright `text=` 的语义：**取最内层那个叶子**。落到 `browser.py` 的
      `Browser.click()` 里就是：先按 CSS 选择器 → 再按"全元素 + 最内层"找文字
      → 最后才用可访问名字（`aria-label`/`title`/`placeholder`/`value`）兜底。
      ⚠️ **顺序不能反**：那个「…」按钮的 `aria-label` 是「nx_dsh 的更多操作」，
      光靠"最短可访问名字"挑，**照样会挑到按钮上**。
      ② **落点原本直接取元素中心，不做命中测试** —— 所以就算选对了元素也会砸到别人身上。
      现在从中心开始试 `document.elementFromPoint()` 验证"底下确实是它（或它的子孙）"，
      不成就退到左侧 25% / 12% / 上方 25%，全不行才退回中心（并且把挡住它的元素记进
      `blocked` 字段，便于诊断）。
      **★ 怎么在没有 QQ 的情况下先把这两条验掉**（省掉反复重启）：仓库里有
      **`tools\click-fixture.html`** —— 一个本地页面，行里一个裸 `span` 写着 `nx_dsh`，
      右边一个 `aria-label="nx_dsh 的更多操作"` 的「…」按钮；点名字写
      `RESULT=SWITCHED_*`、点按钮写 `RESULT=MENU_*`，**结果直接写在页面文字里**，
      所以 `web_click` 的返回值就能判真假。用**你自己的** ego 浏览器打开它，
      `ego_script` 里 `await page.evaluate(<那段 JS>)` 就能离线验算法（实测：
      旧算法 → `not-found`，新算法 → `SPAN :: nx_dsh @ 262,89`）。
      JS 是**用 Python 字符串拼出来的**，Python 语法对不代表拼出来的 JS 对 ——
      **`python tools\check_click_js.py`** 会把那段 JS 抠到 `tools\_click_inline.js` 再跑
      `node --check`（该产物已 gitignore）。**改完 `click()` 先跑它，再重启。**
      - ✅ 端到端实测（2026-10-05 13:09，测试群 `<TEST_GROUP_ID>`）：
        `web_open(file:///…/click-fixture.html)` → **只用文字** `web_click('nx_dsh')`（禁止用坐标）
        → 工具回 `（点了 SPAN:nx_dsh。… RESULT=SWITCHED_nx_dsh / 点中名字 nx_dsh @ 262,89）`，
        她转述 `RESULT=SWITCHED_nx_dsh`；日志确认这一轮**只有** `web_open` + `web_click` 两个调用
        （没有 `web_click_at`），10 秒。真实站点同样过了：
        `web_open('https://example.com')` → `web_click('Learn more')` → 落地页第一行 `Domains`。
    - **✅ 看板的网址/标题现在跟得上了**：原来 `_last_url`/`_last_title` **只在 `goto()` 里写一次**，
      点个链接跳走之后 `/state` 还停在上一个网址（实测：点完 example.com 的 Learn more
      已经跳到 iana.org，`/state` 里还是 `https://example.com`）。现在
      `Browser._sync_location()` 在 **`click` / `click_at` / `type_text` / `text` 之后**都同步一次
      （读 `location.href` + `document.title`，失败不算错）。实测修完
      `/state` = `https://www.iana.org/help/example-domains` ✓。
    - **☠️ 2026-10-05：看板"只有 1 帧"—— 根因是 Chrome 的单例交接把 `running` 判成假。**
      主人打开 `http://127.0.0.1:6199/` 看到的正是 `帧: 1`，而且画面还是上一页
      （标题/地址已经是新的 —— 因为那两个字段走 `_sync_location`，与帧无关）。
      排查链条（值得记住，因为每一层都排除了一个"看起来很像"的解释）：
      1. `/state` 的 `seq` 永远是 1 ⇒ 整个生命期只收到过一帧；
      2. 但之后每一次 `web_open`/`web_click`/`web_look` 都正常 ⇒ **读循环还活着**
         （它死了的话所有 `call()` 都会超时）⇒ 不是"连接断了"，是 Chrome 那边不再推帧；
      3. `tools\probe_watch_frames.py`（**脱离 AstrBot、单独驱动 `Browser`** 的探针，
         用独立临时 profile）里**一切正常**：screencast 推几帧后静默、兜底轮询按时接管
         ⇒ 算法没问题，**差别在运行环境**；
      4. 把 `casting` / 轮询任务状态也吐到 `/state` 上之后一眼看到
         **`casting=false`、`poller=none`** ⇒ 有人调了 `close()`；
      5. `Get-CimInstance Win32_Process` 看命令行 + `netstat :9333`：
         **CDP 9333 是 pid 27156 在服务，它启动于 12:25:40**（好几个 AstrBot 进程之前），
         而当前 AstrBot 连的就是它 —— 其余 chrome.exe 全是它的子进程。
      根因：**Windows 上 Chrome 有单例行为** —— `--user-data-dir` 已有实例在跑时，
      新起的 `chrome.exe` 把请求交给那个实例后**自己立刻退出**。而 `running` 原来只看
      `self._proc.poll() is None` ⇒ 永远 False ⇒ **每一次 `ensure()` 都误判"死了"**、
      走 `close()` 把 CDP 连接拆掉重建 —— 顺手把 `_casting` 和兜底轮询任务一起复位。
      于是 `watch_on()` 推的第一帧成了绝唱。
      **两处修**（都在 `browser.py`）：
      ① `running` 改成"**CDP 连接还在就算活着**"（启动器退不退出不关我们的事）；
      ② `ensure()` **先试着接管已经在 9333 上服务的那个 headless**（`_find_target`），
         没有才起新的；等目标时**不再因"启动器已退出"而 raise** ——
         那正是交接的正常表现，旧代码把正常情况判成了失败。
      修完实测：`seq` 8→24 持续增长、`/frame` 两次抓到 45873→52156 字节（哈希不同，
      **画面真的在动**）、日志 `接管已经在跑的 headless 浏览器（未另起进程）`。
    - **兜底推帧（screencast 哑了就轮询截图）**：实测 headless 里 `Page.startScreencast`
      **只在页面加载/重绘时推帧**，页面一静就没声了。所以 `_poll_frames()` 在静默超过
      `_FRAME_SILENT`(=1.5s) 后接管，按**稳定 1 fps** `Page.captureScreenshot(format='jpeg')`；
      screencast 一旦重新推帧就让位。两条腿都在时 `seq` 走得比 1 fps 还快。
      ⚠️ **没人看就不截**：`_VIEWER_GRACE`(=30s) 内没有任何 `/state` / `/frame` 请求
      （`WatchServer` 会 `touch_viewer()`）就跳过截图，免得白烧 CPU。
      ⚠️ 验证这条闸门时注意：**主人自己开着的那个看板标签页就是 viewer**
      （`netstat -ano | Select-String ":6199"` 能看到 msedge 的 ESTABLISHED 连接），
      所以"我 45 秒没碰它"并不等于"没人在看"。
    - **`browser.py` 现在有 logger 了**：它是**动态加载**的，拿不到 `main.py` 的 `logger` 变量，
      所以自己 `from astrbot.api import logger`（失败则退回标准 logging）。
      这一条是这次排查的教训 —— 之前兜底轮询**静默失败一行日志都没有**，
      只能靠人肉盯着 `/state` 的秒数猜，太贵了。**加静默重试/兜底逻辑时必须留一行日志。**
    - **看板新增三个排障字段**（`/state`）：`mode`（`screencast`/`poll`）、
      `ageSec`（最近一帧到现在多少秒）、`casting` / `poller`（`none`/`running`/`done`/`exc:…`）。
      **"画面冻住了"和"她没在动"是两回事**，有这几个数一眼就能分清 ——
      这也是这次能一步定位到 `casting=false` 的原因。
  - `dsh_rename(name, session="")` —— **给会话改名**（只改列表里的标题，不动内容）。留空 = 改当前这间；
    会自动把名字缀成 `xxx_南汐`（与项目里"南汐用过的会话"命名一致，避免改完又被星驿缀一次）。
    ⚠️ 它每次改完都会**立刻跑一遍日志完整性检查**兜底 —— 底层的 `session/rename` 有 bug（见下），
    撞车/倒退会被就地修好，群里会看到 `· 会话改名成「xxx_南汐」（自检发现…已经就地修好…）`。
  - `dsh_new(workspace="")` —— 开一间**全新的空白会话**（不继承上下文）并切过去。留空 = 在当前项目里开。
  - `dsh_archive(session="")` —— 把一间 DSH 会话**归档**（`workspace/archiveSession`）。留空 = 归档当前这间。
  - `dsh_undo(what="")` —— **撤销最近一次会话操作**，能撤四类：把刚归档的取回来、
    把刚分支的退掉、把刚新建（`dsh_new` 或换工作台开的）退掉、把刚接手的换回去。
    `what` 可填「归档／分支／新建／接手」指名，留空撤最近一次。
  → 于是「撤回刚刚的归档」「把这个分支撤了」「开个新会话从头来」这类自然语言都能落地。
- **`dsh_fork` 与 `dsh_new` 的分工**（南汐曾对主人说"我这边只有『分支』这个手段，
  没有真正意义上的『另建空白间』"—— 她没瞎说：`fork` 之外确实只有"去某项目"间接触发 rebind
  这一条暗道，而且那个项目**去过一次之后就变 adopt（回到旧的）**了，所以补了她这个显式入口）：
  - **`dsh_fork` = 复制现在这间**（带上全部上下文，实测继承 **552 条**）；
  - **`dsh_new` = 另起一间空的**（走星驿 `/session/rebind`）。
  - **"真空白"的硬证据**：同时期三间会话的存储体量 —— 原始会话 **619,383 bytes**、
    fork 副本 **315,824 bytes**、`dsh_new` 开出来的 **481 bytes**（就是一副空骨架）。
    位置：`<NANXI_DSH_HOME>\sessions\<sessionId>\session.v4.jsonl.zstd`。
  - 两者都**不走 `_go_home`**，所以她分支/新建之后会**留在新会话里**
    （与 `dsh_task` 出差干完自动回家的行为相反）—— 这正是"留下来接着干"需要的语义。
  - `dsh_new` 失败时会**退回默认工位**而不是拒绝干活：问不到当前位置不算错。
- **⚠️ 同一个群里，两个 bot 账号 = 两条完全独立的会话线（2026-10-04 实测澄清）**：
  台账是按 **UMO** 分槽的，而 UMO 里带**平台 id**，所以
  `onebot-qq:GroupMessage:<TEST_GROUP_ID>`（南汐 `<BOT_QQ>`）与
  `onebot-qq-test:GroupMessage:<TEST_GROUP_ID>`（测试小号 `<TEST_BOT_QQ>`，见下文「测试 bot」）
  是**两套互不相干的工位** —— 各自的会话映射、撤销栈、`__home__` 全部分开
  （实测：同一天两条线在 `workbench.json` 里是两个平级的键，各记各的会话）。
  **`@` 哪个账号，事件就走哪条线**；AstrBot 是**同一个大脑、同一个人格**，
  回复也走**那个账号的连接**发出去。所以「@ 测试小号」看起来就像"南汐用 deepseek 的号在说话"：
  群里显示的发送者是 `<TEST_BOT_QQ>`，但语气、工具、人格、DSH 会话都是南汐的。
  ⇒ 两个推论：① 想验**南汐主线**的行为，必须 `@南汐`（<BOT_QQ>）；
  ② 「@ 测试小号」不是"测试南汐"，而是**在另一条会话线上跟同一个大脑对话** ——
  它那边的操作（新建/归档/出差）**不会**动到主线的工位。
- **⚠️ 星驿会【覆盖】会话标题 —— 你在 GUI 里可能认不出自己的会话（2026-10-04 实测）**：
  星驿的默认模板是 `sessionTitleTemplate = '星驿 · {platform}/{messageType}/{sessionId}'`
  （`dsh-astrbot-relay/lib/index.js:183`）；每条 IM 消息投递成功后它会调
  `sessionTitle.rename()` 把这间会话的标题**改写成 UMO 名**，而 `lib/session-title.js` 的注释
  明说这是**有意为之**：`source.kind === 'user'` 的标题会 **supersede 自动生成的标题并锁死**
  （之后不再随对话内容漂移 —— 反向定位要的就是这种稳定）。
  ⇒ 后果：**只要南汐用过哪间会话，那间的原名就被盖掉**。实测：主人原来叫「skill」的那间
  （`session-2ffb0ddb-7b2c-4f9a-9a04-b3641767632c`，cwd `<WORKSPACE_MAS>`）现在在 **main 与 nanxi
  两个 GUI 里都显示为「星驿 · onebot-qq/GroupMessage/<TEST_GROUP_ID>」**，主人因此以为
  "我的 skill 不见了 / 是不是被我归档了"。**它既没删也没归档**（两个实例的
  `.global.archivedSessionIds` 里都没有它）。
  排查套路（标题对不上时**别信标题**）：
  1. `storages/session_projcache/sessions/<sessionId>.json` 的 `record.rows.title.val` 是各 HOME
     自己的标题缓存，**可能还留着旧名**（本次就是靠 main 侧的 'skill' 认出来的）；
  2. `storages/workspace.json` 的 `tables.workspaces[<id>].sessionIds` 定位它属于哪个工作区
     （`record.identity.cwd` 也能直接给目录）；
  3. 会话正文在 `sessions/--<目录编码>--/<sessionId>/session.jsonl.zstd`
     （注意：目录是**按 cwd 编码**的一层，不是 `sessions/<id>/`）。
  另注：模板**关不掉**（空模板在配置校验期就被拒），也**拿不到"原标题"这个变量** ——
  想保留原名只能改星驿行为（改的是 node_modules 上游产物，升级会丢，同 `patch_relay_rpc_methods.py` 的处境）。
- **✅ 已修：让星驿【保留】用户起的名字，只在后面缀 `_南汐`**（2026-10-04 晚，
  `patch_relay_session_title.py`）：
  - 改的是 `lib/session-title.js` 的 `applySessionTitle()` 决策 ——
    **空标题 / 已经是模板渲染值**（= 星驿自己写的）⇒ 照旧写模板；
    **用户起的名字** ⇒ 保留原文 + 后缀（新配置项 `sessionTitleSuffix`，默认 `_南汐`）；
    **已缀过** ⇒ 什么都不写（幂等，也省掉一条无意义的 title 事件）；
    `sessionTitleSuffix` 配成空串 ⇒ 这类会话**完全不碰**。后缀会先扣掉自己的字节预算，
    保证不会被 dsh 侧的 80 字节上限截掉（按字符回退，不劈多字节字符）。
  - 两个安装点都打了（`--all`）：`<NANXI_DSH_HOME>\profiles\nanxi\node_modules\dsh-astrbot-relay`
    与 `%USERPROFILE%\.dsh\profiles\web\node_modules\dsh-astrbot-relay`。
    幂等，带 `--revert` / `--dry-run` / `--path`；**升级 dsh-astrbot-relay 后会丢，要重跑**。
    离线单测 18 项（`tools\test_relay_session_title.mjs`，纯函数 + 假服务就能跑，
    `node tools\test_relay_session_title.mjs`）全过。
  - **⚠️ 必须重启 DSH 才生效 —— HMR 只热重载【配置】，不重新 import `lib/*.js`。**
    实测（假 conversation 探针，见下）：改完文件后只改 `cordis.patch.yml` 触发重载，
    新放行的 `session/rename` **立刻可用**，但星驿写标题**仍是旧行为** ——
    把刚 rename 成的 `probe-original` 又盖回模板名。这正是"配置热重载"与"模块重新加载"的差别。
  - **把已经被盖掉的名字找回来**：`session/rename` 在**上游描述符表里本来就有**
    （`lib/rpc-methods.js:92`），所以不用打描述符补丁，只要在 nanxi 的 `cordis.patch.yml`
    的 `allowedRpcMethods` 里放行（**已加**）。调用形态：`/rpc` + endpoint `session/rename`
    + `args.request = {sessionId, title}`。本次恢复了 **2 间**：`skill` → `skill_南汐`、
    `baah` → `baah_南汐`（另 20 间标题是星驿名的属**星驿自己建的** `im-*`，本来就该叫那个，跳过）。
  - **原名去哪找（权威源）**：**会话日志本身** ——
    `sessions/--<cwd 编码>--/<sessionId>/session.v4.jsonl.zstd` 里有一串 `session/title` 事件
    （event-sourced），**倒着数第二条就是被覆盖前的名字**（`source` 字段还能看出是
    fallback/provider 自动生成还是 user 手工改名）。
    ⚠️ **这个文件是多帧 zstd**：Node 的 `zstdDecompressSync()` **只解第一帧**
    （症状：3.6 MB 的文件只解出 258 字符），流式 `createZstdDecompress` 直接
    `The operation was aborted`。可行解：**按帧魔数 `28 B5 2F FD` 切分后逐帧解压再拼接**
    （实测 `session-4a0b8eb7` 264 帧全解出、43 MB 文本）。
    现成脚本：**`node tools\relay-title-history.mjs [sessionId…]`**（默认扫 mas 分组，
    `SCAN_ROOT` 环境变量可换目录），输出的「最初 / 现在 / 全部」就是标题变迁史。
    而 `session_projcache/sessions/<id>.json` 的 `record.rows.title.val` 只是**缓存**，
    会被刷掉（本次它就是先丢的那个）。
  - **★ 无损探针手法（判断"插件代码热没热"用得上）**：星驿在投递路径里**同步**改写标题
    （`lib/index.js:1780`，排在 `followup` **之前**），所以不需要 SSE 消费者、也不用等 turn 跑完。
    用一个**假的 conversation**（如 `onebot-qq:GroupMessage:99990001`）：
    ① `POST /message` 建会话 → ② `/where` 拿 sessionId → ③ `session/rename` 改成 `probe-original`
    → ④ 再 `POST /message` → ⑤ 读该会话日志看标题。**变成 `probe-original_南汐` = 补丁生效；
    又变回模板名 = 还是旧代码**。测完把那间 `im-*` 归档即可，不碰任何真实群。
  - **顺手两条星驿 API 事实**：① `POST /astrbot-relay/message` **必须带 `Idempotency-Key` 头且为
    UUIDv4**（缺了 → `400 unsupported: 「Idempotency-Key 必填且必须是 UUIDv4（契约 §3.1）」`；
    AstrBot 插件在 `main.py:1801` 生成）；② `/rpc` 的 `args` 键必须是**该方法的 wire 键**
    （`session/rename`→`request`、`session/list`→`_request`）——
    写错键是 400，而 `session/list` 即便键对了实测也回 `gateway/cancelled`。
  - **☠️ 事故与教训：`session/rename` 会把会话写坏（2026-10-04 真踩过）。**
    用它给 `skill` 改名后，那间会话变成**打不开**，GUI 报
    `历史加载失败：… is corrupt: stored log is corrupt: Error: corrupt Zstandard session log:
    complete frame contains a torn JSONL record (raw log: …\session.v4.jsonl.zstd)`，
    `session/rename` 也从此对该会话返回 `gateway/cancelled`。
    **根因（对比正常会话看出来的）**：DSH 的 rename 给新事件分配的 seq 会**与末尾那条
    `session/end-seed` 撞车**。正常会话末尾是严格递增且**以 `session/end-seed` 收尾**的：

    ```text
    正常： … turn/end(4010) → session/end-seed(4011)
    坏掉： … turn/end(4010) → session/end-seed(4011) → session/title(4011)   ← seq 撞车
    ```
    实测判据最快：`node tools\relay-title-history.mjs <sessionId>` 或直接看最后两条事件的
    `type`/`seq` —— **末尾是 `session/title(N)` 而它前面恰好是 `session/end-seed(N)`** 就是中招了。
  - **修复**：**`node tools\repair_session_title_event.mjs <session.v4.jsonl.zstd> [--apply]`**
    —— 它保留到倒数第二帧（那条 end-seed 为止），把最后一帧换成**重新编号**的
    `title(N+1)` + `end-seed(N+2)`（用与 DSH 相同的压缩参数：`Frame_Header_Descriptor=0x04`，
    即带 content checksum），写盘前自动备份成 `*.bak-<时间戳>`。幂等：不是那个坏模式就 SKIP。
    实测修好后 `session/rename` 立刻返回 `ok`（seq 也恢复递增），会话打开正常。
    ⚠️ **别做多余的事**：末尾只缺 `end-seed`（seq 不撞车）**不用修** ——
    DSH 加载时会自己补（`dsh-session/lib/index.js:1352`：
    `if (… this.log.at(-1)?.type !== "session/end-seed") this.append("session/end-seed", {})`）。
    **只有 seq 撞车才致命。**（`baah` 就是"末尾 title 但 seq 正常"，一直好好的。）
  - **✅ 现在带着安全网重新放行了**（2026-10-04 晚）：`session/rename` 已加回 nanxi 的
    `allowedRpcMethods`，配套的是插件工具 **`dsh_rename`**（她要改名只用这个）。
    它每次改完都**先等 1.2 秒**（DSH 落盘是异步的，抢在前面自检会读到"改之前"的状态而误判无事 ——
    实测整个工具只跑了 487ms，撞车就是这么漏掉的），再跑 `repair_session_title_event.mjs`，
    撞车/倒退就地修好。**绕过插件直接调 `/rpc session/rename` 就没有这层保护。**
  - ⚠️ **坏法有两种，判据是「末尾 seq 必须递增」而不是「两条 seq 相同」**：实测 rename 写出过
    `end-seed(32) → title(32)`（撞车）**和** `end-seed(34) → title(33)`（**倒退**，比末条还小）。
    只盯"相同"会漏掉后者 —— 2026-10-04 二次实测就漏了一次，随后判据改成 `last.seq <= prev.seq`。
  - ⚠️ **DSH 进程内的投影缓存不会因为外部改文件而刷新**：修完日志是合法的（会话能正常打开），
    但 DSH 自己记账时可能还用旧基准，于是**下一次改名又写出坏 seq** —— 这不是"没修好"，
    而是"外部改了文件、DSH 不知道"。安全网每次都会兜住；想让两边彻底对齐，重启 nanxi 实例即可。
  - **顺带一条 AstrBot/DSH 无关的通用教训**：改别人进程正在用的**事件溯源日志**之前，
    先拿**同目录的健康样本**做结构对比（本次就是靠"正常会话末尾都是 end-seed、
    且 seq 严格递增"一眼看出问题的），再看一眼写入端源码里的不变式（`dsh-session/lib/index.js`）。
- **✅ 已补：首次新建也能撤**（2026-10-04）。原来 `dsh_new` 在 `_where` 拿不到旧会话
  （那条线从没建过会话）时**不压栈**，于是「刚开好就想撤」只会得到一句
  「最近没有可以撤回的会话操作」——主人在测试小号那条全新线上真踩到了。
  现在：`before` 为空**也压栈**（记 `from:""`），`dsh_undo` 遇到 `from` 为空时
  **不 adopt、但仍然把那间新建的归档收掉**，回一句
  「这条线上原本没有会话，已经把你刚建的那间 … 收掉了」。
  实测（手工造一条 `{"op":"rebind","from":"","to":…}` 记录 → 说"撤回刚才新建的那间"）通过，
  记录也被正确弹出。**教训：「没有上一间可退」不等于「什么都不该做」。**
- **实现要点（都不是顺手能猜到的，务必记牢）**：
  1. **DSH 的"归档"不叫 `session/archive`，叫 `workspace/archiveSession`**（在工作区控制器上，
     请求体 `{sessionId, stopActivity?}`）。**DSH 没有删除会话的 RPC** —— 所以"撤回"只能做成
     **归档 + 切回旧会话**，**不能真删**。`unarchiveSession` / `pinSession` / `unpinSession`
     也都在这个控制器上（`@deepseek-ai/dsh-api-workspace-controller`）。
  2. **星驿的描述符表漏收了 `workspace/unarchiveSession`**：`lib/rpc-methods.js`（84 条，由
     **已停止发布**的 `data/p5_rpc_descriptors.json` 生成）里只有 `archiveSession`。
     而星驿对 `allowedRpcMethods` 做**加载期**校验（`lib/index.js:2955`），
     "不在描述符表里"直接抛错、**插件直接起不来**。⇒ 仓库根新增
     **`patch_relay_rpc_methods.py`**（幂等，带 `--revert` / `--path` / `--all`），
     给 nanxi 的 relay 补上这条描述符并把 `RPC_METHOD_COUNT` 84 → 85。
     ⚠️ 它改的是 `node_modules` 里的**上游产物**，**升级 dsh-astrbot-relay 后会丢，要重跑**。
     （`RPC_METHOD_COUNT` 只出现在报错文案里、不参与校验，改它只为自洽。）
  3. **星驿的配置白名单**（`<NANXI_DSH_HOME>\profiles\nanxi\cordis.patch.yml` 的 `allowedRpcMethods`）
     要同时写进 `workspace/archiveSession` 与 `workspace/unarchiveSession`。
  4. **撤销栈**存在台账 `workbench.json` 的 `__undo__` 键下（每个对话一个栈，最多 12 步）。
     **四个压栈点**：`_rebind`（换工作台新建）、`_attach`（接手／回到）、`dsh_fork`（分支）、
     `dsh_archive`（归档）。每次**改映射之前**都要压一条，否则 `dsh_undo` 无从知道该退回哪里。
- **⚠️⚠️ 本次踩的大坑：DSH 插件有 HMR，改 `cordis.patch.yml` 会【立刻】重载 relay。**
  我先改了配置（加 `workspace/unarchiveSession`）、**后**才打描述符补丁 —— 中间态里那条方法
  "不在描述符表里"，relay 重载即失败，`/astrbot-relay/*` **全部 404**。
  AstrBot 侧的表现**极具误导性**：`dsh_task` 看似被调用、群里却什么也没有，
  日志里只有一行 `[nanxi_dsh] 回家失败（不影响本轮结果）：HTTP 404`。
  ⇒ **改这类插件的顺序**：**先补描述符、再改配置**（或两个都改完再重启），别让中间态暴露给 HMR。
- **🔎 三步定位「南汐的 `dsh_task` 突然什么都不干」**（本次实测有效）：
  1. `netstat -ano | Select-String ":3081\s+.*LISTENING"` —— DSH 进程在不在；
  2. `curl -H "Authorization: Bearer <token>" "http://127.0.0.1:3081/astrbot-relay/where?conversation=probe"`
     —— **200 = relay 正常；404 = relay 没挂上**（此时 DSH 本身可能还活着：
     `GET http://127.0.0.1:3081/` 仍回 `dsh web authentication required`，**别被它骗了**）；
  3. 对照主实例 `http://127.0.0.1:3080/astrbot-relay/where` 是否 200 —— 区分"relay 坏了"还是"整机网络问题"。
- **⚠️ 重启 nanxi DSH 的两个前提**（本次都踩到）：
  ① `启动\start-nanxi-dsh.ps1` **见到端口已在监听就直接退出**（*"looks like it is already up"*），
     **不会**替你清理半死的旧进程 ⇒ 重启前必须先 `taskkill /F /PID <占用 3081 的那个 pid>`；
  ② 仍然**让主人双击 bat** —— agent 的 `Start-Process` 会把实例挂在主 DSH 的 job 里，
     主 DSH 一重启就连带陪葬（与 §5.6「AstrBot 是怎么死的」同一条铁律）。
- **`instance_list` 会把 3081 判成 `non-dsh`**：这是**已知误判**（它认不出跨 HOME 的实例），
  不代表那上面没有 DSH —— 用"3081 根路径是否回 `dsh web authentication required`"判断更可靠。
- **⚠️ 星驿的控制面把【失败也包在 HTTP 200】里**：`/rpc` 的响应是 `{"ok":true,"value":…}`
  或 **`{"ok":false,"error":{"code":…,"message":…}}`**。`_unpack` 只看 HTTP 状态码 ⇒
  失败会被**当成成功**：插件在群里报「归档了」、台账还记一笔假的撤销记录（2026-10-04 真踩过）。
  已在 `_rpc` 里拆信封：`ok is False` 就抛错（带 code + message）。**加新 RPC 调用时别绕过 `_rpc`。**
  ⚠️ 另外 `gateway/cancelled（Remote invocation … was aborted）` 是**调用被中止**，
  不等于"方法不可用"——用不存在的 sessionId 试 `archiveSession` 拿到过它，换真实 id 立刻 `ok:true`。
- **⚠️ DSH 的"归档集"是按 session 所属上下文返回的**：`/workspaces` 里每个 board 各带自己的
  `archivedSessionIds`（多数只有 1 个），而 `archiveSession`/`unarchiveSession` 返回的
  `value.archivedSessionIds` 是**那个 session 所在上下文**的全量集合（实测 70+ 个）。
  ⇒ 想确认"某间到底有没有被归档"，**别拿 board 的短列表判断**
  （本项目因此误判过一次，白折腾了好几轮），直接读权威文件
  **`<NANXI_DSH_HOME>\storages\workspace.json` 的 `.global.archivedSessionIds`**。
- **✅ 四类撤回端到端实测（2026-10-04 20:1x，测试群 `<TEST_GROUP_ID>`）**：

  | 我说的 | 她调的 | 结果 |
  |---|---|---|
  | 「把我们现在这间归档一下」 | `dsh_archive{}` | 群里「归档了（能撤回）」；归档集 71 个，含目标 |
  | 「撤回刚刚那个归档」 | `dsh_undo{what:'归档'}` | 归档集 71 → 70，目标被移除 |
  | 「另开一个分支试试」 | `dsh_fork{}` | 「分了一间副本出来（继承 552 条上下文）」 |
  | 「撤回刚才那个分支」 | `dsh_undo{what:'分支'}` | 会话线回家 ＋ 副本进归档集（`workspace.json` 权威确认） |
  | 「去 qirta 数一下有几个文件」 | `dsh_task{at:'qirta'}` | 「**换到** qirta（**新开**了一间会话）」＝ rebind |
  | 「撤回刚才换工作台新建的那间」 | `dsh_undo{what:'新建'}` | 「已退回到上一间会话…顺手把那间多出来的也归档了」 |

  - **判别测试（证明 `what` 真的生效，也是揪出 docstring 坑的那次）**：先归档、再分支
    （栈顶变成 fork），然后说「把刚才那个**归档**撤回掉」→ 她精确撤掉**栈底那条归档**、
    留下 fork，会话线仍停在分支副本。**若 `what` 被忽略，就会错撤栈顶的分支。**
  - **同样重要的反向确认**：栈里只有 `adopt` 时她说「撤回新建」，如实回
    「最近这几步里没有『新建』可撤；能撤的是：接手」—— **不瞎撤**，这正是想要的行为。
  - **触发 rebind 的前提**：台账里**已有**那个项目的会话时会走 `_attach`→`adopt`（群里显示「**回到**」），
    只有**台账里没有**的项目才 `rebind`（显示「**换到**…新开了一间」）。
    所以想复现"撤回新建"，得挑一个她没去过的项目（本次用 `qirta`）。
  - 顺带验到：`@南汐 去 xtlr 看一眼有什么` 她**正确地用了 `dsh_look`** 而不是切工作台 ——
    "看板类问题别换工位"这条工具描述约束是生效的。

**✅ 2026-10-03 新增：测试 bot（第二个 QQ 号）已就绪 —— 南汐现在可以被「自动验收」了。**

- 测试小号 **`<TEST_BOT_QQ>`**（昵称 `deepseek`）跑在 SnowLuma 的**第二个独立 QQ 实例**里
  （`HOME=/app/.local/share/qq2`，即官方多实例开关 `SNOWLUMA_EXTRA_QQ_HOMES` 的机制），与主号**完全隔离**；
- 它在**容器内**开了 OneBot HTTP **`127.0.0.1:3010`**（**不占宿主机端口**，靠 `docker exec` 访问），
  并以 wsClient 连 AstrBot 的**独立平台 `onebot-qq-test`（3003）**；
- ⚠️ **两个 bot 必须各占一个 AstrBot 平台实例**（别图省事塞进同一个）：
  `send_by_session()` 主动发送时传 `event=None` ⇒ `routing_params` 为空 ⇒
  同一平台有**两个连接**时 `call_action` 选不出目标 ⇒ 抛 `ApiNotAvailable` ⇒
  **AstrBot 全部主动发送**（`notify_owner` 群通知、mas 播报）返回 HTTP 400。
  2026-10-03 实测踩过并已修复（变更记录见 `南汐测试bot-使用说明.md` §10）；
- **测试群 `<TEST_GROUP_ID>`**（群名「自己」，**仅 4 人**：主人 + 北晨3号 + deepseek + 南汐，无外人）；
- 工具 **`tools\nanxi-test.ps1`**（`status`/`send`/`read`/`test`/`wait`/`raw`）：一条命令跑完
  「发消息 → 等南汐回复 → 报延迟」；技能 **`nanxi-bot-e2e-test`**；
- 实测：`@Nanxi 1+1等于几？` → 南汐 **4 秒**回复，且**回复由主号发出**（`self_id` 路由正确、不双回复）；
- ⚠️ **必须 `danger-full-access`**（要用 docker CLI）；⚠️ **容器重启后第二实例不会自动起**
  —— 跑 **`启动\恢复测试bot.ps1`** 即可（一条命令；若小号停在扫码界面则需主人扫码，
  **务必勾「自动登录」**否则下次重启还要重扫）。「重建容器持久化」2026-10-03 实测失败
  （新容器 `/usr/local/bin/node: Operation not permitted` → 重启循环，已回滚），**暂时搁置** ——
  详见 **`南汐测试bot-使用说明.md` §6**。

---

## 0. 一句话概述

**南汐是一只 QQ 猫娘机器人（QQ `<BOT_QQ>`），主人是 `<OWNER_QQ>`。** 它由三层组成：
- **SnowLuma**（Docker 容器）= QQ 登录/协议端，把 QQ 消息转成 OneBot v11；
- **AstrBot**（Python 进程）= 聊天大脑，注入"南汐"傲娇猫娘人格，对接 DeepSeek 生成回复；做白名单/主人识别；
- **DSH（DeepSeek Harness，本地 3080 端口）** = 南汐的"工具型执行 agent"，用完整工具（文件/终端/搜索）干实事。

本工作目录 `<PROJECT_ROOT>` 既是项目部署文件夹，也是一个 git 仓库（`git log` 有完整历史）。

---

## 1. 三组件与链路（重要，先记住这张图）

```
QQ 群（白名单 4 个，主要 <TEST_GROUP_ID>）里 @南汐(<BOT_QQ>)
        │ QQ 消息
        ▼
┌──────────────────────────────────────────────┐
│  SnowLuma  ← Docker 容器（QQ 登录端）         │
│   端口：6081(noVNC) 5099(WebUI) 3000(HTTP)     │
│         3001(WS服务端)  VNC密码在部署说明      │
└──────┬───────────────────────────────────────┘
       │ OneBot 反向 WebSocket（作为客户端连入）
       │  → 连 AstrBot 的 3002
       ▼
┌──────────────────────────────────────────────┐
│  AstrBot  ← Python 独立进程（聊天大脑）       │
│   · 端口：6185(WebUI/API) 3002(OneBot反向WS)  │
│   · 白名单：4 个群（见 platform_settings）    │
│   · 主人识别：只有 <OWNER_QQ> 叫"主人"         │
│   · 对话走 DeepSeek(deepseek-chat) + 南汐人设 │
└──────┬───────────────────────────────────────┘
       │ OpenAI 兼容 API
       ▼
   DeepSeek (api.deepseek.com/v1)   ← 外部大模型
```

**另外三条独立的"执行 / 播报"通道：**
- **DSH Web API（127.0.0.1:3080）**：南汐的 `/dsh <指令>` 走这里，用 DSH agent（完整工具）执行任务并回结果。
  ⚠️ **2026-10-03 起已失效（401）** —— DSH 0.2.0 加了认证，详见文首「最新状态」；另注 0.2.0 的流端点已由 `/api/events.mux` 改为 **`/api/remote.mux`**。
  ✅ **但它已被【星驿】取代**（同一天打通）：星驿是**跑在 DSH 进程内**的桥接插件，自己在
  `127.0.0.1:3080/astrbot-relay/*` 开端点、**进程内**投递，所以**不碰 Web API、不受认证影响**。
  群里发 `@南汐 dsh <指令>` 即可（触发前缀就是 `dsh `）。详见文首「星驿链路」那一段。
- **DSH 任务完成通知（DSH 插件 `dsh-email-notify`，已改造）**：DSH 里一次任务干完后，由 agent 自己调工具 `notify_owner(message)` → POST AstrBot `im/messages` → 发到**群 `<TEST_GROUP_ID>`**。**已不再发邮件**（SMTP 代码保留但不再调用）。插件在 DSH 侧：`<DSH_WORKSPACES>\dsh\plugins\dsh-email-notify\`；通知配置 `~/.dsh/dsh-qq-notify.json`（`astrbot_url`/`im_api_key`/`umo=onebot-qq:GroupMessage:<TEST_GROUP_ID>`）。改完插件要**重启 DSH** 才对新生效。
- **游戏日常通知（`<PROJECT_ROOT>\游戏通知\`）**：mas（游戏自动化）跑完游戏任务后，由 mas **全局通知里的「自定义 Webhook」**（mas「设置 → 通知设置 → 自定义渠道」）**直连** AstrBot 发送接口 → 机器人主动发到群 `<TEST_GROUP_ID>`。**不过 LLM、不是回复任何人**。

### ⚠️ 群 `<TEST_GROUP_ID>` 里会出现机器人"主动发"的消息（改聊天逻辑前必读）

游戏通知模块会让**机器人自己**往群里发通知（**不是**有人 @ 南汐，**不是**对谁的回复，也不需要任何 AI 去接话）：

| 触发 | 群里会出现的消息 |
|---|---|
| mas 跑完某个游戏任务 | **mas 原生报告格式**（模板 `{title}\n\n{content}`）：<br>`09-26 \| MAA的自动代理任务报告`<br>（空行）<br>`任务开始时间: …, 已完成数: 1, 未完成数: 0` … `AUTO-MAS 敬上` |

要点：
- 格式就是 **mas 自己的标准报告**（第 1 行 `{title}`、空行后 `{content}`、末尾 `AUTO-MAS 敬上`），与群友用官方机器人转发出来的**完全一致**。那句签名是 mas **自动附加**的（源码常量，模板去不掉），主人已确认**保留**，因此**没有**再加中间服务（曾试过中继方案，主人嫌多一个进程，已撤）。
- **一次游戏日常可能收到多条**（「代理结果」+「统计信息」是两次独立通知，全局 Webhook 两种都响应；多个脚本/账号各算一次）。想少收点可在 mas「设置 → 通知设置」关掉**推送统计信息**。
- **主项目 AI 不需要对它们做任何处理**（不接话、不转述、不当成用户消息）。
- 若看到**语气丰富、每次不同**的类似广播（如"哼，笨蛋主人，mas 那家伙…"），那是**旧方案**（bat + DeepSeek 现场生成）在生效 → 去 mas 里清空该用户的「任务后执行脚本」。
- mas 实际版本是 **v5.6.0-beta.1**（安装目录名仍叫 `AUTO-MAS-Full-v5.3.1-x64`，**别信目录名**）；其后端 HTTP API 在 **`127.0.0.1:36163`**，配置通知走它最稳（见 `游戏通知\apply_mas_webhook.py`，默认即用此 API）。
- 详细说明见 `游戏通知\说明文档.md`（含"会发送什么"完整清单与给主 AI 的注意事项）。

---

## 2. 关键路径速查表（哪些是你的，哪些是上游/别人的）

| 路径 | 作用 | 归属 |
|---|---|---|
| `启动\一键启动.bat` / `启动\start_all.ps1` | 一键启动 SnowLuma + AstrBot（幂等） | 本项目 |
| `启动\stop_astrbot.bat` | 只停 AstrBot（按端口 6185/3002） | 本项目 |
| `启动\一键关闭.bat` / `启动\stop_all.ps1` | **一键关闭**：停 AstrBot（同样只按端口）+ `docker stop snowluma`；加 `-DryRun` 只显示会停什么、不动手 | 本项目 |
| `run_astrbot.py` | AstrBot 启动器（设置 pywin32） | 本项目 |
| `patch_astrbot_forward_name.py` | 把合并转发卡片的显示名从 `AstrBot` 改回/改成 `南汐`（幂等）。**升级 AstrBot 后要重跑** | 本项目（补丁） |
| `patch_astrbot_stop_reply.py` | 把内置 `stop` 命令的两条英文回执改成中文（`（已经叫停了 N 项任务）` / `（这边没有正在跑的任务）`），幂等、带 `--revert` / `--dry-run`。**升级 AstrBot 后要重跑** | 本项目（补丁） |
| `patch_relay_rpc_methods.py` | 给星驿 `lib/rpc-methods.js` 补 `workspace/unarchiveSession` 描述符（84→85 条），幂等、带 `--revert` / `--path` / `--all` / `--dry-run`。**升级 dsh-astrbot-relay 后要重跑** | 本项目（补丁） |
| `patch_relay_approval_bridge.py` | 堵上**审批没被星驿接管**：审批 waterfall 原来只按 `agent.id` 反查网桥（`bridgeByAgent` 遍历 `bridges` 比 `bridge.agent?.id`），一旦那个 agent 换了实例（会话重 attach / 子 agent / 尚未 attach）就比对失败 ⇒ `next()` ⇒ **落到 DSH 自带的审批框**（GUI 里那个「等待审批/允许一次」）——IM 侧**完全收不到**、主人不会被通知，而且**不受星驿 120 秒超时约束**，会一直挂着（2026-10-04 实测：挂了 4 分多钟没人知道）。改成两级反查 `bridgeByAgent(agent.id) ?? bridgeBySession(agent.session)` —— `bridgeBySession` 星驿本来就写了（按 session **对象身份**比，注释说"不比 id，避免同名会话误伤"），只是没接在这条路上；并在两者都认不出时 `log.warn` 记下 `agent.id`，下次直接从日志定位。幂等，带 `--revert` / `--dry-run` / `--path` / `--all`。⚠️ **改完必须重启 DSH 实例**；升级 `dsh-astrbot-relay` 后会丢，要重跑。⚠️ 仍未覆盖「bridge 在但 `bridge.agent` 还没设」——那就靠那条日志继续查 | 本项目（补丁） |
| **`复盘-南汐DSH插件加载排查.md`** | 📋 **想给南汐做"正规 DSH 插件"（B 计划）之前先读这份**。里面是 2026-10-04/05 六轮尝试的逐轮记录（推断 → 做法 → 结果 → **为什么错**），以及 **12 条已确证的硬事实**（判"DSH 跳过某个 bundle"只能看 **stderr** 上的 `skipping profile bundle "…"`；`failed to import` 只是 `entry.fiber === undefined`、真错被吞；`link:` 装的插件解析不到 `@deepseek-ai/*`；`dsh plugin` 是 pnpm 的透传别名…）和 **3 条 PowerShell 坑**（`.ps1` 必须带 UTF-8 BOM，否则中文注释会让 PS 5.1 按 ANSI 解码报错 —— 而 `Parser::ParseFile` 会说"语法 OK"；PS 会缓冲原生命令输出导致日志运行中永远 0 字节；外层 `-RedirectStandardOutput` 会抢掉 ps1 自己的日志文件）。**当前状态：插件通过了全部加载检查但仍未生效，卡在"加载层之后"，已按主人决定收手。** | 本项目（复盘） |
| `patch_relay_steer.py` | 给星驿的 `POST /message` 加 **`mode: "steer"`（插队）**：透传给 DSH 的 `agent.steer` —— 投到当前 turn **最近的 step 边界**，**不等它跑完**（`followup` 才要等）。只改 `lib/index.js` 里**投递用户消息的那一处**；⚠️ 该文件里 `followup(createUserMessage(` 出现**两次**，另一处是**自主心跳**（`source:{kind:'plugin'}`），**绝不能一起改**，所以锚点带上了那处独有的注释。幂等，带 `--revert` / `--dry-run` / `--path` / `--all`。⚠️ **改完必须重启对应的 DSH 实例**（HMR 不重新 import `lib/*.js`）；升级 `dsh-astrbot-relay` 后会丢，要重跑 | 本项目（补丁） |
| `patch_relay_session_title.py` | 让星驿**别再覆盖**用户自己起的会话名，改成「原标题 + `_南汐`」（新配置项 `sessionTitleSuffix`；星驿自建的仍用模板）。改 `lib/session-title.js` + `lib/index.js`，幂等、带 `--revert` / `--dry-run` / `--path` / `--all`。⚠️ **升级 dsh-astrbot-relay 后要重跑；改完必须重启 DSH（HMR 不会重新 import）** | 本项目（补丁） |
| `dsh_cli.js` | 向 DSH Web **创建/复用**会话 + 发任务 + 收回复（JSONL 输出）。子命令：`--list-sessions`（列会话）、`--cancel <sid>`（急停）。⚠️ **2026-10-03 起依赖的旧客户端已 401，待随 qq-bridge 上游 v0.2.0-r3 一起修** | 本项目 |
| `astrbot_plugin_dsh\main.py` | AstrBot 的 `/dsh` 插件 + 自然语言意图拦截（**已归档**，被星驿取代） | 本项目 |
| `astrbot_plugin_nanxi_dsh\` | **南汐自主调用 DSH**：注册 `@filter.llm_tool` 工具 `dsh_task`，南汐自己决定把活交给 DSH；过程流式回帖、结果由南汐人设转述、仅主人可用。与星驿共存、共用同一 DSH 会话 | 本项目（源码在仓库根，部署副本拷进 `astrbot\data\plugins\`） |
| `astrbot_plugin_petpet\` | 摸头杀插件：`/摸头` 生成摸头 GIF（Pillow 渲染器 + 手部素材），详见其 `README.md` | 本项目 |
| `游戏通知\` | 游戏日常完成 → 机器人**主动**播报（mas **全局** Webhook 直连 AstrBot；`apply_mas_webhook.py` 走 mas API 配置） | 本项目 |
| `mas待修问题.md` | `/mas` 自动收录的**待修问题清单**（编号/状态/位置/严重度；状态可直接手改） | 本项目（进 git） |
| `mas_issue草稿\` | `/mas草稿 N` 生成的 issue 草稿（按 mas 官方模板写，等主人点头才提交） | 本项目（进 git） |
| `mas答疑记录.md` | mas 答疑的完整流水归档 | 本项目（进 git） |
| `astrbot\` | **AstrBot 源码 + 数据**（上游 clone） | 上游（gitignore） |
| `qq-bridge\` | DSH Web API 客户端底座（`dsh_cli.js` 依赖 `src/dsh-client.js`）。⚠️ 本地停在 `c9e1f27`（0.1.x 世代），**上游已到 `v0.2.0-r3`（适配 DSH 0.2.0-rc.2）** —— 修复 `/dsh` 要更新它 | 上游（gitignore） |
| `snowluma\` | SnowLuma 发行包（实际跑 Docker 容器，此为本机手动版） | 上游（gitignore） |
| `astrbot\data\cmd_config.json` | AstrBot **核心配置**（DeepSeek/白名单/OneBot/南汐人设） | 上游数据（gitignore，含密钥） |
| `astrbot\data\data_v4.db` | AstrBot 数据库（人设、会话、api_keys、cron） | 上游数据（*.db gitignore） |
| `部署说明-南汐QQ机器人.md` | 部署/运维/排障说明 | 本文档 |
| `南汐自主智能体-目标与路线图.md` | 愿景 + 分阶段路线 + 当前状态 | 本文档 |
| `游戏通知\说明文档.md` | 游戏通知模块用法 | 本文档 |
| `游戏通知\教程-让mas通知发到QQ群.md` | **可分享给群友的通用教程**：AstrBot 建 im-scope API Key → 查平台 ID → mas 配全局自定义 Webhook → 发到 QQ 群（含排障/速查；不含本机密钥） | 本文档 |
| `环境勘察报告-20261003.md` | **2026-10-03 全面环境勘察**：服务/版本现状、`/dsh` 失效根因（DSH 0.2.0 认证）、现成轮子清单、待办优先级 | 本文档 |
| `计划-南汐与DSH分层协作.md` | **新方向的设计书**：南汐（主 agent）↔ DSH（执行 agent）分层协作 —— 自主判断调用、流式反馈、审批转述给主人、`@filter.llm_tool` 机制与事件流协议依据 | 本文档 |
| `计划-南汐会话调度与DSH多实例.md` | **未完成事项清单 + 多实例调研结论 + 踩坑存档**：南汐的会话调度（看板/出差/自动回家/分支/黑白名单）待验证项、独立 DSH 实例的三层方案、官方多实例机制与 `storages/` 无锁这个真坑、本次事故的两条铁律 | 本文档 |
| `tools\nanxi-test.ps1` | **南汐端到端测试工具**：用测试小号 `<TEST_BOT_QQ>` 在群 `<TEST_GROUP_ID>` 发消息 / 读回复 / 判延迟（token 运行时从容器读，不落库）。⚠️ 需 `danger-full-access` | 本项目 |
| `南汐测试bot-使用说明.md` | **测试 bot 说明书**：原理、用法、容器重启后的恢复步骤、持久化（重建容器）与回滚命令、踩坑表 | 本文档 |
| `tools\extra-qq.conf` | 测试小号第二实例的 supervisor 配置模板（**进 git**；容器重启后 `docker cp` 回去 + `supervisorctl reread/update` 即可恢复。⚠️ DBUS 必须用 `%(ENV_…)s` 插值，别硬编码） | 本项目 |
| `启动\恢复测试bot.ps1` | **一键恢复测试小号**：容器重启后跑它即可把第二实例拉回来（登录态在卷里，**不用重新扫码**）。需 `danger-full-access` | 本项目 |
| `_scripts_archive\` | 历年一次性调试/勘测脚本（`probe_*`/`fetch_*` 等），**非正式组件**。⚠️ 该目录已进 `.gitignore`（新文件默认不入库，需要时 `git add -f`），但里面**早期两个文件**历史上已被跟踪 → 属混合状态 | 历史存档 |

> **红线**：`astrbot\`、`qq-bridge\`、`snowluma\` 都是上游/别人代码，别改动，只在需要时读取。真正会改的是本项目自己的那几份。
> **唯一例外（已知且有意为之）**：`astrbot\astrbot\core\pipeline\result_decorate\stage.py` 的转发卡片显示名 —— 上游写死 `"AstrBot"`，本项目改成 `"南汐"`（插件钩子够不着，只能改上游）。改完后用 `patch_astrbot_forward_name.py` 固化，**升级 AstrBot 后要重跑**，详见 §5.5。

---

## 3. 端口 / 服务速查

| 端口 | 归属 | 用途 | HTTP 入口 |
|---|---|---|---|
| 6081 | SnowLuma | noVNC 远程桌面（QQ 扫码窗口），VNC 密码见部署说明 | - |
| 5099 | SnowLuma | SnowLuma WebUI | http://localhost:5099 |
| 3000 | SnowLuma | OneBot HTTP | http://127.0.0.1:3000 |
| 3001 | SnowLuma | OneBot WebSocket（服务端） | ws://127.0.0.1:3001 |
| **3002** | AstrBot | OneBot 反向 WS **服务端** —— 平台 **`onebot-qq`**（南汐主号连入） | ws://0.0.0.0:3002/ws |
| **3003** | AstrBot | OneBot 反向 WS **服务端** —— 平台 **`onebot-qq-test`**（测试小号连入） | ws://0.0.0.0:3003/ws |
| **6185** | AstrBot | WebUI / API | http://localhost:6185 |
| **3080** | DSH Web | DSH 会话/agent API（⚠️ **0.2.0 起需认证 Cookie**） | http://127.0.0.1:3080 |
| **36163** | mas（AUTO-MAS） | mas 后端 HTTP API（配置通知走它最稳） | http://127.0.0.1:36163 |
| 3100 | qq-bridge | 桥接本地控制台（**当前未运行**） | http://127.0.0.1:3100 |
| **3010** | SnowLuma **测试小号** | 第二个 QQ 号 `<TEST_BOT_QQ>` 的 OneBot HTTP —— **只在容器内监听，未映射宿主机**，一律用 `docker exec` 访问 | — |

> 另：`8765` 是**可选**的「mas 通知中继」（`游戏通知\mas_notify_server.py`，用于剥掉 mas 自动附加的「AUTO-MAS 敬上」）。
> **当前未启用**（主人确认保留签名），mas 的 Webhook 直连 AstrBot。要用时手动跑该脚本并把 `apply_mas_webhook.py` 的 `MAS_WEBHOOK_URL` 改成 `RELAY_URL`。

**AstrBot WebUI 登录**：用户名 `astrbot`，密码见本地（部署说明 / 初始化日志；如失效，重启时加 `ASTRBOT_RESET_DASHBOARD_PASSWORD=1`，从日志读 Initial password）。

---

## 4. 关键凭据与"别泄露"（★★★★ 安全红线）

> ⚠️ **本仓库不存任何明文密钥**。下面的"位置"告诉你**去哪儿读**，而不是把值写在这里——因为本文件会进 git，一旦推远端就泄露。实际值永远只在本地被 gitignore 的文件里。

| 凭据 | 去哪儿读（本文件不写明文值） |
|---|---|
| DeepSeek API key | `astrbot\data\cmd_config.json` 的 provider 段；或 `游戏通知\config.json` 的 `deepseek_api_key` |
| AstrBot im-scope API key | `游戏通知\config.json` 的 `im_api_key`；该 key 也注册在 AstrBot 数据库 `astrbot\data\data_v4.db` 的 `api_keys` 表 |
| SnowLuma OneBot accessToken | `onebot_<BOT_QQ>.json`（该文件被 .gitignore 排除） |
| AstrBot WebUI 密码 | 见第 3 节登录行（如需重置：加 `ASTRBOT_RESET_DASHBOARD_PASSWORD=1` 重启，从日志读） |

> **规则**：任何时候都不要把上面这些值写进"会提交到 git 的文件"里。造 key / 改含密钥配置时，先 `git check-ignore <file>` 确认它是否会被排除。`.gitignore` 已排除：`astrbot/data/cmd_config.json`、`游戏通知/config.json`、`onebot_*.json`、`*.db`。

---

## 5. 环境事实 / 踩坑清单（★ 这些是"考古"成本最高的地方，务必先读）

### 5.1 沙箱与权限（本机为 Windows）
- **这个工作目录默认是 workspace-write**：能在 `<PROJECT_ROOT>` 下读写，但**不能写用户主目录 `~/.dsh`、`%TEMP%` 等平台临时区**（会被拒绝）。
- **DSH 的 `~/.dsh` 不能用**：headless 模式加载用户 ui-skin 插件会报 `ERR_MODULE_NOT_FOUND`。改用干净的工作区 `_dshhome`，并在 `_dshhome\sessions` 建一个 **junction** 链接到 `%USERPROFILE%\.dsh\sessions`，这样 DSH 会话能保留在用户真实目录、又能被工作区程序写。
- **docker CLI 在本沙箱被禁**（连接 npipe 无权限）。查容器/端口状态别用 `docker ps`，用 `netstat -ano` 看端口监听 + `Get-Process` 看 PID。
- **pip/uv 写 TEMP 被拒**：设 `UV_CACHE_DIR` / `UV_PYTHON_INSTALL_DIR` / `TEMP` 到工作区目录；npm 设 `npm_config_cache`。`uv sync` 的 build 临时文件 chmod 可能失败 → 用 `uv pip install --no-build`，sdist 手工 `tar.exe` 解压（Python tarfile 也被拒）。
- **AstrBot 的 mcp/pywintypes 报 `No module named pywintypes`**：用 `run_astrbot.py` 启动（它把 `win32`、`win32\lib` 加进 sys.path，并 `os.add_dll_directory(pywin32_system32)`）。

### 5.2 网络 / 代理
- 本机 Clash 代理：`http://127.0.0.1:7897`。**git 要用代理**：`git -c http.sslBackend=openssl -c http.proxy=http://127.0.0.1:7897 <cmd>`（否则拉不下/超时）。
- **优先用境内/镜像源**：npm 用 `npmmirror`（淘宝镜像）；pip/uv 用境内镜像。原版 `@deepseek-ai/dsh-host-apiproxy` 在公网 npm 404（它的依赖 `@deepseek-ai/dsh-paths` 公网找不到），但 `qq-bridge` 能装成功（走 npmmirror），里面带了可用的 `NodeApiClient`。
- `auto-proxy` skill 会优先找镜像、必要时开 Clash。

### 5.3 编码（Windows 批处理大坑）
- **写 `.bat` 时中文注释/中文参数极易乱码**（cmd 默认 GBK，UTF-8 无 BOM 会被读错 → 整行解析失败，连 `%~dp0` 都乱）。稳妥做法：
  - **bat 内用 ASCII**（注释用英文，游戏名用 ASCII 别名如 `arknights`），中文名由脚本内部 `GAME_ALIASES` 映射；
  - 需要中文时，用 **GBK(936) 编码**写 bat，或 bat 首行 `chcp 65001 >nul` + 文件存 ```UTF-8 无 BOM```（但中文注释建议开头就 `chcp`，且不要依赖注释中文）；
  - `.ps1` 用 **UTF-8 with BOM**；`.bat` 别用 BOM（BOM 会破坏首条命令）。
- `start_all.ps1` 曾因 `Get-Content -Raw` 默认 ANSI 被错误转码 → 改 `-Encoding UTF8`。`stop_astrbot.bat` 中文注释被 cmd 输出乱码 → 改纯 ASCII。
- `Test-NetConnection` PS5.1 不支持 `-Quiet` → 用 `.TcpTestSucceeded`。

### 5.4 AstrBot 主动发送（游戏通知用的通道）
- **要"南汐主动发到群"（非对话回复），走 AstrBot Open API**：
  `POST http://127.0.0.1:6185/api/v1/im/messages`
  body：`{"umo": "onebot-qq:GroupMessage:<TEST_GROUP_ID>", "message": [{"type":"plain","text":"..."}]}`
  header：`Authorization: Bearer <im-scope-api-key>`
- umo 格式 = `<platform_id>:GroupMessage:<群号>`。平台 id 从 `cmd_config.json` 读（当前 = `onebot-qq`）。`MessageType` 值是 `GroupMessage`（不是 `group_message`）。
- im scope 的 API key 在 `astrbot\data\data_v4.db` 的 `api_keys` 表（`key_hash` 是 pbkdf2；`key_prefix` 是原始 key 前 12 位）。**别写明文，从 `游戏通知\config.json` 的 `im_api_key` 读**。
- 鉴权链路验证：`GET /api/v1/im/bots` 应返回 `["onebot-qq", "onebot-qq-test"]`（2026-10-03 起有两个平台）。

### 5.5 其他坑
- **★ DSH 的审批归 `dsh-approval-gate` 插件管（与 `/dsh` 卡死直接相关）**：工作目录 `~/.dsh/auto-approve/`（`allowlist.json` 规则 / `audit.log` 审计 / `events.jsonl` 逐次事件）。规则：`allowRules: workspace-write` **自动允许**；`hardCategories`（deletion / credential / remote / system / bulk）→ **转人工**。
  2026-09-18 实测：**读**任意路径（含 `C:\Windows\System32\drivers\etc\hosts`）与工作区**内**操作**都不触发审批**；只有 agent 主动用 `sandbox_permissions` **提权**才被判 HARD → 转人工。
  ⚠️ **2026-10-03 更正：此前那句「因为 QQ 侧没有审批转发通道」是【错误归因】。** 实测阅读 DSH 事件流协议后的结论是：
  **DSH 一直在下发 `approval/requested` 事件（带 `toolName` / `reason` / `approvalId`），是 `dsh_cli.js` 根本没接这个事件、直接把它丢掉了**，于是 DSH 只能干等 —— **通道一直是通的，是我们没应答**。
  正确的事件与应答形态（现成实现：`qq-bridge/src/bridge.js:7939-7994` 捕获与转发、`7480-7500` 回复词匹配）：
  - 事件流每帧都是 **server-request 信封** `{ rpcId, payload }`；`payload.type` 取值：
    `session/event`（内含 `turn/start` / **`assistant/chunk`** 流式增量 / `assistant/message` / `turn/end`）、
    **`approval/requested`**、**`question/requested`**、`stream/error`。
  - 审批应答：`api.respond({ type:'client-response', rpcId, result:{ ok:true, value:{ sessionId, approvalId, outcome:'allowed-once'|'rejected' } } })`。
  - 提问应答：`result.value = { sessionId, answer: { answers: [{ id, selected: [], custom: '' }] } }`。
  - 回复词表（qq-bridge 在用）：`{'通过','同意','允许','批准','yes','y','approve','ok'}`。
  - ⚠️ **`respond` 是无状态 HTTP 调用**（带 rpcId 即可配对）⇒ **应答可以由另一个进程发起** ——
    这正是"长驻 `dsh_cli.js` 只负责报事件，AstrBot 插件另起进程回填"这个方案能成立的关键。
  - ⚠️ 0.2.0 起端点/客户端细节已变（`dsh-host-apiproxy` 不再存在），以 qq-bridge 上游 `v0.2.0-r3` 为准。
- **★★ AstrBot 的 `@filter.llm_tool` 参数 schema【只从 docstring 的 `Args:` 段解析】，完全不看函数签名（2026-10-04 踩过）**：
  `star_handler.py:632-635` 就是 `docstring = docstring_parser.parse(awaitable.__doc__ or "")`，
  然后 `for arg in docstring.params:` 逐个建参数 —— **没有 `Args:` 段，这个工具就等于没有任何参数**。
  后果**极其安静**：模型传进来的参数会在 `tool_loop_agent_runner.py:1183-1196` 被过滤掉
  （`valid_params = {k: v for k, v in func_tool_args.items() if k in expected_params}`），
  函数只拿到默认值，日志里**只有一行 WARN**：
  `[WARN] 工具 dsh_undo 忽略非期望参数: {'what'}` —— 功能照跑，只是参数**永远不生效**。
  实测：新加的 `dsh_archive(session)` / `dsh_undo(what)` 漏了 `Args:` 段，`what='归档'` 被丢弃后
  **碰巧**还撤对了（栈顶正好是那次归档），直到做一个「栈顶是分支、用户却说撤归档」的判别测试才暴露。
  **规矩**：`@filter.llm_tool` 的每个参数都必须在 docstring 里写成 `参数名(类型): 说明`
  （类型只能是 string / number / object / array / boolean）。
  **离线自检**（不用重启、不用发消息，10 秒出结果）：
  ```python
  import ast, sys; sys.path.insert(0, r"<astrbot>/data/site-packages")
  from docstring_parser import parse
  tree = ast.parse(open(r"<插件>/main.py", encoding="utf-8").read())
  for n in ast.walk(tree):
      if isinstance(n, ast.AsyncFunctionDef):
          print(n.name, [(p.arg_name, p.type_name) for p in parse(ast.get_docstring(n) or "").params])
  ```
  拿输出对照函数签名核一遍，缺的补上即可。
- **★★ AstrBot 的 `GreedyStr` 参数必须【不写默认值】，否则完全失效（2026-09-18 踩过）**：`astrbot\astrbot\core\star\filter\command.py` 的 `init_handler_md`（76-79 行）收集参数元数据时**有默认值就存默认值**（`self.handler_params[k] = v.default`）；而 `validate_and_convert_params`（102 行）用 `is` 判断贪婪：`param_type_or_default_val is GreedyStr`。所以写 `prompt: GreedyStr = None` 会被存成 `None` → 贪婪判定 False → 掉进 `if param_type_or_default_val is None:` 分支 → **只取第一个词**。
  症状：`/dsh 检查 <PROJECT_ROOT> 下所有 .md 文档，…` 只有"检查"两个字被交给 DSH。
  **正解**：`async def dsh(self, event: AstrMessageEvent, prompt: GreedyStr)` —— **不要写 `= None`**。GreedyStr 必须是最后一个参数；空参数时得到 `""`，不抛异常。
  验证脚本 `_scripts_archive\probe_param_and_trigger.py`：直接调用 AstrBot 真实的 `CommandFilter.validate_and_convert_params` 做修复前后对照（需先复刻 `run_astrbot.py` 的 pywin32 路径处理才能导入）。
- **★ `@filter.command` 只保证「命令在消息开头」，**不保证**「真的被 @ 了」（2026-09-19 踩过）**：`CommandFilter.filter`（`command.py:199-206`）判的是 `event.message_str.startswith("mas ")`（wake 阶段已按 `wake_prefix` 剥掉开头的 `/`），而**被 @ 的 At 段早在适配器里就没进 `message_str`**（`aiocqhttp_platform_adapter.py:384-389`：第一个 At 若是机器人就跳过不拼接）。
  ⇒ 后果：群里**任何人直接发 `/mas xxx`（完全不 @ 南汐）一样会命中命令**，等于把命令开放给全群（`/dsh` 同理，只是它另有「只有主人能用」的检查挡着）。**`/dsh` 与 `/mas` 现在都用同一道闸门 `_invoked_by_at_bot()` 修掉了。**
  要限制成"必须 @南汐"，只能自己加闸门：插件用 `_invoked_by_at_bot()` 检查 `event.get_messages()` 的**第一个有效消息段是 `At(自己)`**（跳过前导空白段；`@别人`、`/mas @南汐` 这种顺序错的都不算），不满足就 **`event.stop_event()` + return**。
  ⚠️ **别只 `return`** —— `star_request.py` 不会替你停事件，消息会继续进聊天 agent（南汐会把它当闲聊接话）。
  验证脚本 `_scripts_archive\probe_mas_gate.py`：导入**真实插件模块**，用假 event + 真组件跑 10 个用例（含"不 @"、"@别人"、"顺序颠倒"）。
- **★ 命令名后面【必须】跟空格，连写不认（2026-09-19 踩过）**：`CommandFilter.filter` 只有两条判定 ——
  `message_str.startswith(f"{full_cmd} ")` **或** `message_str == full_cmd`。所以 `/mas问题` 这种连写
  既不是 `"mas "` 开头也不等于 `"mas"` ⇒ **压根进不了 handler，而且不报错、静默无响应**（中文用户习惯连写，
  极易踩）。对策：把 `/mas问题`、`/mas草稿 N`、`/mas提issue N` 注册成**独立命令**
  （`@filter.command("mas问题")` 等），共用同一套底层方法 —— 现在**带空格和连写都能用**。
  ⚠️ 但**编号前也必须留空格**：`/mas草稿4` 依然不认，得写 `/mas草稿 4`。
  验证脚本 `_scripts_archive\probe_mas_command_forms.py`：直接构造真实 `CommandFilter` 跑 21 个用例
  （含"连写在 mas 命令下不命中"这个反例）。
- **`/dsh` 有两条触发路径，别混淆**：① `@filter.command("dsh")` —— 只认**消息开头**的 `/dsh`（`CommandFilter.filter` 用 `startswith` 判断），受 `wake_prefix` 制约；② `@filter.on_agent_begin()` 自然语言拦截 —— 只在**命令没匹配上、要进聊天 agent** 时才跑。
  ② 的规则经三次修正，最终形态（2026-09-18，13 个用例全过）：
  `(?:调用|用|让南汐|让|请|使用|帮我)\s*dsh(?![A-Za-z0-9_])\s*[:：]?\s*(.+)`；另有「新开个dsh会话 <指令>」这种说法 → 开新会话执行。
  **两个坑**：ⓐ 早期的兜底 `\bdsh\b…` 会让**任何**提到 dsh 的句子被劫持；ⓑ **`dsh` 后面不能用 `\b`** —— Python 的 `\w` **含中文**，`dsh看看` 里没有词边界 → 整条失配，**这正是自然语言拦截长期"完全没反应"的真凶**；改用 `(?![A-Za-z0-9_])`。
  钩子本身注册/激活都正常（插件 `_selfcheck()` 会在启动日志打印 `OnAgentBeginEvent handlers = [...]`），排查先看那行。开关常量 `NL_TRIGGER_ENABLED`。
- **★ AstrBot 内置 `/stop` 是什么、以及插件该怎么配合它（2026-09-18 查证）**：内置命令在 `astrbot\astrbot\builtin_stars\builtin_commands\main.py`，`stop` → `commands\conversation.py` 的 `stop()` → `core\utils\active_event_registry.py`：
  - `provider_settings.agent_runner_type` 属第三方（`THIRD_PARTY_AGENT_RUNNER_KEY`）→ `stop_all()`（会 `event.stop_event()`，真正掐断事件）；
  - 否则（我们本机是 `local`）→ `request_agent_stop_all()`：**只**给 event 设 `agent_stop_requested` 标志 + 调用**已注册的**停止回调，**不中断事件传播**。
  ⇒ **插件的长任务（如 `/dsh` 在 handler 里等子进程）靠内置 stop 是停不下来的**。正确接入点是
  `active_event_registry.register_agent_stop_callback(event, cb)`：注册后用户发 `@南汐 stop`（内置命令）就会回调你的 `cb`
  （**同步函数、不能 await** —— 要发异步动作得起线程），任务结束记得 `unregister_agent_stop_callback(event)`。
  **别自己注册同名 `stop` 命令** —— 会与内置命令双触发、回两条。
  本项目两条急停路径：`@南汐 stop`（内置命令 → 回调 → 取消 DSH 回合 + kill 本地子进程）、`/dsh stop`（我们自己的子命令 → `dsh_cli.js --cancel`）。
- **★ AstrBot 自带「长回复自动转合并转发」：`platform_settings.forward_threshold`（上游默认 1500；**本项目现为 300**）** —— `core\pipeline\result_decorate\stage.py:408-420`：仅对 `aiocqhttp` 平台，统计结果链里 `Plain` 的**总字数**，超过阈值就把整条包成一个 `Node`（合并转发）。
  ⚠️ **教训：别自己切分长回复**。我们曾把长文本切成每片 <1800 字的多条消息逐条发，结果每片都够不着 1500 的阈值，**上游永远没机会触发**（自己把现成功能废了）。已改回整条发送，交给上游。
  **本项目阈值 = 300**（调整轨迹：上游默认 1500 → 100 → **300**）：配置在 `astrbot\data\cmd_config.json` 的 `platform_settings.forward_threshold`（**该文件 gitignore、不进 git**，改它无需提交）。⚠️ **改完必须重启 AstrBot** —— `stage.py:42-43` 只在 pipeline 初始化时读一次，只改文件不生效。判断用的是 `word_cnt > threshold`（严格大于），所以"恰好 300 字"不合并、301 字才合并。
  🔧 **本地补丁：卡片上的发送者名字（改了上游文件，升级会丢）** —— 上游在 `stage.py:417` 把名字写死成 `name="AstrBot"`，本项目改成 `name="南汐"`。
  **插件侧改不了**：`on_decorating_result` 钩子在 `stage.py:158` **先跑**，Node 在 `stage.py:415` **才包** —— 钩子执行时那个 Node 还不存在（也不该让插件复制一遍上游的阈值逻辑）。
  因为 `astrbot\` 整个目录被 gitignore，这处改动**存不进 git** ⇒ AstrBot 升级/重装后要重跑仓库里的 `patch_astrbot_forward_name.py`（幂等，已经有"南汐"就跳过；找不到上游那一行会报错退出，不会乱改）。
  ⚠️ **阈值调低后必须知道的代价**：包成 `Node` 发生在**加 @ / 引用之前**（`stage.py:408-420` 先替换 chain，422-425 才判断 `can_decorate = all(isinstance(item, (Plain, Image)))`），而 `Node` 既不是 `Plain` 也不是 `Image` ⇒ **凡是超过阈值的回复会同时失去「@提问者」和「引用回复」**，群里变成一张不带指向的合并转发卡片；≤ 阈值的短回复不受影响，行为照旧。
  AstrBot 还有哪些现成能力（内置命令、一堆 `platform_settings` 开关、消息组件、停止回调、t2i…）见 **`AstrBot自带能力盘点.md`** —— 动手前先翻它，别重复造轮子。
- **AstrBot meme_manager 插件阻塞启动**：缺 boto3/tqdm。已把 `data/plugins/meme_manager.disabled` 移出 plugins 目录到 `_disabled_plugins`，别挪回去。
- **插件写错导入 = 静默不加载（★ 真踩过的大坑）**：`MessageChain` 只能从 `astrbot.api.event` 导入，`astrbot.api.message_components` 里**没有**它（那里只有组件类，文件内容就一行 `from astrbot.core.message.components import *`）。写错时 AstrBot 只在启动日志里打印 `Failed to import plugin ...`，插件**完全不生效**——`/dsh` 曾因此长期失效，2026-09-16 修复。
  排查法（把启动 stdout 落盘再 grep）：
  ```powershell
  Start-Process -FilePath "C:\Python310\python.exe" -ArgumentList "<PROJECT_ROOT>\run_astrbot.py" -WorkingDirectory "<PROJECT_ROOT>\astrbot" -WindowStyle Hidden -RedirectStandardOutput "<PROJECT_ROOT>\_test\astrbot_out.log" -RedirectStandardError "<PROJECT_ROOT>\_test\astrbot_err.log"
  ```
  然后看 `Loading plugin` / `Failed to import` / `Traceback`。
- **沙箱里 `taskkill` 会被拒**（`ERROR: Access denied`）：重启 AstrBot 杀进程需要 `danger-full-access` 权限；`启动\stop_astrbot.bat` 带 `pause`，也不适合非交互调用。用 `netstat -ano | Select-String ":6185\s" ` 取 PID 再 `taskkill /F /PID <pid>`。
- **查端口必须用 `netstat -ano`，别用 `Get-NetTCPConnection`**：后者在本沙箱**静默返回空**（不报错、也不给结果），会让人误判成"服务没在跑"。2026-09-18 已踩过（DSH 3080 明明在监听却查不到）。正确姿势：`netstat -ano | Select-String ":3080\s"`。
- **OneBot 反向 WS 地址**：aiocqhttp 的 WS 路由是 `/ws`。SnowLuma 的 `wsClients` 用 `ws://host.docker.internal:3002/ws`（别写成根路径）。
- **`/dsh` 会话在 DSH Web 里显示"未分组"**：✅ **2026-09-18 已解决**。根因不是"另一套参数"，而是 `sessions.create({cwd})` **不会**把会话 attach 到工作区。正解：先 `workspace.list` 按 path 取 `workspaceId`（未注册才 `workspace.create`，幂等），再 `sessions.create({ workspaceId, sessionId })` —— **`workspaceId` 与 `cwd` 互斥**。已实测：传 `cwd` 的会话不在 `sessionIds` 里，传 `workspaceId` 的立即出现在首位。
- **DSH 的 `session.create` 支持预分配 `sessionId`（★ 会话复用的实现基础）**：同 id 同 cwd 重复调用**幂等**返回同一会话；不同 cwd 报 `session-conflict`。裸 UUID 形态被接受（不需要 `session-` 前缀）。⇒ 用 SHA-256 派生确定性 id 即可让同一 QQ 身份永远复用同一会话，**无需 resume API**（HTTP 侧本就没有该 RPC）。
- **★ DSH 会按目录向上查找并注入 `AGENTS.md`（2026-09-18 踩过：工作区"隔离"被记忆穿透）**：DSH 从会话的工作目录开始**向上逐级查找 `AGENTS.md` 并注入**，且**更具体（更深目录）的优先级更高**。实测证据：把 `/dsh` 的工作区设成 `<PROJECT_ROOT>\nx_dsh` 后，agent 在一个**空目录**里仍准确答出主项目手册里的 AstrBot 端口（6185），并自述"来自项目手册 AGENTS.md"。
  解法二选一：① **彻底隔离**——把工作区放到祖先链上没有 `AGENTS.md` 的目录（如 `<DSH_WORKSPACES>\nx_dsh`）；② **原地隔离**——在**工作区目录内**放一份自己的 `AGENTS.md`（实测生效，agent 改按子目录说明作答）。本项目目前用 ②，`/dsh` 工作区 = `<PROJECT_ROOT>\nx_dsh`（内含隔离用 `AGENTS.md`）。
  另注：`session.create` 判重按 **cwd** 比对，所以**换工作区必须同时升 `SESSION_KEY_PREFIX`**（项目已由 `nanxi:v1` → `nanxi:v2`），否则新 key 派生的 id 会撞上旧会话报 `session-conflict`。
- **`~/.dsh/AGENTS.md` 是全局指令文件**（注入每个会话）；`dsh-config-manager` 的备份分区 `agentInstructions` 就是它。项目级 `AGENTS.md` 各仓库自带、默认不随配置迁移。本机目前**没有**全局那份。
- **★ `/dsh` 会话里的 DSH agent 会**自行**调用 `notify_owner`（会导致群里重复播报）**：DSH 的系统提示要求"任务完成时通知主人"，所以 `/dsh` 跑完一个任务后 agent 会自己 POST AstrBot 发一条群通知，而 AstrBot 侧还要发一条南汐转述 ⇒ **同一条任务在群里出现两条消息**。已在 `nx_dsh\AGENTS.md` 写入约束「不要调用 `notify_owner`，结果由上层转述」，2026-09-18 实测生效（约束前 agent 会说"已把结果摘要通过 QQ 通知主人"，约束后复杂任务的回复里再无此类字样）。
- **★★ 沙箱里禁用 `asyncio.create_subprocess_exec`（WinError 5 拒绝访问，2026-09-18 踩过）**：Windows 上 asyncio 的 subprocess 实现用**命名管道**接子进程 stdio，而本机沙箱**禁止打开命名管道** ⇒ 抛 `PermissionError: [WinError 5] 拒绝访问`；而 `subprocess.run` / `subprocess.Popen`（走**匿名管道**）完全正常。实测对照：
  ```
  [sync ] OK   rc=0 out='sync-ok'                       ← subprocess.run
  [async] FAIL PermissionError: [WinError 5] 拒绝访问     ← asyncio.create_subprocess_exec
  ```
  症状：P0-3 把 `subprocess.run` 换成 `asyncio.create_subprocess_exec` 后 `/dsh` 直接失效，南汐在群里回"哼，笨蛋主人，那个 DSH 根本就没跑起来啦！说什么'拒绝访问'…"。
  **正解**：`subprocess.Popen`（匿名管道）+ **后台线程**读 stdout 塞进 `queue.Queue` + async 侧 `await asyncio.to_thread(q.get, True, 1.0)` 取；超时用 `queue.Empty` 每秒醒一次重算剩余时间。既避开命名管道，又保住流式进度。验证脚本：`_scripts_archive\probe_subprocess_mode.py`（两种模式对照）、`_scripts_archive\probe_popen_stream.py`（复刻修复实现跑真实 dsh_cli.js）。
- **`provider_settings.identifier`**：主人识别靠人设里 `owner=<OWNER_QQ>` + `identifier=true`（让 AI 看到发送者 UserID/昵称），才能做到只有主人被称"主人"。

---

## 5.6 AstrBot 失联排查（★ 2026-09-19 新增）

**症状**：DSH 里的 agent 报 `notify_owner` "两次都 fetch failed"；mas 游戏通知也一起静默发不出。
**根因通常只有一个：AstrBot 根本没在运行**（不是 DSH 插件坏了、也不是密钥失效）。

排查与处理：
1. `netstat -ano | Select-String ":6185\s"` —— 没有 LISTENING 就是它没起。（⚠️ 别用 `Get-NetTCPConnection`，本沙箱静默返回空，见 §5.5）
2. **AstrBot 不是开机自启的**（见 §7）。DSH 升级 / 重启电脑后忘了双击 `启动\一键启动.bat` 就会这样 —— 本次就是这么发生的。
3. 起没起、为什么没的，看 **`logs\astrbot.log`** 与 **`logs\astrbot.err.log`**（2026-09-19 起由 `start_all.ps1` 落盘；启动时把旧日志归档成 `logs\astrbot-<yyyyMMdd-HHmmss>.log`，只留最近 5 份）。此前 AstrBot 的日志只走隐藏窗口的 stdout，**事后完全查不到**，这次只能确认"它确实不在"。
4. 起来之后**等十几秒再发**：OneBot 反向 WS 重连要时间，抢跑会拿到 `HTTP 400 Failed to send message`（服务端真实原因是 `aiocqhttp.exceptions.ApiNotAvailable`，即 AstrBot 手里还没有可用的 QQ 连接）。等到 3002 上出现 ESTABLISHED、且 `GET /api/v1/im/bots` 返回 `["onebot-qq"]` 再发就稳。
5. Node 的 `fetch` 只会给一句 `fetch failed`，别指望它自带原因 —— 直接按上面查 6185 更省事。

**★ 为什么"在 DSH 会话里帮用户把 AstrBot 拉起来"是徒劳的（2026-09-19 实测）**：
- `Start-Process ... run_astrbot.py`：进程**随该条命令结束被沙箱回收**（日志里能正常跑到 "AstrBot started"、适配器已连接，随后整个进程消失，无崩溃堆栈 —— 别误判成它自己崩了）；
- `Invoke-CimMethod Win32_Process Create`（WMI 脱离进程树）：被沙箱**拒绝访问**；
- 结论：**让用户双击 `启动\一键启动.bat`**。会话里最多只能临时验证链路，不要把常驻服务挂在自己的后台任务上。

**⚠️ 别用 `cmd /c` 包重定向来启动 AstrBot（2026-09-19 踩过；症状是"双击一键启动完全没效果"）**：给 `start_all.ps1` 加日志落盘时曾写成
`Start-Process cmd.exe -ArgumentList "/c", '"<exe>" "<script>" >> "<log>" 2>&1'` —— cmd 的 `/c` 引号剥离规则会把这条命令行吃坏：
**python 根本不会启动、日志文件也不生成**，而 `logs\` 目录却已经建好了（极易误判成"进程起来了但没监听"）。
**正解**：用 PowerShell 原生重定向，且 stdout / stderr 必须是**两个不同文件**（PowerShell 不允许二者同文件）：
```powershell
Start-Process -FilePath "C:\Python310\python.exe" -ArgumentList "<PROJECT_ROOT>\run_astrbot.py" `
    -WorkingDirectory "<PROJECT_ROOT>\astrbot" -WindowStyle Hidden `
    -RedirectStandardOutput "$logDir\astrbot.log" -RedirectStandardError "$logDir\astrbot.err.log"
```
⇒ 日志是**两个**文件：`logs\astrbot.log`（正常输出）+ `logs\astrbot.err.log`（报错）；归档分别叫 `astrbot-<时间戳>.log` / `astrbot.err-<时间戳>.log`，各留 5 份。
**改完启动逻辑必须实测**：启动后确认 `logs\astrbot.log` **有内容**、`netstat` 里 6185 变 LISTENING —— 只通过语法检查**不算数**（这次就是语法 OK、命令却根本没跑）。

**⚠️ 「AstrBot 活着但发不出消息」= 两个实例抢 3002（2026-09-25 踩过）**：症状是 6185 能开、WebUI 正常，但所有主动发送抛 `aiocqhttp.exceptions.ApiNotAvailable`，而 `netstat` 里 **3002 完全没有监听**。根因直接写在日志里（这次是靠新加的落盘才查到的）：
```
[Core] [ERRO] Task platform_aiocqhttp_onebot-qq failed: [WinError 10013] ...
  PermissionError: [WinError 10013] ... sock.bind(binding)
```
即**上一轮实例没退干净（或双击了两次），后启动的那个绑不上 3002**。⚠️ 3002 **不在** Windows 保留端口段里（`netsh int ipv4 show excludedportrange protocol=tcp` 可查，当时保留段只有 2548-2947 / 12333-12743 / 50000-50059），别往"端口被系统保留"方向查；`netstat` 无记录也不是"端口被占用"，恰恰是**没人绑上**。
**已加固 `start_all.ps1`**（2026-09-25）：① **并发锁** `logs\start.lock` —— 5 分钟内第二次双击直接退出，从源头防止两个实例抢端口；② **半死自愈** —— 检测到「6185 在 + 3002 不在」时，先 `taskkill` 掉监听 6185 的 PID 再重启；③ 启动后**轮询 3002 最多 60 秒**，绑上了才打印 `[OK] OneBot 已就绪`。
**判定口诀**：`6185 有 + 3002 没有` ⇒ 半死（重启自愈）；`两者都没有` ⇒ AstrBot 没跑；`两者都有` ⇒ 正常。

**⚠️ `qq-tool-restrict` 无限刷屏会把 DSH Web 拖垮（2026-09-25 踩过）**：症状是 dsh web 的 cmd 窗口疯狂刷新、`~/.dsh/logs/web-<时间戳>.log` 爆炸（实测两个实例 **131 MB / 92 MB**，8 分钟涨 66 MB），DSH Web 进程内存飙到 **1986 MB**。
日志形态：`[qq-tool-restrict] skip restrict dev_stage_promote: tools.restrict() names unknown global tool "..."` —— 它反复对一批**不存在的 `dev_*` 工具名**调 `tools.restrict()`，而每行还会打印**全量工具表**（约 1 KB/行），新日志里刷了 **19711 次**。
**处置（2026-09-25 已验证有效）**：在 profile 的 `~/.dsh/profiles/web/cordis.patch.yml` 末尾追加
```yaml
- id: qq-tool-restrict
  disabled: true
```
重启 DSH 后：新日志该字样 **0 次**、Web 进程内存回到 **357 MB**。
⚠️ **光重启没用** —— 21:41 那次重启后**立刻复发**（说明有持久来源），必须加这条禁用；也**别指望靠搜字符串定位**：`qq-tool-restrict` 在 web profile 的 package.json 依赖、用户级 + profile 级 cordis.patch.yml、`node_modules`（findstr 全扫、绕开 .gitignore）、`<DSH_WORKSPACES>` 全盘 findstr、Temp、storages 里**全都搜不到** —— 它是运行时拼出来的名字，直接按上面禁用即可。
（改动前的配置备份在同目录 `cordis.patch.yml.bak-before-disable-qq-tool-restrict`。）

---

## 6. 常用命令

```powershell
# 查看本仓 git 历史
git log --oneline

# 启动（双击 bat 亦可）
<PROJECT_ROOT>\启动\一键启动.bat

# 只停 AstrBot（按端口，不动其它 python 进程）
<PROJECT_ROOT>\启动\stop_astrbot.bat

# 一键关闭：停 AstrBot + SnowLuma 容器（-DryRun 只显示会停什么）
<PROJECT_ROOT>\启动\一键关闭.bat
#   powershell -NoProfile -ExecutionPolicy Bypass -File <PROJECT_ROOT>\启动\stop_all.ps1 -DryRun

# 手动启动 AstrBot
cd <PROJECT_ROOT>\astrbot
set PYTHONIOENCODING=utf-8
C:\Python310\python.exe <PROJECT_ROOT>\run_astrbot.py

# 转发卡片显示名补丁（幂等；升级/重装 AstrBot 后重跑一次）
C:\Python310\python.exe <PROJECT_ROOT>\patch_astrbot_forward_name.py

# 测试 AstrBot Open API 鉴权（im scope）
#   GET http://127.0.0.1:6185/api/v1/im/bots   header: Authorization: Bearer <key>

# DSH 会话/工作区探测（只读）：看工作区注册状态、会话归属、哪些会话"未分组"
& "C:\Program Files\nodejs\node.exe" <PROJECT_ROOT>\_scripts_archive\probe_workspace_session.mjs

# /dsh 底层直连自测（真跑一个 DSH 回合；同 key 复用同一会话）
& "C:\Program Files\nodejs\node.exe" <PROJECT_ROOT>\dsh_cli.js http://127.0.0.1:3080 "只回复三个字：连通了" --key "nanxi:v2:selftest"

# 列会话 / 急停（AstrBot 侧分别对应 `/dsh 会话`、`@南汐 stop`）
& "C:\Program Files\nodejs\node.exe" <PROJECT_ROOT>\dsh_cli.js http://127.0.0.1:3080 --cwd <PROJECT_ROOT>\nx_dsh --list-sessions --key "nanxi:v2:group:<TEST_GROUP_ID>:<OWNER_QQ>"
& "C:\Program Files\nodejs\node.exe" <PROJECT_ROOT>\dsh_cli.js http://127.0.0.1:3080 --cancel <sessionId>

# 游戏通知（mas 全局 Webhook）—— 走 mas API，无需关闭 mas
<PROJECT_ROOT>\venv312\Scripts\python.exe <PROJECT_ROOT>\游戏通知\apply_mas_webhook.py               # 预览
<PROJECT_ROOT>\venv312\Scripts\python.exe <PROJECT_ROOT>\游戏通知\apply_mas_webhook.py --apply --test

# （可选，当前未启用）去签名的中继：先跑 游戏通知\mas_notify_server.py，
# 再把 apply_mas_webhook.py 里的 MAS_WEBHOOK_URL 改成 RELAY_URL 并 --apply。
# 当前是【直连 AstrBot】并保留 mas 自动附加的「AUTO-MAS 敬上」。
# 旧的 预览mas通知配置.bat / 应用mas通知配置.bat 等同上面两条命令。

# 游戏通知（旧方案，手动备用）：只生成文案不发群 / 真发到群
<PROJECT_ROOT>\venv312\Scripts\python.exe <PROJECT_ROOT>\游戏通知\nanxi_notify.py arknights --dry-run
<PROJECT_ROOT>\venv312\Scripts\python.exe <PROJECT_ROOT>\游戏通知\nanxi_notify.py 鸣潮
```

> Python 环境：本机有 `<PROJECT_ROOT>\venv312`（venv，Python 3.12.x）；AstrBot 用 `C:\Python310\python.exe`。写 python 脚本尽量只用标准库（urllib/json/sqlite3），避免额外依赖。

---

## 7. 当前任务状态（诚实标注）

- ✅ **阶段 0**（QQ 聊天跑通）完成。
- ✅ **端到端验收能力（测试 bot）建成（2026-10-03）**：第二个 QQ 号 `<TEST_BOT_QQ>` 跑在 SnowLuma 的独立第二实例里，在私有测试群 `<TEST_GROUP_ID>` 充当"真实群友"；配合 `tools\nanxi-test.ps1` + 技能 `nanxi-bot-e2e-test`，南汐的群内行为**可被 agent 自动验收**（发消息 → 读回复 → 判延迟）。实测通过（4 秒回复）。⚠️ **容器重启后**第二实例需用 `启动\恢复测试bot.ps1` 拉回来（一条命令；若小号停在扫码界面则需主人扫码 —— **扫码时务必勾「自动登录」**，否则每次重启都要重扫）。「重建容器持久化」2026-10-03 实测**失败**（新容器 `/usr/local/bin/node: Operation not permitted` → 重启循环，当场已回滚、数据无损），**暂时搁置**，详见 `南汐测试bot-使用说明.md` §6.2 与坑表。
- ✅ **南汐自主判断调用 DSH（2026-10-03 深夜，实测通过）**：新插件 `astrbot_plugin_nanxi_dsh`
  注册 `@filter.llm_tool` 工具 **`dsh_task`**，南汐在对话里**自己**决定何时把活交给 DSH ——
  不再需要 `dsh ` 前缀，也不需要正则猜意图（旧 `/dsh` 那套的教训见 §5.5）。
  长输出按 `throttle_ms`/`flush_chars` **流式分片**、短输出整段交还给南汐**用人设转述**、
  仅主人可用（`owner_only=true`，因为 DSH 在本机是完全文件权限）。
  实测三条路径全过：自然语言自主调用 / 长输出流式 + 一句收尾 / 非主人被拒。
  另有 **`@南汐 stop` 急停**（约 1 秒中断 DSH 回合，实测通过）。
  ⚠️ 前置条件：人格的 `tools` 白名单必须含 `dsh_task`（**`[]` 等于一个工具都不给**，本机踩过）；
  另有一个更阴的坑 —— **模型会学着演上下文里出现过的"我做不到"**，详见文首「最新状态」。
- ✅ **游戏日常通知模块**完成并验证：mas 跑完游戏任务 → **mas 全局通知里的「自定义 Webhook」** → 固定话 + mas 报告标题发到群 `<TEST_GROUP_ID>`（**不过 LLM**）。已实测（mas 官方 `/api/setting/webhook/test` 返回成功、群里收到）。
  - mas 实际是 **v5.6.0-beta.1**（目录名仍写 v5.3.1），后端 API 在 **`127.0.0.1:36163`**；
  - 通知格式 = **mas 原生报告**（模板 `{title}\n\n{content}`，末尾带 mas 自动附加的「AUTO-MAS 敬上」），与群里其它机器人转发出来的**完全一致**；mas 的 Webhook **直连** AstrBot（主人确认保留签名，去签名的中继方案已撤，脚本仅留作备用）；
  - 配置走 **mas API**（`游戏通知\apply_mas_webhook.py`，幂等、`--test` 可立即验证），**无需关闭 mas**；
  - ⚠️ 2026-09-26 发现：**v5.6.0 升级重建了用户配置**（3→9 个），此前配的**用户级 Webhook 全部丢失** ⇒ 故改为**全局**方案；
  - 旧方案（bat + DeepSeek 现场生成）保留作手动备用；蔚蓝档案未做（mas 不支持）。详见 `游戏通知\说明文档.md`。
- ✅ **摸头杀插件**（`astrbot_plugin_petpet`）完成并已确认加载成功：`@南汐 /摸头` —— 引用图片 / 直接发图 / `@某人` / 默认自己头像 → 生成 112×112、5 帧透明 GIF。渲染器复刻网页版 toolwa.com/petpet（`petpet_render.py`，只依赖 Pillow），手部素材 `assets/hand.png`。详见 `astrbot_plugin_petpet\README.md`。
- 🔜 **阶段 1**（`/dsh` 完整工具执行）：
  - ✅ 2026-09-16 修掉 `MessageChain` 导入错误后，插件已确认加载成功（此前"`/dsh` 没反应"极可能就是插件根本没加载）。
  - ✅ **2026-09-18 会话复用 + 工作区归组完成**（P0-1/P0-2）：`/dsh` 现在按「群/私聊 + 发送者」派生确定性 sessionId，**复用同一 DSH 会话**（南汐记得之前做过什么）；会话以 `workspaceId` 创建 ⇒ **DSH Web 里不再显示"未分组"**。`/dsh -n <指令>` 开新会话。已实测（同 key 二次提问能答出上一轮内容）。详见 `阶段1-DSH桥接增强-计划.md`。
  - ✅ **2026-09-18 P0-3 进度反馈完成**：`dsh_cli.js` 改为 **JSONL 协议**（`start`/`progress`/`result` 各一行，调试信息走 stderr）+ 与事件流**解耦**的节流心跳（`--progress-interval`）；插件改用 **`subprocess.Popen` + 后台线程 + `queue`** 做流式逐行读（⚠️ **不能用 `asyncio.create_subprocess_exec`** —— 沙箱禁命名管道会报 WinError 5，见 §5.5，当天已踩并修复），长任务按「首条 ≥15s、间隔 ≥45s、最多 4 条」发"还在忙"提示（**只报活着，不发 DSH 中间文本**）。实测 9.9 秒的任务触发 3 条心跳。
  - ✅ **2026-09-18 P1-1 长回复**：先写了一版 `_chunk_markdown()` 本地切分（按 Markdown 边界、代码块/表格原子化），但**当天就发现是多余的** —— AstrBot 自带 `platform_settings.forward_threshold`（**现为 300 字**，见 §5.5）会把整条自动包成**合并转发**，而我们的分片把每片都压到阈值以下、**反而让上游永远不触发**。现已改回整条发送，`_chunk_markdown()` 保留作备用（详见 §5.5）。
  - ✅ **2026-09-18 P1-2 审批探测完成**：结论**暂不做转发** —— 实测工作区内操作与工作区外**只读**都不触发审批（不会卡），只有 agent **提权**才转人工；已补超时审批指引 + 在 `nx_dsh\AGENTS.md` 禁止 agent 提权。完整转发方案（协议已查清）记录待需要时再做。
  - ✅ 2026-09-18 修掉两个实测暴露的回归：`GreedyStr` 写成默认值导致指令只传第一个词；自然语言触发正则过宽（见 §5.5）。
  - ✅ **2026-09-18 自然语言拦截修复 + `/dsh 会话`**：真凶是正则 `\b` 对中文失效（详见 §5.5）；新增 `/dsh 会话`（列出本工作区会话并标出"当前"），且 `/dsh` 会自动给会话起标题；按主人要求**不做** `/dsh 新`（`-n` 已够）。
  - ✅ **2026-09-18 急停（`@南汐 stop` / `/dsh stop`）**：**复用 AstrBot 内置 `stop`**（不抢命令名）—— 注册 `active_event_registry.register_agent_stop_callback` 接住内置停止回调，再加 `dsh_cli.js --cancel`。实测：本应跑 20s+ 的长任务被 cancel 后 **0.0 秒收尾**，`reason=aborted`（机制详见 §5.5）。
  - ✅ **2026-09-19 调用形态严格化**：`/dsh` 与 `/mas` **共用同一道闸门** `_invoked_by_at_bot()` —— 只认 `@南汐 /dsh ...`（@ 必须排最前）；不 @ 直接发 `/dsh`、`@别人 /dsh`、`/dsh @南汐` 一律静默丢弃。**权限没变：`/dsh` 仍然只有主人能用**（闸门通过后才是那句"只有主人能用喵"）
  - ⏳ 仍待办：自然语言拦截与急停的**真群实测**（代码层均已验证）。
  - 🔴 **2026-10-03：`/dsh` 全线失效（HTTP 401）** —— DSH 升级到 `0.2.0-rc.2` 后给 Web 加了认证 Cookie，
    且我们依赖的客户端包 `dsh-host-apiproxy` 在 0.2.0 中**已被移除**。
    ⇒ **上面这些 09-16 ~ 09-19 的成果当前一律无法工作**（代码没坏，是底座变了）。
    修复路径见文首「最新状态」与 `环境勘察报告-20261003.md` §六：
    ① 更新 `qq-bridge` 到上游 `v0.2.0-r3`；② 让 `dsh_cli.js` 走新的认证（离线铸造 Cookie）与新协议（`/api/remote.mux`）。
  - ✅ **2026-10-03 晚：这条腿已被【星驿】替代并当天打通** —— 星驿是 DSH 进程内的插件，
    不碰 Web API ⇒ **不受上面那个 401 影响**。群里 `@南汐 dsh <指令>` 实测 **4 秒**回复、
    流式分片正常。**新工作请一律基于星驿**；`dsh_cli.js` / `astrbot_plugin_dsh`（已归档到
    `_disabled_plugins\astrbot_plugin_dsh.disabled`）不再提供服务，只留作历史参考。
    星驿的完整口径（触发方式、白名单语法、审批、踩坑）见文首「星驿链路」那一段。
- ✅ **`/mas` 答疑（2026-09-18 上线，09-19 实战验证）**：群里发截图/引用/转发消息后 `@南汐 /mas <问题>` →
  在 **mas 项目工作区**（`<WORKSPACE_MAS>`）用**分支会话**分析（从 `session-4fc15bc6…` fork，带历史前缀 → 命中 prompt cache，
  实测"禁止读文件"仍能答出 mas 项目结构）；发现问题时 agent 在末尾用 `ISSUE:` 块逐条列出 → 插件**沉淀进待修清单**（`mas待修问题.md`）并归档到 `mas答疑记录.md`。
  - 素材来源：`Image.convert_to_file_path()`（自动下载）、`Reply.message_str`/`chain`（引用内容 AstrBot 已解析好）、`Nodes`/`Node`（转发多条）
  - **`@南汐 /mas - <内容>` = 直通模式**：原样发给 mas 会话，**不套** 【输出要求】等模板（追问/闲聊/让它干别的时用）
  - **调用形态是严格的（2026-09-19 加闸门）**：只认 **`@南汐 /mas ...`** —— @ 必须排在最前；不 @ 直接发 `/mas`、`@别人 /mas`、`/mas @南汐`（顺序错）一律**静默丢弃**（不执行，也不转给聊天）。私聊没有 @ 的概念，直接 `/mas` 即可。原理见 §5.5
  - **每日限额（2026-09-19 加）**：`/mas` 对**所有群友**开放，但**非主人每人每天 8 次**（`MAS_DAILY_LIMIT`；**主人不受限**）。台账存 `nx_dsh\mas用量.json`（gitignore），结构 `{"date": "YYYY-MM-DD", "counts": {"<QQ>": n}}`，**跨天自动清零**（日期不符即视为新的一天）。只有**真正发起 DSH 调用**才扣次数 —— 只发 `/mas` 看用法、冷却期被挡回的都不占额度；回复里会带"（今天还剩 N 次）"。验证脚本 `_scripts_archive\probe_mas_quota.py`（12 用例）
  - **只读 + 待修清单 + 代为提 issue（2026-09-19，主人要求）**：主人出于安全把 mas 会话设成了**只读**，
    agent 不能再自己提 issue，于是分工改成「agent 只读分析 / 插件落库 / 主人点头才写上游」：
    - agent 在回复末尾用 `ISSUE:` 块**逐条**列出问题（摘要/位置/严重度/判定/证据/建议）；
      **收录范围是全收**（确认的 bug + 疑似 + 前后不一致 + 坑 + 明显体验问题），不再要求"必须改代码才算"；
    - 插件解析后沉淀进 **`mas待修问题.md`**（编号 + 状态 + 位置 + 严重度 + 出现次数）；按「位置+摘要」
      规范化后**去重**，同一问题再被问到只累加次数、刷新时间。`ISSUE` 块**不进群消息**，群里只看分析正文；
    - **只对新收录的问题**主动通知主人（重复出现的不打扰）；`/mas 问题` 随时拉全清单 ——
      这就是主人要的"等我要集中修的时候告诉我"。状态列**可以直接手改**（待修/已修/忽略/已提issue）；
    - `/mas 草稿 N` → 让 agent 按 mas 官方模板拟 issue 草稿（存 `mas_issue草稿\#N.md`）；
      `/mas 提issue N` → **仅主人**（群里不只有主人，代码里有 `sender != OWNER_QQ` 校验），
      由插件调 gh 提交，成功后把清单标成「已提issue」并记下 URL；
    - **两种写法都支持**：带空格的 `/mas 问题` 与连写的 `/mas问题` 等价（连写是靠注册成**独立命令**
      实现的 —— `CommandFilter` 要求命令名后必须跟空格，连写本来根本进不来，原理见 §5.5）。
      ⚠️ 但**编号前必须留空格**：`/mas草稿4` 不认，要写 `/mas草稿 4`；
    - 这几个子命令**不调 DSH、不占每日额度**（所以分发排在配额检查之前）。
  - **issue 必须合规（2026-09-19 落实）**：模板在 `<WORKSPACE_MAS>\AUTO-MAS\.github\ISSUE_TEMPLATE\`（共 7 个；
    `05-cn-ai-report.yaml` 是**专给 AI 提交**的分区，写明「不承诺处理时间」，必填「提交所用的 AI 工具或模型 /
    问题描述 / 证据」，且"只有推测没有证据的报告会被直接关闭"）。拟稿时让 agent **自己读模板目录挑一个**，
    严格按字段组织成 `###` 小标题；文风按 `<WORKSPACE_MAS>\AI必读.md` §3.4 —— 维护者原话
    「不想看 deepseek 的 D 言 D 语」：结论前置、理由最多一条、别堆编号、别用破折号+括号补充、
    删掉礼貌收尾、术语直接上文件名。
  - **提交通道（已验证）**：`gh` 2.100 在 `C:\Program Files\GitHub CLI\gh.exe`，已登录 `beichen24a1`（含 `repo` scope）；
    插件用 `subprocess.run` 调它，实测 subprocess 能正常取到 token；标签不存在时会**自动去掉标签重试一次**
    （避免整个提交因一个 label 失败）。仓库固定 `AUTO-MAS-Project/AUTO-MAS`。
  - 分支会话 id 持久化在 `nx_dsh\mas会话.json`（gitignore）；删掉它 = 下次重新 fork 一个
  - 每人 30 秒冷却；详见 `计划-mas答疑改分支会话.md`
- ❌ **阶段 2**（计划调度 / 16 点自动跑 MAA）：**已取消**（2026-09-18，主人确认不需要）。
  理由：游戏日常由 **AUTO-MAS 自带定时任务**执行、跑完由 **mas Webhook** 通知到群（见 `游戏通知\说明文档.md`），
  机器人侧再调度一遍是重复劳动。**南汐只做"接收结果 + 转述给主人"**，这层已跑通。
- ⏳ **阶段 3/4**（GUI 自动化 / 自我扩展）：未开发（阶段 3 **不含 MAA 场景**）。

---

## 8. 工作约定（务必遵守）

1. **git 全程存档**：动手改代码/配置前先 `git status` 看工作区；每次有意义改动提交一次 `git add -A && git commit`。**git 上传需要代理**：`git -c http.sslBackend=openssl -c http.proxy=http://127.0.0.1:7897 <cmd>`。
2. **密钥不入库**：含 key/token/密码的配置（cmd_config.json、config.json、onebot_*.json、*.db）都被 .gitignore 排除，别用 `git add -f` 强加。
3. **不擅自杀 python.exe**：用户机器上可能跑着其它东西，禁用"杀所有 python"。停 AstrBot 只按端口（6185/3002）——参见 `启动\stop_astrbot.bat`。
4. **AstrBot 改动要重启才生效**：改插件/配置后需 `启动\stop_astrbot.bat` + `启动\一键启动.bat` 重启 AstrBot。
5. **命令权限口径**：只有 `<OWNER_QQ>` 是主人。当前 —— **`/dsh` 仅主人**（非主人 @ 了也只会收到"只有主人能用喵"）；**`/mas` 所有群友可用**，非主人每人每天 8 次、主人不限；其余命令/白名单默认对主人放行、对他人拒绝。
6. **中文沟通**：你面向的是中文用户，请用中文说明；必要时先用 `ask_user_question` 确认关键决策（如改动大、涉及密钥、要发群的真实行为）。

---

*维护：DSH ｜ 生成 2026-09-01（含本仓最新状态）｜ 如需更新直接改写本文档。*
