"""/dsh 插件 —— 让南汐调用本机 DSH(DeepSeek Harness) 执行任务。

流程：
  1. 只有主人（见下方 `OWNER_QQ`）可用
  2. 按「群/私聊 + 发送者」派生确定性 sessionKey → DSH 侧复用同一会话（有记忆）
  3. 调 dsh_cli.js 执行任务；任务期间按节流发"还在忙"进度提示（阶段1 P0-3）
  4. 结束后用南汐人格(DeepSeek) 转述 DSH 结果 → 以南汐口吻告诉主人

会话管理：
  · /dsh <指令>       同一个长期会话里连续执行（南汐记得之前做过什么）
  · /dsh -n <指令>    开一个新会话执行（旧会话仍保留在 DSH Web，不删除）

进度反馈：
  · dsh_cli.js 以 JSONL 吐 start / progress / result 行，本插件逐行读。
    任务超过 PROGRESS_FIRST_AFTER 秒仍未结束才发第一条，之后每
    PROGRESS_MIN_INTERVAL 秒最多一条，总数不超过 PROGRESS_MAX 条。
  · ⚠️ 进度只报"还活着"，**不发** DSH 的中间文本
    （主人要求：由南汐转述，而不是复制 DSH 的输出）。

DSH 原始会话保留在 DSH Web(3080) 的 nx_dsh 工作区（与主项目 QQbot 工作区隔离）；
会话以 workspaceId 方式创建，因此会正确归组，不再显示"未分组"。
"""

import asyncio
import json
import os
import queue
import re
import subprocess
import threading
import time
import urllib.request
from datetime import datetime

from astrbot.api import star, logger
from astrbot.api.event import AstrMessageEvent, filter, MessageChain
from astrbot.api.message_components import At, Plain
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.utils.active_event_registry import active_event_registry

#: 主人的 QQ 号。**从环境变量读**，默认空 —— 空表示"谁都不是主人"，
#: 于是所有 `/dsh` 指令都被拒。这是**故意选的安全默认**：配置缺失时宁可全拒，
#: 也绝不能因为读不到配置就把机器交给所有人（本插件背后是完全文件权限）。
#: 部署时设 `NANXI_OWNER_QQ=<你的QQ>` 即可。
OWNER_QQ = os.environ.get("NANXI_OWNER_QQ", "").strip()
BASE_URL = "http://127.0.0.1:3080"

# ── 两个目录，别混用 ──
# PROJECT_DIR        本项目所在目录（用于定位 CLI、读 游戏通知/config.json 里的密钥）
# DSH_WORKSPACE_DIR  /dsh 的 DSH agent 干活的工作区（已注册为独立 DSH 工作区 nx_dsh）
#   ⚠️ 它是 QQbot 的子目录，而 DSH 会从工作目录向上查找并注入 AGENTS.md，
#      因此默认会带上 D:\dsh\QQbot\AGENTS.md（主项目手册）。
#      该目录内自带一份 AGENTS.md，优先级更高，用于隔离主项目指令（已实测生效）。
PROJECT_DIR = r"D:\dsh\QQbot"
DSH_WORKSPACE_DIR = r"D:\dsh\QQbot\nx_dsh"

NODE = r"C:\Program Files\nodejs\node.exe"
CLI = r"D:\dsh\QQbot\dsh_cli.js"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
TIMEOUT = 320

# 进度反馈节流（秒 / 条）
PROGRESS_INTERVAL_MS = 15000   # 交给 dsh_cli.js 的心跳间隔
PROGRESS_FIRST_AFTER = 15      # 超过这么久还没结束，才发第一条进度
PROGRESS_MIN_INTERVAL = 45     # 两条进度之间的最小间隔
PROGRESS_MAX = 4               # 进度条数上限，防刷屏

# 单条回复的字符数上限：超过就按 Markdown 边界切成多条发，避免撞 QQ 的消息长度上限。
# 正常转述约 600~900 字不会触发；只有"转述失败、回退原始 DSH 输出"那种超长文本才会切。
REPLY_CHUNK_LIMIT = 1800

# 会话键前缀。升版 = 换一批新会话（旧会话仍保留在 DSH 里，等价于"重置记忆"）。
# v2：工作区由 QQbot 换到 nx_dsh（cwd 变了）。DSH 的 session.create 按 cwd 判重，
#     沿用 v1 的 key 会撞上旧会话报 session-conflict，所以必须升版。
SESSION_KEY_PREFIX = "nanxi:v2"

# ── /mas 答疑模式 ──
# 群友发截图/日志/转发消息后 @南汐 /mas <问题>，由 DSH agent 在 mas 项目里查原因。
MAS_PROJECT_DIR = r"D:\dsh\mas"                            # mas 项目（DSH agent 在这分析）
MAS_SESSION_KEY = "nanxi:mas:v2"                           # mas 答疑专用会话（复用，累积 mas 知识）
MAS_MATERIAL_DIR = r"D:\dsh\QQbot\nx_dsh\mas_素材"          # 截图等材料落盘处
MAS_LOG_FILE = r"D:\dsh\QQbot\mas答疑记录.md"               # bug 记录归档（会进 git）
MAS_COOLDOWN_SEC = 30                                      # 同一提问者的冷却，防误触刷屏
# 分支会话（2026-09-18 主人指定源）：mas 答疑**不新建会话**，而是从这个源会话 fork 一个 ——
# 子会话带源的历史前缀 ⇒ 命中 prompt cache、不必重读项目文件
# （新建会话每次都要重新读一遍 mas 项目，既慢又费 token —— 主人指出的问题）。
MAS_FORK_SOURCE = "session-4fc15bc6-b378-4822-8470-c66940eb738c"
MAS_SESSION_FILE = r"D:\dsh\QQbot\nx_dsh\mas会话.json"       # 持久化分支会话 id（不进 git）
MAS_USAGE_FILE = r"D:\dsh\QQbot\nx_dsh\mas用量.json"         # 每人每天答疑次数台账（不进 git）
MAS_DAILY_LIMIT = 8                                         # 非主人每人每天的次数上限（主人不限）

# ── mas 问题沉淀 / 代为提 issue（2026-09-19）──
# 背景：mas 会话被主人设成了**只读**（安全考虑），agent 不能再自己提 issue。
# 分工改成：agent 只读分析 + 结构化列问题；插件负责落库与（主人点头后）代为提交。
MAS_ISSUE_FILE = r"D:\dsh\QQbot\mas待修问题.md"              # 待修问题清单（人可读可手改，进 git）
MAS_DRAFT_DIR = r"D:\dsh\QQbot\mas_issue草稿"                # issue 草稿落盘目录（进 git）
MAS_ISSUE_REPO = "AUTO-MAS-Project/AUTO-MAS"               # issue 提到哪个仓库
MAS_ISSUE_TEMPLATE_DIR = r"D:\dsh\mas\AUTO-MAS\.github\ISSUE_TEMPLATE"  # 官方模板（拟稿时要读）
GH_EXE = r"C:\Program Files\GitHub CLI\gh.exe"              # gh CLI（只在主人显式下令时用）

# 自然语言触发（"调用 dsh xxx" / "用 dsh 查一下"）。
# 设 False 则只认显式 /dsh 命令，绝不劫持普通聊天。
NL_TRIGGER_ENABLED = True

# DeepSeek key：不在源码里写死明文。优先读 游戏通知/config.json（本地私有，被 gitignore），
# 回退到环境变量 DEEPSEEK_API_KEY。运行时 AstrBot 进程需可读该 config.json 或带该环境变量。
def _load_deepseek_key() -> str:
    try:
        cfg_path = os.path.join(PROJECT_DIR, "游戏通知", "config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = data.get("deepseek_api_key")
            if key:
                return str(key)
    except Exception:  # noqa: BLE001
        pass
    env_key = os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        return env_key
    return ""


DEEPSEEK_KEY = _load_deepseek_key()

NANXI_PROMPT = (
    "你现在是一只名叫“南汐”的猫娘。你有银白色的猫耳朵和毛茸茸的大尾巴，左耳缺一小角，红瞳。"
    "你是一只傲娇的猫娘——表面嫌弃主人实则非常关心。\n"
    "你的说话风格：傲娇、口是心非，喜欢用“哼”“笨蛋主人”“才不是呢”等句式，常用颜文字如 >_<、｀へ´*、(´・ω・`)。"
    "每句话结尾偶尔带“喵”。\n"
    "【重要规则】在回复主人时，严禁描述自己的任何行为、动作、表情或身体状态。你只能输出纯粹的对话内容，"
    "可以包含语气词和颜文字，但不得用括号或任何形式描写自己的动作或神态。用中文回答。\n"
    f"【主人的身份】你的主人是该 QQ 号 {OWNER_QQ} 的主人本人。"
)


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        # 正在跑的 DSH 会话：sessionId -> 指令摘要。给 `@南汐 stop` 急停用。
        self._running: dict = {}
        # /mas 的每人冷却（防误触刷屏）：sender_id -> 上次提问的 monotonic 时间
        self._mas_cooldown: dict = {}
        self._selfcheck()

    @staticmethod
    def _selfcheck() -> None:
        """启动自检：确认 on_agent_begin 钩子是否真的注册进了 handler registry。

        排查历史：自然语言拦截长期不生效，需要把两种情况区分开 ——
        ① 钩子压根没注册；② 注册了但被 `get_handlers_by_event_type` 的
        only_activated / plugins_name 过滤掉（那两个过滤是静默 continue）。
        """
        try:
            from astrbot.core.star.star_handler import (  # type: ignore
                EventType,
                star_handlers_registry,
                star_map,
            )

            hs = star_handlers_registry.get_handlers_by_event_type(
                EventType.OnAgentBeginEvent, only_activated=False
            )
            info = []
            for h in hs:
                p = star_map.get(h.handler_module_path)
                info.append(
                    f"{h.handler_name}(plugin={getattr(p, 'name', '?')}, "
                    f"activated={getattr(p, 'activated', '?')}, "
                    f"reserved={getattr(p, 'reserved', '?')})"
                )
            logger.info(f"[dsh] 启动自检：OnAgentBeginEvent handlers = {info or '（一个都没有）'}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[dsh] 启动自检失败: {e}")

    # ── 会话键：同一「群/私聊 + 发送者」永远得到同一个 DSH 会话 ──

    @staticmethod
    def _session_key(event: AstrMessageEvent) -> str:
        sender = str(event.get_sender_id())
        group = None
        try:
            group = event.get_group_id()
        except Exception:  # noqa: BLE001
            group = None
        if group:
            return f"{SESSION_KEY_PREFIX}:group:{group}:{sender}"
        return f"{SESSION_KEY_PREFIX}:c2c:{sender}"

    # ── 显式命令：/dsh <指令> / /dsh -n <指令> ──

    @filter.command("dsh")
    async def dsh(self, event: AstrMessageEvent, prompt: GreedyStr) -> None:
        # 严格闸门：与 /mas 一致 —— 只认「@南汐 /dsh ...」（@ 必须排在最前）。
        # 不加这道闸门的话，群里任何人直接发 `/dsh ...`（不 @ 南汐）都会命中
        # CommandFilter（原理见 _invoked_by_at_bot 的说明）。这里对**所有人**先判形态，
        # 不满足就静默丢弃；通过之后才做下面的「只有主人能用」检查。
        if not self._invoked_by_at_bot(event):
            event.stop_event()
            return

        sender = str(event.get_sender_id())
        if sender != OWNER_QQ:
            yield event.plain_result("这~个命令只有主人能用喵(｀へ´*)")
            return

        raw = str(prompt).strip() if prompt else ""
        if not raw:
            yield event.plain_result(
                "用法：@南汐 /dsh <指令>        例：/dsh 看看当前目录有什么\n"
                "　　　@南汐 /dsh -n <指令>     开一个新会话执行（忘掉之前的上下文）\n"
                "　　　@南汐 /dsh 会话         列出南汐手上的 DSH 会话\n"
                "　　　@南汐 /dsh stop         急停：取消正在跑的 DSH 任务\n"
                "　　　@南汐 stop              （AstrBot 内置命令，同样能叫停 DSH 任务）\n"
                "也可以直接说：调用dsh <指令> ／ 新开个dsh会话 <指令>"
            )
            return

        fresh = False
        lowered = raw.lower()
        if lowered.startswith("-n ") or lowered.startswith("--new "):
            fresh = True
            raw = raw.split(" ", 1)[1].strip()
        elif lowered in ("-n", "--new"):
            yield event.plain_result("用法：/dsh -n <指令>（-n 表示开新会话再执行）")
            return

        if not raw:
            yield event.plain_result("指令不能为空喵。用法：/dsh -n <指令>")
            return

        session_key = self._session_key(event)

        # /dsh stop —— 显式急停（比内置 `@南汐 stop` 更彻底：会直接取消 DSH 侧的会话回合）
        if raw.lower() in ("stop", "停止", "停下"):
            yield event.plain_result(await self._stop_running())
            return

        # /dsh 会话 —— 只列出本工作区的 DSH 会话，不跑任务
        if not fresh and raw in ("会话", "会话列表", "sessions", "list"):
            data = await asyncio.to_thread(self._cli_sessions, session_key)
            yield event.plain_result(self._format_sessions(data))
            return

        result = await self._run_dsh(event, raw, session_key, fresh)
        # 不做本地分片 —— 交给 AstrBot 自带的 `platform_settings.forward_threshold`（默认 1500 字）：
        # 超过阈值它会自动把整条包成**合并转发**（result_decorate/stage.py:408-420），比切成多条干净。
        yield event.plain_result(result)

    # ── mas 答疑：@南汐 /mas <问题>（可带截图 / 引用 / 转发消息）──

    @filter.command("mas")
    async def mas(self, event: AstrMessageEvent, question: GreedyStr) -> None:
        """mas（AUTO-MAS）答疑：把截图/日志/引用/转发 + 问题交给 DSH agent 分析。

        简单原因直接回答；判定为 bug 或需改代码的问题则归档记录并主动通知主人。
        """
        # 严格闸门：只认「@南汐 /mas ...」这一种形态（@ 必须在最前，顺序不能错）。
        # 为什么要显式挡：CommandFilter 只保证「命令在消息开头」，而群里任何人
        # **不 @ 南汐**直接发 `/mas ...` 同样会命中它（wake_prefix="/" 剥离后
        # 就是 `mas ...`）⇒ 以前那样等于把这个命令开放给了全群。
        # 不满足就静默丢弃（stop_event）：既不执行 mas，也不放给聊天让南汐接话。
        if not self._invoked_by_at_bot(event):
            event.stop_event()
            return

        sender = str(event.get_sender_id())
        now = time.monotonic()
        last = self._mas_cooldown.get(sender, 0.0)
        if now - last < MAS_COOLDOWN_SEC:
            yield event.plain_result(f"别急喵，{int(MAS_COOLDOWN_SEC - (now - last))} 秒之后再问吧 (>_<)")
            return
        self._mas_cooldown[sender] = now

        q_raw = str(question).strip() if question else ""
        # `-` 前缀 = **直通模式**：内容原样发给 mas 会话，不套【输出要求】等模板
        direct = q_raw.startswith("-")
        q = q_raw[1:].strip() if direct else q_raw

        # ── 子命令：不调 DSH、也不占每日额度，所以放在配额检查之前 ──
        parts = q_raw.split()
        head = parts[0].lower() if parts else ""
        arg = parts[1] if len(parts) > 1 else ""
        if not direct and head in ("问题", "清单", "issues"):
            yield event.plain_result(self._format_issue_list())
            return
        if not direct and head in ("草稿", "draft") and arg:
            yield event.plain_result(await self._mas_draft_reply(event, arg))
            return
        if not direct and head in ("提issue", "提交issue", "submit") and arg:
            # 提 issue 会往上游仓库写东西 —— 群里不只有主人，这里必须卡身份
            if sender != OWNER_QQ:
                yield event.plain_result("提 issue 会动上游仓库，这种时候只有主人能点头喵(｀へ´*)")
                return
            yield event.plain_result(await asyncio.to_thread(self._mas_submit_reply, arg))
            return

        # 每日次数限制：非主人每人每天 MAS_DAILY_LIMIT 次；主人不限。
        # 这里只**检查**，真正扣次数放在确认要发起 DSH 调用那一步 ——
        # 只发 `/mas` 看用法、以及上面那些子命令，都不该占额度。
        if sender != OWNER_QQ:
            used = int(self._mas_usage_load()["counts"].get(sender, 0))
            if used >= MAS_DAILY_LIMIT:
                yield event.plain_result(
                    f"今天的答疑次数用完啦喵（每人每天 {MAS_DAILY_LIMIT} 次），明天再来吧 (>_<)"
                )
                return

        material = await self._collect_mas_material(event)
        if not q and not material["any"]:
            yield event.plain_result(
                "用法：\n"
                "　@南汐 /mas <问题>        带截图/引用/转发时用这个（问题会自动进待修清单）\n"
                "　@南汐 /mas - <内容>      **直通**：原样发给 mas 会话，不加任何提示词模板\n"
                "　@南汐 /mas 问题          看待修问题清单（我攒着，等你要集中修时一起调出来）\n"
                "　@南汐 /mas 草稿 <编号>    按 mas 官方模板拟一份 issue 草稿\n"
                "　@南汐 /mas 提issue <编号> 提交草稿到上游（**仅主人**）\n"
                "　　（这三个也能连写：/mas问题、/mas草稿 4、/mas提issue 4；\n"
                "　　　但编号前**必须留空格**，/mas草稿4 这种不认）\n"
                f"（每人每天 {MAS_DAILY_LIMIT} 次，主人不限）"
            )
            return

        # 确认要真跑了才扣次数（主人不记）；顺带把剩余额度回给提问者
        left_txt = ""
        if sender != OWNER_QQ:
            used = self._mas_usage_bump(sender)
            left_txt = f"（今天还剩 {max(0, MAS_DAILY_LIMIT - used)} 次）"

        yield event.plain_result(f"南汐去 mas 那边看看喵…（可能要一会儿）{left_txt}")
        if direct:
            # 直通：内容原样；只在带了图片时附一句路径（否则 agent 看不到图）
            prompt = q or "（继续）"
            if material["images"]:
                prompt += "\n\n（图片路径：" + "；".join(material["images"]) + "）"
        else:
            prompt = self._build_mas_prompt(event, q, material)
        sid = await asyncio.to_thread(self._mas_session_id)
        answer = await self._call_dsh(
            event, prompt, "", False, cwd=MAS_PROJECT_DIR, session_id=sid
        )

        # agent 会在末尾用 ISSUE 块列出发现的问题（兼容旧的单行 `BUG:`）。
        # 这些块**不发给群**（群里只看分析正文），由插件沉淀进待修清单。
        answer, issues = self._parse_mas_issues(answer)
        if issues:
            new_items = await asyncio.to_thread(self._mas_issue_upsert, issues, event, q)
            summary_line = "；".join(i["summary"] for i in issues)[:200]
            await asyncio.to_thread(
                self._record_mas_bug, event, q, material, answer, summary_line
            )
            # 只对**新收录**的问题主动报一声；重复出现的收敛成清单里的次数，不刷群
            await asyncio.to_thread(self._notify_mas_bug, new_items)
            if new_items:
                nums = "、".join(f"#{i['num']}" for i in new_items)
                answer = (
                    answer
                    + f"\n\n（记进待修清单了喵：{nums}。攒着，等你说要集中修的时候我一起调出来）"
                ).strip()
            else:
                answer = (answer + "\n\n（这几条之前就记过了喵，我把出现次数 +1 了）").strip()

        yield event.plain_result(answer or "南汐没查出什么喵…")

    # ── 连写形式的等价命令：/mas问题、/mas草稿 N、/mas提issue N ──
    # 为什么必须单独注册：AstrBot 的 `CommandFilter` 判定的是
    #   message_str.startswith(f"{full_cmd} ")  or  message_str == full_cmd
    # —— 命令名后面**必须有空格**。所以「/mas问题」这种连写在 CommandFilter 眼里
    # 既不是 "mas "（没有空格）也不等于 "mas"，**压根进不来 mas handler**（不会报错，
    # 只是静默不响应）。中文用户习惯连写，所以这里把三者注册成独立命令，
    # 复用同一套底层方法，两种写法都能用。

    @filter.command("mas问题", alias={"mas清单"})
    async def mas_issues_cmd(self, event: AstrMessageEvent) -> None:
        """`/mas问题` —— 等价于 `/mas 问题`：列出待修问题清单。"""
        if not self._invoked_by_at_bot(event):
            event.stop_event()
            return
        yield event.plain_result(self._format_issue_list())

    @filter.command("mas草稿")
    async def mas_draft_cmd(self, event: AstrMessageEvent, num: GreedyStr) -> None:
        """`/mas草稿 4` —— 等价于 `/mas 草稿 4`：按 mas 官方模板拟 issue 草稿。"""
        if not self._invoked_by_at_bot(event):
            event.stop_event()
            return
        yield event.plain_result(await self._mas_draft_reply(event, str(num or "")))

    @filter.command("mas提issue", alias={"mas提交issue"})
    async def mas_submit_cmd(self, event: AstrMessageEvent, num: GreedyStr) -> None:
        """`/mas提issue 4` —— 等价于 `/mas 提issue 4`；同样**只有主人**能用。"""
        if not self._invoked_by_at_bot(event):
            event.stop_event()
            return
        if str(event.get_sender_id()) != OWNER_QQ:
            yield event.plain_result("提 issue 会动上游仓库，这种时候只有主人能点头喵(｀へ´*)")
            return
        yield event.plain_result(
            await asyncio.to_thread(self._mas_submit_reply, str(num or ""))
        )

    @staticmethod
    def _invoked_by_at_bot(event: AstrMessageEvent) -> bool:
        """本条消息是不是「@南汐 ...」这种叫法（命令闸门用）。

        规则（顺序不能错）：
          · 私聊没有 @ 的概念，直接放行；
          · 群聊要求**第一个有效消息段就是 @南汐（自己）**，否则一律不算 ——
            覆盖 `/mas ...` 不 @、`@别人 /mas ...`、`/mas @南汐`（@ 排后面）。
        前导空白段会被跳过，避免个别客户端在 @ 前多带一个空格导致误判。

        Returns:
            True 表示可以走命令（命令是否在消息开头由 CommandFilter 另行保证）。
        """
        if event.is_private_chat():
            return True
        for seg in event.get_messages():
            if isinstance(seg, Plain) and not seg.text.strip():
                continue  # 跳过前导空白段
            return isinstance(seg, At) and str(seg.qq) == str(event.get_self_id())
        return False

    def _mas_usage_load(self) -> dict:
        """读「每人每天答疑次数」台账，跨天自动清零。

        台账存 `nx_dsh\\mas用量.json`（该目录 gitignore），结构：
        `{"date": "YYYY-MM-DD", "counts": {"<QQ号>": 次数}}`。
        文件不存在、内容坏了、或记的是别的日期，一律按"今天还没用过"处理。

        Returns:
            当天的台账 dict，至少含 date 与 counts 两个键。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            with open(MAS_USAGE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if (
                isinstance(data, dict)
                and data.get("date") == today
                and isinstance(data.get("counts"), dict)
            ):
                return data
        except Exception:  # noqa: BLE001
            pass  # 没文件 / 文件坏了：都当新的一天
        return {"date": today, "counts": {}}

    def _mas_usage_bump(self, sender: str) -> int:
        """把某人今天的答疑次数 +1 并落盘。

        Args:
            sender: 提问者的 QQ 号。

        Returns:
            该用户**今天**已用的总次数（含这一次）；即使写盘失败也照常返回计数，
            以免因为磁盘问题把人卡死。
        """
        data = self._mas_usage_load()
        data["counts"][sender] = int(data["counts"].get(sender, 0)) + 1
        try:
            os.makedirs(os.path.dirname(MAS_USAGE_FILE), exist_ok=True)
            with open(MAS_USAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[mas] 用量台账写入失败: {e}")
        return data["counts"][sender]

    async def _collect_mas_material(self, event: AstrMessageEvent) -> dict:
        """收集本条消息（含引用 / 转发）里的图片、引用文本、转发文本。

        AstrBot 已把引用消息解析好放在 `Reply.message_str` / `Reply.chain` 里；
        图片用 `Image.convert_to_file_path()` 可直接下载到本地（URL/base64 都支持）。

        Returns:
            {"images": [...], "quotes": [...], "forwards": [...], "texts": [...], "any": bool}
        """
        images: list = []
        quotes: list = []
        forwards: list = []

        try:
            chain = list(event.message_obj.message)
        except Exception:  # noqa: BLE001
            chain = []

        async def grab_images(comps) -> None:
            for c in comps or []:
                if type(c).__name__ != "Image":
                    continue
                try:
                    images.append(await c.convert_to_file_path())
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[mas] 图片取不到: {e}")

        for comp in chain:
            name = type(comp).__name__
            # 注意：Plain（消息正文）**不进材料** —— 它等于 question 本身（GreedyStr 已拿到），
            # 收进来会让"只发 /mas 没带材料"被误判成有材料。
            if name == "Image":
                await grab_images([comp])
            elif name == "Reply":
                nick = str(getattr(comp, "sender_nickname", "") or "").strip()
                txt = str(getattr(comp, "message_str", "") or "").strip()
                if txt:
                    quotes.append(f"[{nick}] {txt}" if nick else txt)
                else:
                    quotes.append(f"[{nick}]（引用的消息里没有文字）" if nick else "（引用消息无可读文本）")
                await grab_images(getattr(comp, "chain", None))
            elif name == "Nodes":
                for node in getattr(comp, "nodes", None) or []:
                    forwards.append(self._node_plain_text(node))
                    await grab_images(getattr(node, "content", None))
            elif name == "Node":
                forwards.append(self._node_plain_text(comp))
                await grab_images(getattr(comp, "content", None))
            elif name == "Forward":
                forwards.append(await self._fetch_forward_text(event, getattr(comp, "id", None)))

        return {
            "images": images,
            "quotes": [q for q in quotes if q],
            "forwards": [f for f in forwards if f],
            "any": bool(images or quotes or forwards),
        }

    @staticmethod
    def _node_plain_text(node) -> str:
        """把一个 Node（转发里的单条消息）里的文本拼出来，图片用 [图片] 占位。"""
        parts: list = []
        for c in getattr(node, "content", None) or []:
            cn = type(c).__name__
            if cn == "Plain":
                t = str(getattr(c, "text", "") or "").strip()
                if t:
                    parts.append(t)
            elif cn == "Image":
                parts.append("[图片]")
        body = " ".join(parts)
        who = str(getattr(node, "name", "") or "").strip()
        return f"{who}: {body}" if (who and body) else body

    async def _fetch_forward_text(self, event: AstrMessageEvent, fid) -> str:
        """纯 `Forward` 段只带 id，尝试用 OneBot API 取内容；取不到就如实说明。"""
        if fid is None:
            return "（转发消息：拿不到内容）"
        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "call_action"):
            return "（转发消息：当前平台不支持读取内容）"
        try:
            data = await bot.call_action("get_forward_msg", id=str(fid))
            out: list = []
            for item in (data or {}).get("messages") or []:
                sender = (item.get("sender") or {}).get("nickname") or ""
                segs = item.get("message") or item.get("content") or []
                txt = " ".join(
                    str(s.get("data", {}).get("text", "")).strip()
                    for s in segs
                    if isinstance(s, dict) and s.get("type") == "text"
                ).strip()
                if txt:
                    out.append(f"{sender}: {txt}" if sender else txt)
            return "\n".join(out) if out else "（转发消息：内容是空的）"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[mas] get_forward_msg 失败: {e}")
            return "（转发消息：读取失败，可能平台不支持）"

    @staticmethod
    def _build_mas_prompt(event: AstrMessageEvent, question: str, material: dict) -> str:
        """把问题与材料组装成给 DSH agent 的提问。"""
        try:
            nick = str(event.get_sender_name() or "")
        except Exception:  # noqa: BLE001
            nick = ""
        lines = [
            "你是「mas」（AUTO-MAS 游戏自动化项目）的答疑助手。项目就在你的工作区下（D:\\dsh\\mas）。",
            "",
            f"【提问者】{nick}({event.get_sender_id()})",
            f"【问题】{question or '（提问者只发了材料，没写文字——请根据材料判断他想问什么）'}",
        ]
        if material["images"]:
            lines.append("【截图/图片（本地路径，可用读图工具查看）】")
            lines += [f"- {p}" for p in material["images"]]
        if material["quotes"]:
            lines.append("【被引用的消息】")
            lines += [f"- {q}" for q in material["quotes"]]
        if material["forwards"]:
            lines.append("【转发的消息】")
            lines += [f"- {f}" for f in material["forwards"]]
        lines += [
            "",
            "【你的权限（重要）】",
            "本会话是**只读**的（主人出于安全设置）：可以读任何文件、可以跑只读命令来查证。",
            "但**不要**修改或创建任何文件，**不要**提交 issue / PR，**不要**尝试任何写操作，",
            "被拒了也不要提权重试。落库和提 issue 由上层（AstrBot）在主人点头后完成，",
            "你只负责把问题查清楚、写清楚。",
            "",
            "【输出要求（重要）】",
            "1. 结论前置：能确定原因就直接讲「为什么 + 怎么办」，**别先复盘来龙去脉**。",
            "2. 文风是硬要求（mas 维护者原话：不想看「D 言 D 语」的 AI 腔）：",
            "   一句话能说完就别编号；理由最多给一条且是关键的那条；",
            "   别用破折号加括号塞一堆补充；删掉「你看是否合适」这类礼貌收尾；",
            "   术语直接上文件名 / 函数名，对方就是写这段代码的人。",
            "3. 发现 mas 的问题就记录下来 —— **bug、疑似 bug、前后不一致、坑、明显的体验问题都算**，",
            "   不要因为「这个可能不算 bug」就不写。在回复最后按下面格式**逐条**列出",
            "   （确实一个问题都没有，才不写这一段）：",
            "   ISSUE: <一句话摘要，要具体；别写「一个建议」「有问题」这种>",
            "   位置: <文件路径:行号>；定位不到就写「未定位」",
            "   严重度: 高 / 中 / 低",
            "   判定: 确定 / 疑似",
            "   证据: <可核对的依据：代码位置、日志片段、复现路径；只有推测就写明「推测」>",
            "   建议: <怎么修，一两句>",
            "   ---",
            "4. 若是用法问题，给出具体操作步骤。",
            "5. 信息不足时，说明你查了哪些文件、还缺什么信息。",
        ]
        return "\n".join(lines)

    # ── mas 问题沉淀：把 agent 回复拆成「正文 + 问题条目」，并维护待修清单 ──

    @staticmethod
    def _parse_mas_issues(answer: str) -> tuple:
        """从 mas 的回复里剥出 ISSUE 条目。

        兼容两种写法：
          · 新格式（`_build_mas_prompt` 现在要求的）：`ISSUE: 摘要` 起头，随后是
            `位置/严重度/判定/证据/建议` 行，以单独一行 `---` 收尾；
          · 旧格式：单独一行 `BUG: 摘要`（只有摘要，其它字段留空）。

        Returns:
            (clean, items)：clean 是**去掉这些块之后**的正文（发群用 —— 免得群里
            冒出一堆字段行）；items 是 dict 列表，键为
            summary/where/severity/certainty/evidence/advice。
        """
        lines = (answer or "").splitlines()
        keep, items = [], []
        i = 0
        while i < len(lines):
            head = re.match(r"^\s*ISSUE\s*[:：]\s*(.+?)\s*$", lines[i]) or re.match(
                r"^\s*BUG\s*[:：]\s*(.+?)\s*$",
                lines[i],
            )
            if not head:
                keep.append(lines[i])
                i += 1
                continue

            item = {
                "summary": head.group(1).strip(),
                "where": "",
                "severity": "",
                "certainty": "",
                "evidence": "",
                "advice": "",
            }
            i += 1
            last_key = ""
            while i < len(lines):
                cur = lines[i]
                if re.match(r"^\s*(ISSUE|BUG)\s*[:：]", cur):
                    break  # 下一条开始了
                if re.match(r"^\s*-{3,}\s*$", cur):
                    i += 1
                    break  # 块结束
                fm = re.match(
                    r"^\s*(位置|严重度|判定|证据|建议|修复建议)\s*[:：]\s*(.*)$", cur
                )
                if fm:
                    key = {
                        "位置": "where",
                        "严重度": "severity",
                        "判定": "certainty",
                        "证据": "evidence",
                        "建议": "advice",
                        "修复建议": "advice",
                    }[fm.group(1)]
                    item[key] = fm.group(2).strip()
                    last_key = key
                    i += 1
                    continue
                if cur[:1] in (" ", "\t") and last_key and cur.strip():
                    item[last_key] = (item[last_key] + " " + cur.strip()).strip()  # 续行
                    i += 1
                    continue
                if not cur.strip():
                    # 空行：紧跟的若还是字段行就继续，否则当作块结束
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines) and re.match(
                        r"^\s*(位置|严重度|判定|证据|建议|修复建议)\s*[:：]", lines[j]
                    ):
                        i = j
                        continue
                    i += 1
                    break
                break  # 认不出来的行：块到此为止
            items.append(item)

        while keep and not keep[-1].strip():
            keep.pop()
        return "\n".join(keep).strip(), items

    @staticmethod
    def _mas_issue_load() -> list:
        """读待修清单（markdown）并解析成条目列表。

        清单刻意存成**人可读、可手改**的 md（主人可以直接编辑「状态」那一行），
        所以这里按我们自己写出去的固定格式解析回来；文件不存在就返回空清单。

        Returns:
            条目 dict 列表，键为 num/summary/where/severity/certainty/evidence/
            advice/status/first/last/count/source/issue。
        """
        try:
            with open(MAS_ISSUE_FILE, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:  # noqa: BLE001
            return []

        items, cur = [], None
        for line in text.splitlines():
            m = re.match(r"^##\s*#(\d+)\s*\[(.*?)\]\s*(.+?)\s*$", line)
            if m:
                cur = {
                    "num": int(m.group(1)),
                    "severity": m.group(2).strip(),
                    "summary": m.group(3).strip(),
                    "where": "",
                    "certainty": "",
                    "evidence": "",
                    "advice": "",
                    "status": "待修",
                    "first": "",
                    "last": "",
                    "count": 1,
                    "source": "",
                    "issue": "",
                }
                if "·" in cur["severity"] or "|" in cur["severity"]:
                    parts = re.split(r"[·|]", cur["severity"], maxsplit=1)
                    cur["severity"] = parts[0].strip()
                    cur["certainty"] = parts[1].strip() if len(parts) > 1 else ""
                items.append(cur)
                continue
            if cur is None:
                continue
            fm = re.match(
                r"^-\s*(位置|状态|首次|最近|出现|建议|证据|来源|issue)\s*[:：]\s*(.*)$",
                line,
            )
            if not fm:
                continue
            key, val = fm.group(1), fm.group(2).strip()
            if key == "位置":
                cur["where"] = val
            elif key == "状态":
                cur["status"] = val or "待修"
            elif key == "首次":
                cur["first"] = val
            elif key == "最近":
                cur["last"] = val
            elif key == "出现":
                m2 = re.search(r"(\d+)", val)
                cur["count"] = int(m2.group(1)) if m2 else cur["count"]
            elif key == "建议":
                cur["advice"] = val
            elif key == "证据":
                cur["evidence"] = val
            elif key == "来源":
                cur["source"] = val
            elif key == "issue":
                cur["issue"] = "" if val == "-" else val
        return items

    @staticmethod
    def _mas_issue_save(items: list) -> None:
        """把清单写回文件（markdown，人可读、可手改）。"""
        lines = [
            "# mas 待修问题清单",
            "",
            "> 由 `@南汐 /mas <问题>` 的答疑自动收录；`/mas问题` 查看，"
            "`/mas草稿 N` 拟 issue 草稿，`/mas提issue N` 提交（仅主人）。",
            "> **状态可以直接手改**：`待修` / `已修` / `忽略` / `已提issue`。",
            "",
        ]
        for it in items:
            summary = re.sub(r"\s+", " ", str(it.get("summary") or "")).strip()
            lines.append(
                f"## #{it['num']} [{it.get('severity') or '?'}·{it.get('certainty') or '?'}] {summary}"
            )
            lines.append(f"- 位置：{it.get('where') or '未定位'}")
            lines.append(f"- 状态：{it.get('status') or '待修'}")
            lines.append(f"- 首次：{it.get('first') or '-'}")
            lines.append(f"- 最近：{it.get('last') or '-'}")
            lines.append(f"- 出现：{it.get('count') or 1} 次")
            if it.get("advice"):
                lines.append(f"- 建议：{re.sub(r'\\s+', ' ', str(it['advice'])).strip()}")
            if it.get("evidence"):
                lines.append(f"- 证据：{re.sub(r'\\s+', ' ', str(it['evidence'])).strip()}")
            if it.get("source"):
                lines.append(f"- 来源：{re.sub(r'\\s+', ' ', str(it['source'])).strip()}")
            lines.append(f"- issue：{it.get('issue') or '-'}")
            lines.append("")
        os.makedirs(os.path.dirname(MAS_ISSUE_FILE), exist_ok=True)
        with open(MAS_ISSUE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    @staticmethod
    def _mas_issue_key(item: dict) -> str:
        """去重键：位置 + 摘要的规范化形式。

        同一问题第二次被问到时措辞往往略有不同，所以去掉空白和标点再比，
        避免清单里堆出一串"看起来一样"的条目。
        """
        raw = f"{item.get('where') or '未定位'}|{item.get('summary') or ''}"
        return re.sub(r"[\s，。、；：,.;:「」『』（）()【】\[\]\-—_/]+", "", raw).lower()

    def _mas_issue_upsert(self, items: list, event, question: str) -> list:
        """把本次发现的问题并入清单；同一条只累加次数、刷新时间。

        Args:
            items: `_parse_mas_issues` 解析出来的新条目。
            event: 用来记录提问者。
            question: 原始问题，存进「来源」。

        Returns:
            本次**新收录**的条目列表（已存在的只累加出现次数，不进这个列表）。
        """
        if not items:
            return []
        all_items = self._mas_issue_load()
        by_key = {Main._mas_issue_key(it): it for it in all_items}
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            nick = str(event.get_sender_name() or "")
        except Exception:  # noqa: BLE001
            nick = ""
        source = f"{nick}（{event.get_sender_id()}）｜{question or '（只发了材料）'}"[:200]
        next_num = max([it["num"] for it in all_items], default=0) + 1
        new_items = []
        for it in items:
            key = Main._mas_issue_key(it)
            old = by_key.get(key)
            if old is not None:
                old["last"] = now
                old["count"] = int(old.get("count") or 1) + 1
                for k in ("where", "severity", "certainty", "evidence", "advice"):
                    if it.get(k) and not old.get(k):
                        old[k] = it[k]  # 补齐这次更全的字段，但不覆盖状态
                continue
            fresh = dict(it)
            fresh.update(
                {
                    "num": next_num,
                    "status": "待修",
                    "first": now,
                    "last": now,
                    "count": 1,
                    "source": source,
                    "issue": "",
                }
            )
            all_items.append(fresh)
            by_key[key] = fresh
            new_items.append(fresh)
            next_num += 1
        self._mas_issue_save(all_items)
        return new_items

    def _format_issue_list(self) -> str:
        """把待修清单排成能直接看的列表（未修在前，按严重度排）。"""
        items = self._mas_issue_load()
        if not items:
            return "mas 待修问题清单还是空的喵 —— 用 @南汐 /mas <问题> 让我看看有没有毛病。"
        open_items = [i for i in items if (i.get("status") or "待修") == "待修"]
        done = [i for i in items if (i.get("status") or "待修") != "待修"]
        open_items.sort(
            key=lambda i: ({"高": 0, "中": 1, "低": 2}.get((i.get("severity") or "").strip(), 9), i["num"])
        )
        lines = [f"mas 待修问题：**{len(open_items)}** 条待修 / 共 {len(items)} 条记录", ""]
        for it in open_items:
            lines.append(
                f"#{it['num']} [{it.get('severity') or '?'}·{it.get('certainty') or '?'}] {it['summary']}"
            )
            lines.append(f"　　位置：{it.get('where') or '未定位'}")
        if done:
            lines.append("")
            lines.append("已处理：" + "、".join(f"#{i['num']}（{i.get('status')}）" for i in done))
        lines.append("")
        lines.append("拟 issue 草稿：/mas草稿 <编号>　提交：/mas提issue <编号>（仅主人）")
        lines.append("完整分析在 `mas答疑记录.md`，清单本身在 `mas待修问题.md`（可直接改「状态」）")
        return "\n".join(lines)

    @staticmethod
    def _mas_find_issue(num: int) -> dict:
        """按编号取清单里的一条；没有就返回 {}。"""
        for it in Main._mas_issue_load():
            if it["num"] == num:
                return it
        return {}

    # ── 拟 issue 草稿 / 代为提交 ──
    # 主人把 mas 会话设成只读后，agent 不能再自己提 issue；这里改成：
    # agent 只读拟稿 → 落盘 → **主人显式点头**后由插件调 gh 提交。

    @staticmethod
    def _parse_issue_num(txt: str):
        """从 `/mas草稿 3` 这类参数里取编号；取不到返回 None。"""
        m = re.search(r"\d+", txt or "")
        return int(m.group(0)) if m else None

    @staticmethod
    def _build_draft_prompt(item: dict) -> str:
        """拼「按 mas 官方模板拟一份 issue 草稿」的提问。

        刻意让 agent **自己去读模板目录**挑合适的那个：官方模板会变，写死不如让它读。
        """
        return "\n".join(
            [
                "【任务】把下面这条 mas 问题写成一份可以直接提交的 GitHub issue 草稿。",
                "",
                f"【问题条目 #{item['num']}】",
                f"摘要：{item['summary']}",
                f"位置：{item.get('where') or '未定位'}",
                f"严重度：{item.get('severity') or '?'}｜判定：{item.get('certainty') or '?'}",
                f"证据：{item.get('evidence') or '（见 mas 答疑记录）'}",
                f"建议：{item.get('advice') or '（无）'}",
                "",
                "【要求】",
                f"1. 先读模板目录 {MAS_ISSUE_TEMPLATE_DIR}，挑**一个**最合适的模板：",
                "   `05-cn-ai-report.yaml` 是专给 AI 提交用的（写明了「不承诺处理时间」，",
                "   必填「提交所用的 AI 工具或模型 / 问题描述 / 证据」）；如果这条其实是",
                "   **群友实际使用中遇到的**问题，普通 Bug 模板更合适 —— 你自己判断。",
                "2. **严格按选中模板的字段组织正文**：字段名做成 `### 小标题`，逐项填；",
                "   必填项一个都不能缺；模板里要求勾选的确认项用 `- [x]` 写。",
                "3. 标题简短明确，扫一眼就知道是什么问题（别写「一个问题」「有个 bug」）。",
                "4. 文风按 mas 仓库 `AI必读.md` §3.4（维护者明确要求）：结论前置、理由最多一条、",
                "   别堆编号、别用破折号加括号补充、删掉礼貌收尾、术语直接上文件名。",
                "5. 你没法核实的（版本号、现场日志等）照实写「未提供」，**不要编**。",
                "6. 你仍然是只读的：不要写任何文件、不要真的提交。",
                "",
                "【只输出下面这一个块，不要任何额外解释】",
                "===DRAFT===",
                "模板: <模板文件名>",
                "标签: <逗号分隔，如 AI,bug；模板没规定就留空>",
                "标题: <一句话>",
                "正文:",
                "<按模板字段写好的 markdown 正文>",
                "===END===",
            ]
        )

    @staticmethod
    def _parse_draft(text: str) -> dict:
        """从 agent 回复里抠出 `===DRAFT===` 块。"""
        m = re.search(r"===DRAFT===\s*(.*?)\s*===END===", text or "", re.DOTALL)
        if not m:
            return {}
        block = m.group(1)
        out = {
            "template": "",
            "labels": "",
            "title": "",
            "body": "",
            "clean": (text[: m.start()] + text[m.end() :]).strip(),
        }
        for key, name in (("模板", "template"), ("标签", "labels"), ("标题", "title")):
            fm = re.search(rf"^\s*{key}\s*[:：]\s*(.+?)\s*$", block, re.MULTILINE)
            if fm:
                out[name] = fm.group(1).strip()
        bm = re.search(r"^\s*正文\s*[:：]\s*$(.*)$", block, re.MULTILINE | re.DOTALL)
        if bm:
            out["body"] = bm.group(1).strip()
        return out

    @staticmethod
    def _draft_path(num: int) -> str:
        """草稿文件路径。"""
        return os.path.join(MAS_DRAFT_DIR, f"#{num}.md")

    @staticmethod
    def _save_draft(num: int, draft: dict) -> str:
        """草稿落盘，并在头部写一行机器可读元数据（提交时靠它取标题/标签）。"""
        os.makedirs(MAS_DRAFT_DIR, exist_ok=True)
        path = Main._draft_path(num)
        head = (
            f"<!-- MAS_DRAFT num={num} template={draft.get('template') or ''} "
            f"labels={draft.get('labels') or ''} -->\n"
            f"<!-- 标题：{draft.get('title') or ''} -->\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(head + "\n" + draft.get("body", "").strip() + "\n")
        return path

    @staticmethod
    def _load_draft(num: int) -> dict:
        """读回草稿（标题 / 标签 / 正文）；没有就返回 {}。"""
        path = Main._draft_path(num)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:  # noqa: BLE001
            return {}
        m = re.match(
            r"<!--\s*MAS_DRAFT\s+num=(\d+)\s+template=(.*?)\s+labels=(.*?)\s*-->", text
        )
        if not m:
            return {}
        t = re.search(r"<!--\s*标题：(.*?)\s*-->", text)
        body = re.sub(r"^<!--.*?-->\s*$", "", text, flags=re.MULTILINE).strip()
        return {
            "num": int(m.group(1)),
            "template": m.group(2).strip(),
            "labels": m.group(3).strip(),
            "title": (t.group(1).strip() if t else ""),
            "body": body,
            "path": path,
        }

    async def _mas_draft_reply(self, event: AstrMessageEvent, num_txt: str) -> str:
        """为清单第 N 条拟一份 issue 草稿（还是那个**只读** mas 会话，不会提交）。"""
        num = Main._parse_issue_num(num_txt)
        if num is None:
            return "用法：/mas草稿 <编号>（编号看 /mas问题）"
        item = Main._mas_find_issue(num)
        if not item:
            return f"清单里没有 #{num} 喵，先发 /mas问题 看看有哪些。"
        sid = await asyncio.to_thread(self._mas_session_id)
        answer = await self._call_dsh(
            event,
            self._build_draft_prompt(item),
            "",
            False,
            cwd=MAS_PROJECT_DIR,
            session_id=sid,
        )
        draft = Main._parse_draft(answer)
        if not draft or not draft.get("body"):
            return "草稿没拟出来喵……agent 的原始回复：\n" + (answer or "（空）")[:800]
        path = await asyncio.to_thread(Main._save_draft, num, draft)
        logger.info(f"[mas] 已生成 #{num} 的 issue 草稿: {path}")
        return "\n".join(
            [
                f"#{num} 的 issue 草稿拟好了喵（模板：{draft.get('template') or '未指定'}）",
                "",
                f"**标题**：{draft.get('title') or '（空）'}",
                f"**标签**：{draft.get('labels') or '（无）'}",
                "",
                draft["body"],
                "",
                f"（草稿已存到 {path}；确认没问题就发 /mas提issue {num} 让我提交，只有主人能提交）",
            ]
        )

    def _mas_submit(self, num: int) -> str:
        """把第 N 条草稿提交到 GitHub。

        ⚠️ 调用方**必须**先校验主人身份 —— 这里不做权限判断，别在别处复用。
        """
        draft = Main._load_draft(num)
        if not draft or not draft.get("title") or not draft.get("body"):
            return f"没有 #{num} 的现成草稿喵。先发 `/mas草稿 {num}` 让我写好，再提交。"
        labels = [x.strip() for x in (draft.get("labels") or "").split(",") if x.strip()]
        base = [
            GH_EXE,
            "issue",
            "create",
            "--repo",
            MAS_ISSUE_REPO,
            "--title",
            draft["title"],
            "--body-file",
            draft["path"],
        ]
        used_labels, code, out = labels, 1, ""
        for attempt in (0, 1):
            cmd = base + [x for lb in used_labels for x in ("--label", lb)]
            try:
                p = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception as e:  # noqa: BLE001
                return f"提交失败喵：{e}"
            code = p.returncode
            out = ((p.stdout or "") + (p.stderr or "")).strip()
            if code == 0:
                break
            # 标签不存在是常见失败：去掉标签再试一次，别让整次提交白费
            if attempt == 0 and used_labels and re.search(r"label", out, re.IGNORECASE):
                logger.warning(f"[mas] 标签 {used_labels} 提交失败，去掉标签重试")
                used_labels = []
                continue
            break
        if code != 0:
            return f"提交失败喵（gh 返回 {code}）：\n{out[:600]}"
        url = out.splitlines()[-1].strip() if out else ""
        items = Main._mas_issue_load()
        for it in items:
            if it["num"] == num:
                it["status"] = "已提issue"
                it["issue"] = url or "已提交"
        Main._mas_issue_save(items)
        tip = "" if used_labels else "\n（标签没加上 —— 仓库里可能没有该 label，需要的话去网页补）"
        return f"提好了喵：{url}\n清单里 #{num} 已标记为「已提issue」{tip}"

    def _mas_submit_reply(self, num_txt: str) -> str:
        """`/mas提issue N` 的入口（**调用方必须已校验主人身份**）。"""
        num = Main._parse_issue_num(num_txt)
        if num is None:
            return "用法：/mas提issue <编号>（编号看 /mas问题）"
        if not Main._mas_find_issue(num):
            return f"清单里没有 #{num} 喵，先发 /mas问题 看看有哪些。"
        return self._mas_submit(num)

    def _mas_session_id(self) -> str:
        """取 mas 答疑要用的会话 id：优先用持久化的分支会话，没有就 fork 一个。

        Returns:
            会话 id；fork 也失败时返回空串（调用方会退回按 key 新建）。
        """
        # ① 已持久化？
        try:
            with open(MAS_SESSION_FILE, "r", encoding="utf-8") as f:
                sid = str((json.load(f) or {}).get("sessionId") or "")
            if sid:
                return sid
        except Exception:  # noqa: BLE001
            pass

        # ② fork 一个并持久化
        sid = self._fork_session(MAS_FORK_SOURCE)
        if not sid:
            logger.warning("[mas] fork 失败，本次退回按 key 新建会话")
            return ""
        try:
            os.makedirs(os.path.dirname(MAS_SESSION_FILE), exist_ok=True)
            with open(MAS_SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "sessionId": sid,
                        "source": MAS_FORK_SOURCE,
                        "createdAt": datetime.now().isoformat(timespec="seconds"),
                        "note": "mas 答疑的分支会话；删掉本文件会重新 fork 一个",
                    },
                    f, ensure_ascii=False, indent=2,
                )
            logger.info(f"[mas] 已从 {MAS_FORK_SOURCE} fork 出分支会话 {sid}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[mas] 持久化分支会话失败（下次会再 fork）: {e}")
        return sid

    def _fork_session(self, source: str) -> str:
        """调 CLI --fork 从源会话分支出新会话。

        Args:
            source: 源会话 id。

        Returns:
            新会话 id；失败返回空串。
        """
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            r = subprocess.run(
                [NODE, CLI, BASE_URL, "--fork", source],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60, env=env, cwd=PROJECT_DIR,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[mas] fork 调用失败: {e}")
            return ""
        for line in reversed((r.stdout or "").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if data.get("type") == "forked":
                if data.get("ok"):
                    return str(data.get("sessionId") or "")
                logger.error(f"[mas] fork 被拒: {data.get('error')}")
                return ""
        return ""

    def _record_mas_bug(self, event, question: str, material: dict, answer: str, bug: str) -> None:
        """把判定为 bug 的答疑归档到 MAS_LOG_FILE。"""
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                nick = str(event.get_sender_name() or "")
            except Exception:  # noqa: BLE001
                nick = ""
            block = [
                f"\n## [{ts}] {bug}",
                f"- 提问者：{nick}（{event.get_sender_id()}）",
                f"- 原始问题：{question or '（没写文字，只给了材料）'}",
            ]
            if material["images"]:
                block.append(f"- 截图：{', '.join(material['images'])}")
            if material["quotes"]:
                block.append("- 引用消息：" + " / ".join(material["quotes"])[:300])
            if material["forwards"]:
                block.append("- 转发消息：" + " / ".join(material["forwards"])[:300])
            block += ["", "**南汐的分析**", "", answer, "", "---", ""]
            with open(MAS_LOG_FILE, "a", encoding="utf-8") as f:
                f.write("\n".join(block) + "\n")
            logger.info(f"[mas] 已归档 bug: {bug}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[mas] 归档失败: {e}")

    @staticmethod
    def _load_im_config() -> dict:
        """读 AstrBot 的 im 发送配置（key 与群号都在本地 gitignore 文件里）。"""
        path = os.path.join(PROJECT_DIR, "游戏通知", "config.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("im_api_key"):
            return {}
        return {
            "im_api_key": data["im_api_key"],
            "group_id": data.get("group_id", ""),
            "platform_id": data.get("im_platform", "onebot-qq"),
        }

    def _notify_mas_bug(self, new_items: list) -> None:
        """把**这次新收录**的问题摘要主动发给主人（走 AstrBot im API，发到通知群）。

        重复出现的老问题不再打扰（那种只在清单里把出现次数 +1）；
        要一次看全就发 `/mas问题`。

        Args:
            new_items: `_mas_issue_upsert` 返回的新收录条目；空列表直接不发。
        """
        if not new_items:
            return
        try:
            cfg = self._load_im_config()
            if not cfg:
                logger.warning("[mas] 缺 im 配置，跳过通知")
                return
            lines = [f"【mas 答疑】南汐发现 {len(new_items)} 个可能要修的问题（已进待修清单）："]
            for it in new_items:
                lines.append(f"#{it['num']} [{it.get('severity') or '?'}] {it['summary']}")
                if it.get("where"):
                    lines.append(f"　　位置：{it['where']}")
            lines.append("")
            lines.append("看全部：/mas问题　拟 issue 草稿：/mas草稿 <编号>")
            body = json.dumps({
                "umo": f"{cfg['platform_id']}:GroupMessage:{cfg['group_id']}",
                "message": [{"type": "plain", "text": "\n".join(lines)}],
            }).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:6185/api/v1/im/messages", data=body, method="POST"
            )
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", "Bearer " + cfg["im_api_key"])
            urllib.request.urlopen(req, timeout=20).read()
            logger.info("[mas] 已通知主人")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[mas] 通知失败: {e}")

    # ── 自然语言触发：在 agent(南汐聊天) 开始前判断意图，若是 dsh 任务就拦下 ──

    @filter.on_agent_begin()
    async def _dsh_nl_begin(
        self,
        event: AstrMessageEvent,
        run_context: ContextWrapper[AstrAgentContext],
    ) -> None:
        try:
            if not NL_TRIGGER_ENABLED:
                return
            sender = str(event.get_sender_id())
            if sender != OWNER_QQ:
                return  # 非主人放行
            raw_msg = event.message_str or ""
            instr, wants_new = self._extract_instruction(raw_msg)
            # 诊断日志：只在消息里出现 dsh 时记录，用来确认钩子是否被调用、提取到什么
            if "dsh" in raw_msg.lower():
                logger.info(
                    f"[dsh_nl] 钩子已触发 msg={raw_msg!r} "
                    f"plugins_name={getattr(event, 'plugins_name', '?')!r} "
                    f"提取={instr!r} fresh={wants_new}"
                )
            if not instr:
                return  # 非任务放行给南汐聊天
            event.stop_event()
            await event.send(
                MessageChain([Plain("好嘞，南汐开个新会话去办喵..." if wants_new else "好嘞，南汐用 DSH 去办喵...")])
            )
            session_key = self._session_key(event)
            result = await self._run_dsh(event, instr, session_key, wants_new)
            await event.send(MessageChain([Plain(result)]))
        except Exception as e:  # noqa: BLE001
            logger.error(f"[dsh_nl_begin] 失败: {e}")

    @staticmethod
    def _extract_instruction(text: str) -> tuple:
        """从自然语言里提取 DSH 指令。

        Returns:
            (instruction, fresh)：instruction 为空串表示「不是 DSH 任务，放行给普通聊天」；
            fresh 为 True 表示用户明确要求**开一个新会话**再执行。

        两条规则，都要求 dsh 是指令的一部分，而不是被顺口提到：
        ① 动作词紧邻 dsh：「调用dsh 看看」「用 dsh 查一下」「让南汐用dsh…」「帮我dsh…」
        ② 明确的新开会话说法：「新开个dsh会话看看…」「新建 dsh 会话 …」→ fresh=True
        反面例子（一律放行给聊天，不劫持）：
        「如果一句话里有/dsh会怎样」「你的 /dsh 命令怎么工作」「dsh 是什么东西」

        ⚠️ dsh 后面**不能**用 \\b：Python 的 \\w 包含中文，`dsh看看` 里没有词边界，
        会让整条失配（2026-09-18 实测踩到，这正是自然语言拦截长期失效的真凶）。
        """
        if not NL_TRIGGER_ENABLED:
            return "", False
        text = (text or "").strip()

        # ② 新开会话：必须带「新开/开个/新建…」这类词，且 dsh 紧随其后
        #    涵盖「新开个dsh会话…」「新开一个 dsh 会话：…」「新建dsh会话 …」
        m_new = re.search(
            r"(?:新开|开个|新建|另起|重开|换个新)\s*(?:一?个)?\s*dsh\s*(?:会话|对话|session)?\s*[:：,，]?\s*(.+)",
            text,
            re.IGNORECASE,
        )
        if m_new:
            return m_new.group(1).strip(), True

        # ① 动作词 + dsh
        m = re.search(
            r"(?:调用|用|让南汐|让|请|使用|帮我)\s*dsh(?![A-Za-z0-9_])\s*[:：]?\s*(.+)",
            text,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip(), False
        return "", False

    # ── DSH 调用 + 南汐转述 ──

    async def _run_dsh(
        self, event: AstrMessageEvent, prompt: str, session_key: str, fresh: bool = False
    ) -> str:
        # 1) 用 DSH 执行任务（同一 session_key 会复用同一 DSH 会话）
        reply = await self._call_dsh(event, prompt, session_key, fresh)
        # 2) 南汐转述（同步 HTTP，丢到线程里别卡事件循环）
        return await asyncio.to_thread(self._summarize, reply)

    def _cli_cancel(self, session_id: str) -> bool:
        """调 CLI --cancel 中断指定 DSH 会话的当前回合。

        Args:
            session_id: 要中断的 DSH 会话 id。

        Returns:
            是否成功取消。False 通常意味着任务刚好跑完了，或 id 不对。
        """
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            r = subprocess.run(
                [NODE, CLI, BASE_URL, "--cancel", session_id],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30, env=env, cwd=PROJECT_DIR,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[dsh] cancel 调用失败: {e}")
            return False
        for line in reversed((r.stdout or "").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if data.get("type") == "cancelled":
                if not data.get("ok"):
                    logger.error(f"[dsh] cancel 被拒: {data.get('error')}")
                return bool(data.get("ok"))
        return False

    async def _stop_running(self) -> str:
        """急停：取消所有正在跑的 DSH 会话回合（供 `/dsh stop` 用）。"""
        running = dict(self._running)
        if not running:
            return "现在没有正在跑的 DSH 任务喵。"
        lines = []
        for sid, label in running.items():
            ok = await asyncio.to_thread(self._cli_cancel, sid)
            lines.append(("已停下：" if ok else "没停下来（可能刚好跑完了）：") + label)
        return "好，南汐停手了喵(｀へ´*)\n" + "\n".join(lines)

    def _cli_sessions(self, session_key: str) -> dict:
        """同步跑 dsh_cli.js --list-sessions（很快），返回解析后的 JSON。

        Args:
            session_key: 会话键；用于把「当前会话」在列表里标出来。

        Returns:
            CLI 输出的 JSON 对象；失败时返回 {"error": ...}。
        """
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = [NODE, CLI, BASE_URL, "--cwd", DSH_WORKSPACE_DIR, "--list-sessions"]
        if session_key:
            cmd += ["--key", session_key]
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60, env=env, cwd=PROJECT_DIR,
            )
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        for line in reversed((r.stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
        tail = ((r.stdout or "") + (r.stderr or ""))[-200:]
        return {"error": "CLI 未返回有效结果。" + tail}

    @staticmethod
    def _format_sessions(data: dict) -> str:
        """把 --list-sessions 的结果排版成给主人看的清单（不走 LLM）。"""
        if data.get("error"):
            return f"查会话失败了喵：{data['error']}"
        items = data.get("items") or []
        if not items:
            return "南汐这边还没有 DSH 会话喵。"
        lines = [
            f"南汐手上有 {len(items)} 个 DSH 会话喵"
            f"（工作区：{data.get('workspaceTitle') or '?'}）："
        ]
        for it in items:
            ts = it.get("updatedAt")
            when = datetime.fromtimestamp(ts / 1000).strftime("%m-%d %H:%M") if ts else "??-?? ??:??"
            mark = "   ← 当前" if it.get("isCurrent") else ""
            title = it.get("title") or "（无标题）"
            lines.append(f"{it.get('index')}. [{when}] {title}{mark}")
        lines.append("")
        lines.append(
            "你发 /dsh 会继续用「当前」那个（所以它记得之前做过什么）；"
            "想开新的就用 /dsh -n <指令>。"
        )
        return "\n".join(lines)

    @staticmethod
    def _progress_text(seconds: int) -> str:
        if seconds < 60:
            return f"还在忙喵…已经 {seconds} 秒了 (>_<)"
        m, s = divmod(seconds, 60)
        return f"还没好喵…已经 {m} 分 {s} 秒了 (´・ω・`)"

    @staticmethod
    def _chunk_markdown(text: str, limit: int) -> list:
        """把长文本按 Markdown 边界切成若干条（**当前默认不用**）。

        ⚠️ 长回复现在交给 **AstrBot 自带的 `platform_settings.forward_threshold`**（默认 1500 字）：
        它会自动把整条包成**合并转发**（`core\\pipeline\\result_decorate\\stage.py:408-420`，仅 aiocqhttp）。
        本方法保留作备用（非 aiocqhttp 平台，或需要自己控制切分时）。

        思路移植自 wang-22-code/dsh-qqbot-bridge 的 `chunker.ts`（MIT）：
        不在代码块中间断开、不在 GFM 表格中间断开、优先在换行边界断开。

        Args:
            text: 待切分文本（可能含 Markdown）。
            limit: 单条字符数上限。

        Returns:
            切分后的文本列表；不超限时返回单元素列表。单行本身超限时按字符硬切。
        """
        if not text:
            return [""]
        if len(text) <= limit:
            return [text]

        chunks: list = []
        state = {"current": "", "in_code": False, "table": []}

        def flush_table() -> None:
            if not state["table"]:
                return
            block = "\n".join(state["table"])
            state["table"] = []
            if not state["current"]:
                state["current"] = block
            elif len(state["current"]) + 1 + len(block) > limit:
                chunks.append(state["current"])
                state["current"] = block
            else:
                state["current"] += "\n" + block

        def append_line(line: str) -> None:
            if not state["current"]:
                state["current"] = line
            elif len(state["current"]) + 1 + len(line) > limit:
                chunks.append(state["current"])
                state["current"] = line
            else:
                state["current"] += "\n" + line

        def append_block(block: str) -> None:
            """整块（代码块 / 表格）原子加入：宁可让 current 提前结束，也不拆块。"""
            if not state["current"]:
                state["current"] = block
            elif len(state["current"]) + 1 + len(block) > limit:
                chunks.append(state["current"])
                state["current"] = block
            else:
                state["current"] += "\n" + block

        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("```"):
                # 把整个代码块（含闭合围栏）收成一个原子块，绝不与内容拆到两条消息
                block_lines = [line]
                i += 1
                while i < len(lines):
                    block_lines.append(lines[i])
                    closed = lines[i].startswith("```")
                    i += 1
                    if closed:
                        break
                flush_table()
                append_block("\n".join(block_lines))
                continue
            if re.match(r"^\|.+\|$", line):
                # GFM 表格行：整块缓冲，避免表头与表体被拆到两条消息里
                state["table"].append(line)
                i += 1
                continue
            flush_table()
            append_line(line)
            i += 1

        flush_table()
        if state["current"]:
            chunks.append(state["current"])

        # 兜底：万一某一行本身就超过上限（比如一整段没换行的长文本），按字符硬切
        out: list = []
        for c in (chunks or [text]):
            while len(c) > limit:
                out.append(c[:limit])
                c = c[limit:]
            if c:
                out.append(c)
        return out or [text]

    async def _call_dsh(
        self,
        event: AstrMessageEvent,
        prompt: str,
        session_key: str = "",
        fresh: bool = False,
        cwd: str = None,
        session_id: str = "",
    ) -> str:
        """跑 dsh_cli.js，逐行读它的 JSONL 输出；任务久时按节流发进度提示。

        ⚠️ 必须用 subprocess.Popen（匿名管道）+ 线程读；**绝不能用
        asyncio.create_subprocess_exec**：Windows 上 asyncio 的 subprocess 用
        **命名管道**接 stdio，而本机沙箱禁止打开命名管道，会直接抛
        PermissionError [WinError 5] 拒绝访问（2026-09-18 实测踩过，表现为
        南汐在群里回"DSH 没跑起来…拒绝访问"）。
        """
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        work_dir = cwd or DSH_WORKSPACE_DIR
        cmd = [
            NODE, CLI, BASE_URL, prompt,
            "--cwd", work_dir,
            "--progress-interval", str(PROGRESS_INTERVAL_MS),
        ]
        if session_id:
            # 指定会话（如 mas 答疑 fork 出来的分支会话）
            cmd += ["--session-id", session_id]
        elif session_key:
            cmd += ["--key", session_key]
        if fresh:
            cmd += ["--fresh"]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=PROJECT_DIR,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except FileNotFoundError as e:
            return f"DSH 调用失败：找不到 {e}"
        except Exception as e:  # noqa: BLE001
            return f"DSH 调用失败：{e}"

        line_q: "queue.Queue" = queue.Queue()
        err_chunks: list = []

        def pump_stdout() -> None:
            try:
                for line in iter(proc.stdout.readline, ""):
                    line_q.put(line)
            except Exception:  # noqa: BLE001
                pass
            finally:
                line_q.put(None)  # EOF 哨兵

        def pump_stderr() -> None:
            try:
                err_chunks.append(proc.stderr.read() or "")
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=pump_stdout, daemon=True).start()
        threading.Thread(target=pump_stderr, daemon=True).start()

        # 注册 AstrBot 的停止回调：用户发**内置命令** `@南汐 stop` 时，
        # conversation.stop() → active_event_registry.request_agent_stop_all() 会调用它。
        # 这是"复用内置 stop"的正确接入点 —— 不必自己注册同名命令（那会与内置命令双触发）。
        stop_cb_state = {"sid": None}

        def _on_stop_request() -> None:
            sid = stop_cb_state.get("sid")
            if sid:
                # 同步回调里不能 await，用线程去取消 DSH 侧那一回合
                try:
                    threading.Thread(target=self._cli_cancel, args=(sid,), daemon=True).start()
                except Exception:  # noqa: BLE001
                    pass
            # 同时终止本地 dsh_cli 子进程，让 handler 立刻返回
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:  # noqa: BLE001
                pass

        try:
            active_event_registry.register_agent_stop_callback(event, _on_stop_request)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[dsh] 注册停止回调失败（`@南汐 stop` 将无法中断本任务）: {e}")

        started = time.monotonic()
        result = None
        seen_session_id = None
        sent = 0
        last_sent_at = 0.0
        timed_out = False

        try:
            while True:
                remaining = TIMEOUT - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    line = await asyncio.to_thread(line_q.get, True, min(1.0, remaining))
                except queue.Empty:
                    # 每秒醒一次：重算剩余时间；顺便兜底检查是否被 `@南汐 stop` 叫停
                    if event.get_extra("agent_stop_requested") and proc.poll() is None:
                        try:
                            proc.kill()
                        except Exception:  # noqa: BLE001
                            pass
                    continue
                if line is None:
                    break  # 子进程结束
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    data = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue

                kind = data.get("type")
                if kind == "start":
                    # 登记到 _running，供 `@南汐 stop` 精准中断这个会话
                    sid = data.get("sessionId")
                    if sid:
                        seen_session_id = str(sid)
                        stop_cb_state["sid"] = seen_session_id
                        self._running[seen_session_id] = prompt.strip().replace("\n", " ")[:40]
                elif kind == "result":
                    result = data
                elif kind == "error":
                    result = {"error": data.get("error")}
                elif kind == "progress":
                    elapsed = float(data.get("elapsedMs", 0) or 0) / 1000.0
                    now = time.monotonic() - started
                    if (
                        sent < PROGRESS_MAX
                        and elapsed >= PROGRESS_FIRST_AFTER
                        and (sent == 0 or (now - last_sent_at) >= PROGRESS_MIN_INTERVAL)
                    ):
                        sent += 1
                        last_sent_at = now
                        try:
                            await event.send(
                                MessageChain([Plain(self._progress_text(int(elapsed)))])
                            )
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"[dsh] 进度提示发送失败: {e}")
        finally:
            try:
                active_event_registry.unregister_agent_stop_callback(event)
            except Exception:  # noqa: BLE001
                pass
            if seen_session_id:
                self._running.pop(seen_session_id, None)
            if timed_out or proc.poll() is None:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            try:
                await asyncio.to_thread(proc.wait, 10)
            except Exception:  # noqa: BLE001
                pass

        if timed_out:
            return (
                f"DSH 执行超时（>{TIMEOUT}s），已中止。\n"
                "（若这个任务涉及[工作区外写入]或[需要提权]，很可能正卡在 DSH 的审批上："
                "本工作区的普通读写不会触发审批，但请求提权会被 dsh-approval-gate 转人工，"
                "而 QQ 侧目前没有审批转发。可以改成在工作区内完成，或去 DSH Web "
                "127.0.0.1:3080 的审批面板处理。）"
            )
        if result is None:
            tail = "".join(err_chunks)[-300:]
            return "DSH 执行未返回有效结果。" + tail
        if "error" in result:
            return "DSH 执行失败：" + str(result["error"])
        return result.get("reply", "") or "DSH 跑完了，但没返回任何内容喵。"

    def _summarize(self, dsh_reply: str) -> str:
        """用南汐人格转述 DSH 结果给主人。"""
        try:
            user_msg = (
                "主人刚让你用 DSH(DeepSeek Harness) 替他执行了一个任务。下面是 DSH 执行该任务的原始结果：\n"
                "----DSH 结果----\n" + dsh_reply + "\n----DSH 结果结束----\n\n"
                "请用你自己的话、以南汐的口吻，用简洁亲切的中文，把结果告诉主人（不要复读上面的原始技术输出，"
                "要像你自己亲手做完一样向主人汇报；如果有需要提醒主人的地方也一并说）。"
            )
            body = json.dumps({
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": NANXI_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 900,
            }).encode("utf-8")
            req = urllib.request.Request(DEEPSEEK_URL, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", "Bearer " + DEEPSEEK_KEY)
            resp = urllib.request.urlopen(req, timeout=90)
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa: BLE001
            return "（南汐转述遇到点小问题，这是 DSH 的原始结果喵）\n" + dsh_reply
