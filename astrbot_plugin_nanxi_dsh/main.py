# -*- coding: utf-8 -*-
"""南汐 · 自主调用 DSH（把"需要真正动手的事"交给执行代理）。

为什么是现在这个样子（改动前请先读完这四条）：

1. **自主判断**。走 AstrBot 的 ``@filter.llm_tool``：由南汐自己的模型在对话中决定
   何时调用，不再依赖用户手打 ``dsh `` 前缀（``astrbot_plugin_dsh_relay`` 那条路），
   也不靠正则猜意图（旧 ``astrbot_plugin_dsh`` 那条路，已归档）。
   ⚠️ ``agent_runner_type`` 必须是 ``local``（本机即如此），否则工具不会下发给模型。

2. **不刷屏优先**。工具内部消费 DSH 的 SSE 事件流，但**默认不逐片直发**：正文在本地
   攒到最后，由 ``_send_body`` **一次性交付** —— 超过 ``merge_threshold`` 就自己打成一个
   合并转发 ``Node``（群里一张卡片），而不是一串各占一条的消息。
   ⚠️ ``event.send`` 绕过 ResultDecorateStage，所以 AstrBot 自带的 ``forward_threshold``
   在这里帮不上忙（那条路只作用于 LLM 最终的回复），长内容只能自己包。
   想回到旧的逐片流式，把配置项 ``stream`` 打开即可。

3. **收尾交还给南汐**。返回值分两种口径，避免群里出现两遍同样的内容：
   * 内容**已经**流式发过 → 只回一句"已发出，别重复"，让南汐用自己口气收尾；
   * 内容**一个字都没发**（短任务）→ 把 DSH 原文整段交给 LLM 转述，
     于是短任务在群里只有南汐一条消息，最自然。

4. **主人专属**。``owner_only`` 默认为真。DSH 在本机是 danger-full-access，
   绝不能让任何群友一句话就把整台机器交出去。

链路与触发口径（星驿那套，详见项目 AGENTS.md）：
* 顺序是硬要求 —— **先连 SSE 再 POST /message**，``text/delta`` 是瞬时事件，
  没有订阅者时永久丢失，反着做会丢掉开头几个 token；
* ``GET /events`` 必须带 ``?conversation=<UMO>``，否则 HTTP 400；
* 同 conversation 全程串行化：SSE 帧里没有消息 id，两路并发会互相串味。
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp
import mcp.types

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Node, Plain
from astrbot.api.star import Context, Star
from astrbot.core.star.star_tools import StarTools
from astrbot.core.utils.active_event_registry import active_event_registry

PLUGIN_NAME = "astrbot_plugin_nanxi_dsh"

#: 台账里"家"那一格的键。家 = 出差干完活要回去的那间默认会话。
HOME_KEY = "__home__"

#: 台账里「可撤销的会话操作栈」那一格的键（``dsh_undo`` 靠它回退）。
UNDO_KEY = "__undo__"
#: 撤销栈最多留多少步，再老的自动挤掉。
UNDO_DEPTH = 12

#: ``dsh_undo`` 的 ``what`` 参数 → 栈里 ``op`` 的别名表（中文说法归一到内部 op 名）。
_UNDO_ALIASES = {
    "归档": "archive", "archive": "archive", "收起来": "archive",
    "分支": "fork", "副本": "fork", "fork": "fork", "分家": "fork",
    "新建": "rebind", "换工作台": "rebind", "rebind": "rebind", "出差": "rebind",
    "接手": "adopt", "切换": "adopt", "adopt": "adopt", "回到": "adopt",
}
#: op → 给人看的中文名（拼错误提示、给人读的日志用）。
_UNDO_LABELS = {
    "archive": "归档", "fork": "分支", "rebind": "新建", "adopt": "接手",
}

#: 桥接路由（契约 §3.1 / §3.2）。
ROUTE_MESSAGE = "/message"

#: 星驿的审批回执端点（契约 §3.3）：`{conversation, callId, outcome, code}`。
ROUTE_APPROVAL = "/approval"

#: 主人回什么算「放行这一次」/「否掉」一项审批（见 :meth:`_reply_approval`）。
_APPROVE_WORDS = frozenset({"同意", "批准", "允许", "可以", "行", "好", "allow", "yes", "ok"})
_REJECT_WORDS = frozenset({"拒绝", "不行", "否", "不要", "别", "reject", "no", "deny"})

#: 南汐**自己**的浏览器（纯 Python 驱动本机 Chrome，实现见同目录 ``browser.py``）。
#: ⚠️ 用动态加载而不是 ``import browser`` —— AstrBot **不会**把插件目录放进 ``sys.path``，
#: 直接 import 会 ModuleNotFoundError。
_BROWSER_SPEC = importlib.util.spec_from_file_location(
    "nanxi_dsh_browser", Path(__file__).resolve().parent / "browser.py"
)
browser_mod = importlib.util.module_from_spec(_BROWSER_SPEC)
_BROWSER_SPEC.loader.exec_module(browser_mod)

#: 会话日志完整性检查脚本（`dsh_rename` 改完名就跑一遍）。
#: 跟着**插件目录**走；仓库根 `tools\repair_session_title_event.mjs` 是给命令行用的同名副本，
#: 两边内容要保持一致（和 main.py 的仓库根/部署副本一个道理）。
INTEGRITY_SCRIPT = "repair_session_title_event.mjs"

#: 星驿 `/message` 的 `images[].mediaType` 只认这四种（契约 §3.1 的闭集）。
_IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


def _sniff_image_media_type(b64: str) -> str:
    """从 base64 的前几个字节认出图片类型 —— 认不出来就当 PNG 报。

    为什么要嗅探而不是看文件名/URL：星驿的 `images[]` **必须**带 `mediaType`，
    而 AstrBot 的 ``Image.convert_to_base64()`` 只给裸 base64、不给类型；
    QQ 给的图片 URL 又常常没有可用的扩展名（后面挂一串 query）。看**字节魔数**最可靠：
    PNG `89 50 4E 47` / JPEG `FF D8 FF` / GIF `47 49 46 38` / WebP `RIFF….WEBP`。

    Args:
        b64: 裸 base64（不带 ``data:`` 前缀）。

    Returns:
        str: 四种 mediaType 之一；认不出来时固定返回 ``image/png``（宁可按最保守的报，
            也不要给星驿一个它会 400 的值）。
    """
    try:
        head = base64.b64decode(b64[:64], validate=False)
    except Exception:  # noqa: BLE001 - 嗅探失败不该让整条消息投不出去
        return "image/png"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"
ROUTE_EVENTS = "/events"
#: 定位（某 IM 对话 → 它当前指向哪间 DSH 会话）与控制面转发（§11）。
ROUTE_WHERE = "/where"
ROUTE_RPC = "/rpc"

#: 事件类型（契约 §4）。未知类型一律忽略，保证前向兼容。
_EVENT_TURN_START = "turn/start"
_EVENT_TEXT_DELTA = "text/delta"
_EVENT_REASONING_DELTA = "reasoning/delta"
_EVENT_TOOL_CALL = "tool/call"
_EVENT_APPROVAL_REQUIRED = "approval/required"
_EVENT_APPROVAL_RESOLVED = "approval/resolved"
_EVENT_QUESTION_REQUIRED = "question/required"
_EVENT_QUESTION_RESOLVED = "question/resolved"
_EVENT_MESSAGE_FINAL = "message/final"
_EVENT_TURN_END = "turn/end"
_EVENT_HEARTBEAT = "heartbeat"
_EVENT_GAP = "gap"

#: SSE 的 socket 读超时（秒）的兜底值。
#:
#: ⚠️ 别再调回 45 秒 —— 2026-10-04 实测翻过车：「看看 mas 下那个 baah 会话」时
#: DSH 长时间不吐字，45 秒就判超时了；而**服务端那次投递并不会因为客户端走了被取消**，
#: 那个会话于是永久卡在 `attaching`（`/health` 的 `pending` 里能看到），
#: 后续所有 adopt / rebind 全被 **HTTP 409「该会话有投递或附件」** 拒掉 ——
#: 表现就是"南汐卡住了"，只能重启她的 DSH 实例才解得开。
#: 心跳（heartbeatMs=15000）不等于内容，想事情慢是常态，故放宽到 180 秒，
#: 并允许用配置项 ``sse_read_timeout`` 覆盖。
_DEFAULT_SSE_READ_SECONDS = 180.0

#: ---- 事件账本（给 WebUI「思维链」页面用）--------------------------------
#:
#: 地基抄的是 MaiBot「麦麦观察」那套：**单调自增 event_id 的事件账本 + 前端游标补发**。
#: 三条纪律，都是那套系统用血换来的，照守：
#:   ① **按 event_id 排序，不能按时间戳** —— 写入顺序才是真相（同一毫秒内多件事很常见）；
#:   ② **卡片身份要稳定**（这里用 ``turn``）—— 重复推送只原位刷新，别每次新增一条；
#:   ③ **分配 event_id 与对外可见要串行** —— 否则前端游标会越过还没送达的事件，
#:      断线重连后就**永久丢事件**。这里只做只读观察、暂不广播（前端轮询），
#:      但前两条照守，第三条留给将来上推流时用。
#:
#: 与主库无关：独立一个小 SQLite（``data/plugin_data/<插件>/trace.db``），
#: 删掉它只是丢掉观察记录，不影响任何功能。
TRACE_DB_NAME = "trace.db"
TRACE_MAX_RECORDS = 10000
TRACE_MAX_AGE_HOURS = 72
TRACE_SCHEMA_VERSION = 1


def _parse_sse_block(lines: list[str]) -> dict[str, Any] | None:
    """按 SSE 规范把一个事件块拼成字典；非 JSON 或空块一律忽略，不抛。"""
    if not lines:
        return None
    data: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if not data:
        return None
    try:
        payload = json.loads("\n".join(data))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _pick_cut(text: str, soft: int, hard: int) -> int:
    """在 ``text`` 里挑一个"切在这里不会难看"的下标；返回 0 表示再攒攒。

    优先段落/换行，其次句末标点，实在没有就按 ``hard`` 硬切 ——
    硬切只是为了不让单条消息超过 ``chunk_size``，不是为了好看。
    """
    if len(text) >= hard:
        limit = hard
    elif len(text) >= soft:
        limit = len(text)
    else:
        return 0
    window = text[:limit]
    floor = max(1, int(soft * 0.6))
    for sep in ("\n\n", "\n", "。", "！", "？", "；", "…", ". ", "! ", "? "):
        idx = window.rfind(sep)
        if idx >= floor:
            return idx + len(sep)
    return limit


class Main(Star):
    """注册 ``dsh_task`` 工具，让南汐自己决定何时把事情交给 DSH。"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config
        #: 同会话串行化。SSE 帧里没有消息 id，两路并发会把别人的 token 混进来。
        self._locks: dict[str, asyncio.Lock] = {}
        #: 异步交活用的队列与 worker：**每个 IM 会话一条**，串行消费 ——
        #: DSH 侧一个会话同时只能跑一个 turn，并发投递会互相踩。
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        #: 后台干完的活的结果，等着在**她的下一轮请求**里补回上下文（见 :meth:`watch_request`）。
        #: ⚠️ 异步交活之后 tool result 只剩一句"已交出去"，正文只发到了群里 ——
        #: 不补这一步她就"手上一片空白"，主人一问细节只能抓瞎（2026-10-04 实测被点名）。
        self._inbox: dict[str, str] = {}
        #: 正等着主人批准的敏感操作（每会话一条）。星驿接管审批时会把 4 位一次性码
        #: 通过 `approval/required` 事件推下来，主人回一句「同意」/「拒绝」我们就替他把
        #: `POST /approval` 打回去（契约 §3.3：outcome 只能是 allowed-once / rejected）。
        self._pending_approval: dict[str, dict[str, Any]] = {}
        #: 南汐自己的浏览器（懒启动；第一次真用时才拉起 Chrome）。
        self._web: Any = None
        #: 那个"只看不摸"的看板（让人在浏览器里看她那台 headless 在干什么）。
        self._watch: Any = None
        #: 配置文件热读缓存（见 :meth:`_cfg`）：调白名单/黑白名单时不必重启 AstrBot。
        self._cfg_stamp: tuple[int, int] | None = None
        self._cfg_cache: dict[str, Any] | None = None
        #: 工作台摘要缓存（见 :meth:`_workspace_digest`）：给 system prompt 用的项目清单，
        #: 缓存 60 秒，免得每轮请求都去问一遍 DSH。
        self._boards_cache: tuple[float, str] | None = None
        #: 观察面板的只读接口（同源、带登录 cookie，不用另搞鉴权）。
        #: ⚠️ route 必须**自带插件名前缀** —— AstrBot 是把
        #: `/plugins/extensions/{plugin_path:path}` 里的**完整 plugin_path**
        #: （即 `astrbot_plugin_nanxi_dsh/state` 这样）丢给路由匹配器的。
        #: 只写 `state` 会 404（且因为认证中间件先拦，匿名访问看到的是 401，
        #: 极易误判成"路由挂上了、只是没登录"）。
        try:
            context.register_web_api(
                f"{PLUGIN_NAME}/trace/<since>",
                self.api_trace,
                ["GET"],
                "南汐观察 · 事件增量",
            )
            context.register_web_api(
                f"{PLUGIN_NAME}/state", self.api_state, ["GET"], "南汐观察 · 当前状态"
            )
            context.register_web_api(
                f"{PLUGIN_NAME}/boards", self.api_boards, ["GET"], "南汐观察 · 工作台"
            )
            # 打一行实际注册结果：路由 404 时先看这里（比猜正则快得多）
            logger.info(
                "[nanxi_dsh] 观察接口已注册 %d 条：%s",
                len(context.registered_web_apis),
                ", ".join(str(item[0]) for item in context.registered_web_apis),
            )
        except Exception as exc:  # noqa: BLE001 - 面板注册失败不该影响聊天
            logger.warning(f"[nanxi_dsh] 注册观察接口失败（面板会空着）：{exc}")

    # ---- 观察面板的接口 ------------------------------------------------
    #
    # 三个只读口子，挂在 /api/plugins/extensions/<插件名>/… 下（同源 iframe 自带
    # 登录 cookie，所以不用另做鉴权）。
    # ⚠️ AstrBot 的插件 API handler **只收路径参数**（view_handler(**path_values)），
    # 拿不到 query string —— 所以游标走路径（/trace/0、/trace/1234）而不是 ?since=。

    async def api_trace(self, since: str = "0") -> dict[str, Any]:
        """事件增量。``since`` 是前端上次收到的最大 event_id（0 = 给我最近一段）。

        Args:
            since: 路径参数，字符串形式的 event_id。

        Returns:
            含 ``events``（按 event_id 升序）与 ``last``（新游标）的字典。
        """
        try:
            since_id = int(str(since or "0").strip() or "0")
        except ValueError:
            since_id = 0
        events = self.trace_query(
            since_event_id=since_id, limit=300 if since_id > 0 else 120
        )
        return {
            "ok": True,
            "events": events,
            "last": events[-1]["event_id"] if events else since_id,
        }

    async def api_state(self) -> dict[str, Any]:
        """当前状态：她在哪间会话、cwd 是什么、台账记了哪些项目。"""
        out: dict[str, Any] = {"ok": True}
        try:
            wb = self._workbench()
            conv = next(iter(wb), "") if isinstance(wb, dict) else ""
            if conv:
                where = await self._where(conv)
                sid = str(where.get("sessionId") or "")
                meta = self._session_meta(sid)
                memory = wb.get(conv) or {}
                out.update(
                    {
                        "conversation": conv,
                        "session_id": sid,
                        "cwd": str(where.get("cwd") or ""),
                        "title": str(meta.get("title") or ""),
                        "memory": {
                            k: v for k, v in memory.items() if isinstance(v, str)
                        }
                        if isinstance(memory, dict)
                        else {},
                    }
                )
        except Exception as exc:  # noqa: BLE001 - 面板读不到就空着，别抛
            out["error"] = str(exc)
        return out

    async def api_boards(self) -> dict[str, Any]:
        """工作台：各项目的会话数与最近在忙什么（黑名单里的不出现）。"""
        try:
            boards = await self._workspaces()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "items": []}
        items: list[dict[str, Any]] = []
        for board in boards:
            if self._board_denied(board):
                continue  # 拉黑的项目连名字都不给面板看
            ids = [
                str(x)
                for x in (board.get("sessionIds") or [])
                if not self._session_denied(str(x))
            ]
            metas = [self._session_meta(i) for i in ids]
            metas = [m for m in metas if m]
            metas.sort(key=lambda m: m.get("mtime", 0), reverse=True)
            items.append(
                {
                    "title": str(board.get("title") or ""),
                    "path": str(board.get("path") or ""),
                    "sessions": len(ids),
                    "recent": [
                        {"title": str(m.get("title") or "")} for m in metas[:3]
                    ],
                }
            )
        return {"ok": True, "items": items}

    # ---- 配置与闸门 --------------------------------------------------

    def _cfg(self, key: str, default: Any = None) -> Any:
        """读配置。``AstrBotConfig`` 继承 dict，但缺失键与显式 None 都要回落默认值。

        **顺手盯一眼配置文件**：AstrBot 只在启动时加载插件配置，而 ``owner_qq``、
        ``workspace_deny`` 这类旋钮调一次就要重启一次，非常烦。这里在内存副本之外
        看一眼 ``data/config/<插件名>_config.json`` 的 mtime —— 变了就用文件里的值。
        读的是几 KB 的 JSON，且只在 mtime 变化时解析，代价可以忽略。
        """
        live = self._cfg_live()
        if live is not None:
            value = live.get(key)
            if value is not None:
                return value
        if self.config is None:
            return default
        value = self.config.get(key) if hasattr(self.config, "get") else None
        return default if value is None else value

    def _cfg_path(self) -> Path | None:
        """插件配置文件：``<data>/config/<插件名>_config.json``。

        由本文件位置反推（``<data>/plugins/<插件名>/main.py``），不依赖 AstrBot 内部结构。
        """
        try:
            data = Path(__file__).resolve().parents[2]
        except IndexError:  # pragma: no cover - 只会在异常布局下发生
            return None
        return data / "config" / f"{PLUGIN_NAME}_config.json"

    def _cfg_live(self) -> dict[str, Any] | None:
        """文件有更新就重读，否则复用缓存（mtime 没变时连解析都不做）。"""
        path = self._cfg_path()
        if path is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self._cfg_stamp:
            return self._cfg_cache
        self._cfg_stamp = stamp
        try:
            raw = path.read_text(encoding="utf-8-sig")
            self._cfg_cache = json.loads(raw) if raw.strip() else {}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[nanxi_dsh] 配置文件解析失败，继续用内存里的那份：{exc}")
            self._cfg_cache = None
        return self._cfg_cache

    def _conversation_lock(self, conversation: str) -> asyncio.Lock:
        lock = self._locks.get(conversation)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[conversation] = lock
        return lock

    def _allowed(self, event: AstrMessageEvent) -> bool:
        """主人闸门。DSH 侧权限很大，默认不放给群友。

        ``owner_qq`` 支持写多个（逗号/空格/分号/顿号分隔，中英文标点都认），
        方便临时把测试号放进来一起做验收 —— **测完记得删掉**。
        """
        if not bool(self._cfg("owner_only", True)):
            return True
        raw = str(self._cfg("owner_qq", "") or "")
        for sep in ("，", "；", ";", "、", "|", "\n", "\r", "\t", " "):
            raw = raw.replace(sep, ",")
        owners = [p.strip() for p in raw.split(",") if p.strip()]
        return str(event.get_sender_id()) in owners

    # ---- 工具本体 ----------------------------------------------------

    @filter.on_llm_request()
    async def watch_request(self, event: AstrMessageEvent, req: Any) -> None:
        """把"你有 DSH 这双手"写进系统提示，并确认工具真的下发了。

        **为什么非要在 system prompt 里再说一遍**：工具描述是弱注意力区，实测只靠它
        时，模型面对"帮我数一下某目录下有几个 .md"照样回"我看不到你本地 D 盘"。
        这跟能力无关，是模型的自我认知问题 —— 它默认自己是个纯聊天机器人。
        还有更坏的一种：一旦某一轮它说过"我做不到"（比如非主人被拒那次），
        这句话就留在上下文里，**之后的请求它也会照着演**，连主人都会被带偏。
        所以这里既给它能力认知，也挡住"我做不到"这个说法。

        "南汐为什么不用我"只有三种原因，而且它们在这里的表现完全不同：
        工具没注册 / 注册了没激活 / 激活了但被人格的 ``tools`` 白名单挡掉
        （本机踩过第三种：``tools = []`` 不等于 ``None``，等于一个工具都不给）。
        所以**只在缺失时告警**，正常情况打 DEBUG，不刷日志。
        """
        # 顺手把"看板"挂上 —— 放在最前面、且与这轮有没有 dsh_task 无关。
        # Chrome 仍是懒启动（_ensure_watch 只构造 Browser 对象），所以这么做不占资源；
        # 好处是**重启 AstrBot 之后不用干等她真的用一次浏览器**，看板一直都在。
        with contextlib.suppress(Exception):
            await self._ensure_watch()
        try:
            tool_set = getattr(req, "func_tool", None)
            names = tool_set.names() if tool_set is not None else []
        except Exception as exc:  # noqa: BLE001 - 观测失败绝不能影响正常请求
            logger.warning(f"[nanxi_dsh] 无法读取本次请求的工具集：{exc}")
            return
        if "dsh_task" not in names:
            logger.warning(
                f"[nanxi_dsh] dsh_task 不在本次请求的工具集里（{names}）——"
                "南汐这轮没法调用它。请检查：插件 enable / 人格的 tools 白名单是否含 dsh_task。"
            )
            return
        logger.debug(f"[nanxi_dsh] 本次工具集 = {names}")

        #: 幂等标记：tool loop 里每轮请求都会过这个钩子，别把同一段话叠好几次。
        marker = "【关于 DSH】"
        prompt = (
            f"{marker}你手边有一个执行代理 DSH：它跑在这台真实的 Windows 机器上，"
            "能读文件和目录、执行命令、写代码、查网页。凡是需要碰到这台机器的事"
            "（读文件、看目录、跑命令、查代码、搜资料、多步骤的活），"
            "就调用 dsh_task 交给它去做。"
            "**绝不要回答「我看不到你的电脑」「我访问不了本地文件」，也不要让用户自己去敲命令** ——"
            "那不是你的能力问题，只是你还没叫 DSH 而已。"
            "\nDSH 里每个项目目录是一张工作台（mas、QQbot、qirta 这些），每张台子上有若干间会话。"
            "主人交代的事属于哪个项目，就在 dsh_task 的 at 里填那个项目名 —— "
            "同一个项目你会固定用同一间会话，不用每次重新交代背景；"
            "拿不准有哪些项目、或者现在在哪一间，用 dsh_look 看一眼；"
            "想试个新做法又不想弄脏正在用的那间，先 dsh_fork 分一份副本出来。"
            "**不属于任何明确项目的杂事，at 留空就行** —— 干完活你会自动回到默认那间。"
            "\n【两条硬规矩，务必遵守】"
            "① 主人问「你有哪些项目」「现在待在哪间」「某间在忙什么」这类**关于工作台本身**的问题，"
            "**只用 dsh_look 回答，绝对不要用 dsh_task**。实测用 dsh_task 去查这些的代价是："
            "多花几十秒、把会话线切走、还在群里刷一串「正在用 pwsh / glob / read」的废过程。"
            "dsh_look 是只读的、一秒返回，看到什么就用自己的口气说出来。"
            "② `dsh_task` 的 at **只在主人明确说「去某个项目那边做」时才填**"
            "（例如「去 mas 看看」「到 QQbot 项目里改个东西」）。"
            "**任务文字里出现路径或项目名，不等于要换项目** ——"
            "「数一下 D:/dsh/QQbot/nx_dsh 下有几个文件」这种，at 必须留空。"
            "乱填会把会话线切走再切回来，群里还会冒出误导人的「换到…」提示。"
            "别拿反问代替动手：问你能不能做某件事，就直接试，别先问「要不要我做」。"
            "日常闲聊、撒娇、常识问答不要用这些。"
            "\n【你还有一双眼睛和一只手：浏览器】DSH 那台机器上装了浏览器自动化"
            "（dsh-ego-browser），它能**真的打开网页**、点按钮、填表单、滚动、截图。"
            "所以碰到**没有命令行接口的东西** —— 某个 Web 后台、在线看板、网页版的设置页、"
            "要登录的管理界面 —— 别回「那个我操作不了」，让 DSH 用浏览器去做；"
            "它甚至能打开 DSH 自己的 Web 界面（http://127.0.0.1:3081）去看会话状态。"
            "写任务时把「用浏览器打开 X，点到 Y，把 Z 读回来」写清楚就行。"
            "\n【而且你自己也有一双浏览器的手】"
            "web_open（开网页并读正文）、web_look（截图 —— **图会直接进你的视野**，"
            "你现在是能看图的）、web_click / web_click_at（点）、web_type（填字）、"
            "web_read（读当前页）、这些是**你本人的手和眼睛**，不是叫 DSH 去干。"
            "页面上那些**纯命令行的 DSH 干不了的、或者你自己就能一步做完的**，直接用它们。"
            "\n⚠️ 判断这几个工具**在不在、能不能用**，唯一的办法是**真的调用一次**："
            "框架会把错误原文回给你（比如「Tool web_open not found」）。"
            "**没调用过就说「我的浏览器本事没了 / 工具找不到」，那是编的** ——"
            "上下文里你以前说过的话、或者上一轮失败过，都不等于这一轮也不行。"
            "**先试，再下结论。**"
        )
        # 把**当前的工作区清单**带进每一轮请求：她总把 at 留空、窝在默认工位，
        # 根子就是不知道有哪些项目可选（只有主动调 dsh_look 才看得到，她又不调）。
        digest = await self._workspace_digest()
        if digest:
            prompt += (
                f"\n【当前工作区】{digest}。"
                "判断这件事属于哪个项目，就把它填进 dsh_task 的 at ——"
                "**不要一律留空窝在默认工位**；只有确实不属于任何项目的杂事才留空。"
                "拿不准某个项目在忙什么，再调 dsh_look 细看。"
            )
        current = getattr(req, "system_prompt", "") or ""
        if marker not in current:
            req.system_prompt = f"{current}\n{prompt}\n"

        # 【DSH 回执】把**后台干完那件活**的结果补回她的上下文。
        # ⚠️ 这是异步交活必须配套的一步：同步时代正文是随 tool result 回去的，改成异步之后
        # tool result 只剩一句"已交出去"、正文只发进了群，于是她"手上一片空白"、
        # 主人一问细节就抓瞎 —— 2026-10-04 主人实测点名："刚刚的返回你没看到吗"。
        # ⚠️ 注入 `contexts`（对话历史）而不是 ``system_prompt``：后者每轮重算、用完即弃，
        # 塞那儿她下一轮又忘；进历史才会一直记得。取走即清，不会重复注入。
        note = self._inbox.pop(event.unified_msg_origin, None)
        if note:
            req.contexts.append(
                {
                    "role": "user",
                    "content": (
                        "（系统提示：DSH 后台那件活干完了，下面是它的**真实结果** —— "
                        "群里已经发过一份，你手上这份是给你看的：主人问起就据此回答，"
                        "但**不要再往群里复述一遍**。）\n" + note[:12000]
                    ),
                }
            )
            logger.info(
                f"[nanxi_dsh] 已把后台结果补回上下文（{len(note)} 字符，"
                f"{event.unified_msg_origin}）"
            )

    @filter.llm_tool(name="dsh_task")
    async def dsh_task(self, event: AstrMessageEvent, task: str, at: str = "") -> str:
        '''把一件需要真正动手完成的事交给 DSH 执行代理去做。它有一台真实 Windows 机器的完整能力：读写本机文件、执行命令、查目录、看代码、搜网页、装环境、分析项目。

        **只要用户要你做的事需要碰到这台机器（读文件、写文件、跑命令、查目录、看代码、抓网页、干多步骤的活），就必须调用这个工具，不要回答"我看不到你的电脑"，也不要让用户自己去敲命令。你自己没有手，DSH 才是你的手。**

        你有一张工作台：DSH 里每个项目目录是一个工作区（mas、QQbot、qirta 这些），每个工作区里有若干间会话。**事属于哪个项目，就把那个项目填进 at** —— 同一个项目你会有固定的那间会话，第二次去不用重新交代背景。

        ⚠️ **别把「要不要换到那个项目」当成问题回抛给用户。** 用户已经明确说过"以后这种局不要停下来问我了"——**目标一旦清楚，该切就直接切**，切完在收尾里顺口提一句就行；回头请示"要我切过去吗"只会被嫌啰嗦（2026-10-04 实测被主人点名批评过）。
        （这里禁的是**已知目标、还回头确认要不要切**；要是"这件事到底属于哪个项目"本身拿不准，那当然还是可以问。）

        什么时候不该用：日常闲聊、打招呼、撒娇、情感陪伴、讲笑话、简单常识问答，以及你本来就能直接答上来的问题。**如果主人只是想知道有哪些项目、现在在哪间、某间在忙什么，用 dsh_look —— 别用这个去翻目录，那要几十秒，dsh_look 一秒就够了。**

        **这条消息里如果带图（截图、照片、报错画面），插件会自动把图一起交给 DSH —— 它直接就能看见。** 所以别为了让它看图而特意把图片路径写进 task：那是多此一举，2026-10-04 实测会变成"图上送一遍、路径再写一遍"的重复交代。只有用户明确要它去读**某个路径上的文件**时才写路径。

        ⚠️ **这是异步交活**（2026-10-04 起）：这个工具会**立刻返回**，DSH 在后台干，过程与结果都会自动发到群里。所以**交完就往下走** —— 不要在原地等结果、不要说"我盯着它干完"，也不要替它复述内容；主人接着说什么你就正常接（这正是不再让他等你 61 秒的意义）。DSH 干完时群里会自己冒出结果和一句"干完了"。

        Args:
            task(string): 交给 DSH 的完整任务描述。它看不到我们的聊天记录，所以要把目标、必要的背景（比如涉及哪个目录、哪个项目）和期望的结果写清楚，别只丢一个短句。
            at(string): 可选，**绝大多数情况都该留空**。留空 = 就在现在这间会话里干。只有当用户**明确表示"去某个项目那边做"**（例如"去 mas 那边看看"、"到 QQbot 项目里改个东西"）时才填那个项目名（如 mas、QQbot、xtlr），或它的目录路径，或一个具体会话 id 直接接手那间。⚠️ **任务文字里出现了某个路径，不等于要换项目** —— "数一下 D:/dsh/QQbot/nx_dsh 下有几个文件"只是要读那个目录，`at` 必须留空。乱填会把会话线切走再切回来，不但多绕两趟，群里还会冒出误导人的"换到…"提示。想"开一份不影响原会话的副本"请先用 dsh_fork。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭，请用你自己的话告诉用户这件事暂时做不了。）"

        if not self._allowed(event):
            logger.info(
                f"[nanxi_dsh] 非主人（{event.get_sender_id()}）尝试调用工具，已拒绝"
            )
            return (
                "（这次请求不是主人发来的，已经拒绝执行。但要记住：**这个能力你是有的**，"
                "只是不给他用而已。请用你自己的口吻礼貌地回绝他，说这种事只有主人吩咐你"
                "才会做；**不要说做不到，也不要说你访问不了本地文件**，"
                "更不要教他自己去敲命令。不要提及工具或 DSH 这类字眼。）"
            )

        text = str(task or "").strip()
        if not text:
            return "（任务描述是空的，什么也没交给 DSH。请让用户把要做的事说清楚。）"

        conversation = event.unified_msg_origin
        #: 卡片身份 —— 这一轮的所有观察事件共用它，前端据此原位刷新同一张卡，
        #: 而不是每来一条事件就往上堆一张（一次任务能有两三张而不是二十张）。
        turn = uuid.uuid4().hex[:10]
        # 换工作台、干活、回家必须在同一把锁里：两路并发会把映射切串。
        async with self._conversation_lock(conversation):
            # 开工前先把「家」建好：星驿用 /message 裸建出来的会话没有 workspaceId，
            # 而 fork 只把副本挂到「源会话所在的工作区」——源没归属，副本就落「未分组」。
            # 这里复用的正是收工后那套回家逻辑（没家就 rebind 到 home_workspace 建一间有归属的）。
            if not str(at or "").strip():
                await self._go_home(event, conversation)
            moved = await self._goto(event, conversation, str(at or "").strip())
            if moved:
                return moved  # 没切成功：把原因原样交回给 LLM，别硬着头皮干
            logger.info(
                f"[nanxi_dsh] 南汐自主调用（{conversation}，at={at or '-'}）：{text[:80]}"
            )
            self.trace_emit(
                "decision", conversation, turn, at=str(at or ""), task=text[:300]
            )
            try:
                return await self._execute(event, conversation, text, turn)
            finally:
                # 出差干完就回工位：群里那条主线不该被某个项目借走。
                await self._go_home(event, conversation)

    @filter.llm_tool(name="dsh_look")
    async def dsh_look(self, event: AstrMessageEvent) -> str:
        '''看一眼 DSH 这张工作台：你现在在哪间会话、有哪些项目可以去、每个项目最近在忙什么。

        **主人问起「你有哪些项目」「你能在哪儿干活」「现在在做什么」，或者你拿不准这活儿该落在哪儿时，直接调用它去看 —— 不要反问主人，也不要凭记忆猜。** 这是只读的，不会改变任何状态。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人问，你才可以去看。请用你自己的口吻回绝他。）"
        conv = event.unified_msg_origin
        self.trace_emit("look", conv)
        try:
            return await self._board_text(conv)
        except Exception as exc:  # noqa: BLE001
            return f"（看工作台失败：{exc}）"

    @filter.llm_tool(name="dsh_fork")
    async def dsh_fork(self, event: AstrMessageEvent) -> str:
        '''把现在这间 DSH 会话复制一份，并带着这份副本继续往下干。

        用在"这次想试个新做法，但不想弄脏原来那间会话"的时候 —— 副本继承了现在为止的全部上下文，原会话一个字节都不动，之后你就在副本里干活了。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"

        conversation = event.unified_msg_origin
        async with self._conversation_lock(conversation):
            try:
                here = await self._where(conversation)
                source = str(here.get("sessionId") or "")
                if not source:
                    return "（这条会话线还没建过会话，没有可分支的东西。）"
                made = await self._relay_post("/session/fork", {"sessionId": source})
                target = str(made.get("sessionId") or "")
                if not target:
                    return f"（分支没拿到新会话 id：{made}）"
                await self._relay_post(
                    "/session/adopt",
                    {"conversation": conversation, "sessionId": target},
                )
            except Exception as exc:  # noqa: BLE001
                return f"（分支失败：{exc}）"

            meta = self._session_meta(target)
            self._remember(conversation, str(meta.get("cwd") or ""), target)
            self._push_undo(conversation, "fork", source, target)
            await self._say(
                event,
                f"· 分了一间副本出来（{target[:16]}…，继承了 "
                f"{made.get('inheritedEventCount', '?')} 条上下文），接下来在这里干",
            )
            return (
                f"（已经分支到新会话 {target}，你现在就在这间里干活。"
                "请用你自己的口吻告诉用户你另开了个副本在试，原来那间没动。）"
            )

    @filter.llm_tool(name="dsh_new")
    async def dsh_new(self, event: AstrMessageEvent, workspace: str = "") -> str:
        '''开一间**全新的空白会话**，并把你切过去 —— 它不继承任何上下文，从零开始。

        和 dsh_fork 的分工：**dsh_fork 是"复制现在这间"**（带上全部上下文，适合"换个做法但保留来龙去脉"）；
        **dsh_new 是"另起一间空的"**（什么都不带，适合"这件事跟之前无关，别被旧上下文带偏"）。
        用户说"开个新会话""新建一间""从头来""别用刚才那些"时用它。

        Args:
            workspace(string): 可选，在哪个项目里开，填项目名或目录路径（如 mas、D:\\dsh\\mas）。**绝大多数情况都该留空** —— 留空 = 就在你此刻所在的那个项目里开一间。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"

        conversation = event.unified_msg_origin
        async with self._conversation_lock(conversation):
            try:
                boards = await self._workspaces()
            except Exception as exc:  # noqa: BLE001
                return f"（连不上 DSH 工作台，没敢乱开：{exc}）"

            # 问不到当前位置不算错 —— 退到默认工位就好，别因此拒绝干活。
            here: dict[str, Any] = {}
            try:
                here = await self._where(conversation)
            except Exception:  # noqa: BLE001
                here = {}

            want = (workspace or "").strip() or str(here.get("cwd") or "")
            board = self._match_board(boards, want) if want else None
            if board is None:
                board = self._home_board(boards)
            if board is None:
                names = "、".join(
                    str(b.get("title") or b.get("path") or "?") for b in boards
                )
                return f"（认不出该在哪个项目里开，现有工作区：{names}。）"
            if self._board_denied(board):
                return (
                    f"（「{board.get('title') or board.get('path')}」不在允许南汐去的名单里。）"
                )

            before = str(here.get("sessionId") or "")
            try:
                made = await self._relay_post(
                    "/session/rebind",
                    {
                        "conversation": conversation,
                        "workspaceId": str(board.get("id") or ""),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                return f"（开新会话失败：{exc}）"

            target = str(made.get("sessionId") or "")
            if not target:
                return f"（DSH 没给出新会话 id：{made}）"
            label = str(board.get("title") or board.get("path") or "?")
            self._remember(conversation, str(board.get("path") or ""), target)
            # ⚠️ `before` 为空**也要压栈**（那条记录 from=""）。
            # 否则「第一次在某条会话线上开一间、然后马上想撤掉」只会得到一句「退不回」——
            # 2026-10-04 真踩到：主人在只有测试小号的线上 dsh_new 之后说"撤回"，
            # 她只能如实报「最近没有可以撤回的会话操作」。
            # **没有「上一间」可退，不等于什么都不该做** —— 至少该把那间新建的收掉。
            if before != target:
                self._push_undo(conversation, "rebind", before, target)
            await self._say(
                event,
                f"· 在 {label} 开了一间**空白**新会话（{target[:16]}…，不继承上下文）",
            )
            return (
                f"（已经在「{label}」里开出一间**全新的空白会话** {target} —— "
                "上下文是空的，**没有**继承之前任何东西，你现在就在这间里干活。"
                "请用你自己的口吻告诉用户：这是一间真正的新会话（不是分支副本），"
                "然后接着干他要你干的事。）"
            )

    @filter.llm_tool(name="dsh_rename")
    async def dsh_rename(self, event: AstrMessageEvent, name: str, session: str = "") -> str:
        '''给一间 DSH 会话**改名字** —— 只改你在会话列表里看到的那行标题，不动里面的内容。

        用在"这间以后就叫 xxx 吧""名字太乱，给它起个名""把刚才那间改名"的时候。
        **改名是安全的，不用反问用户确不确定**：改完插件会立刻检查那间会话的日志有没有被
        DSH 的改名流程写坏（它有个已知的 seq 撞车 bug），坏了当场自动修好。

        约定：项目里的会话名统一以 `_南汐` 结尾（你和主人用过的会话都这样），
        所以这里会自动补上这个尾巴 —— 你要做的只是给个短而好认的前缀。

        Args:
            name(string): 新名字（前缀），必填。起个一眼认得出的短名，比如「baah 活动卡片」，别超过 30 字。
            session(string): 可选，要改哪一间（会话 id）。**绝大多数情况都该留空** —— 留空 = 你和用户此刻正在用的这一间。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"

        title = " ".join((name or "").split())
        if not title:
            return "（要改成什么名字？把新名字告诉我。）"
        if not title.endswith("_南汐"):
            title = f"{title}_南汐"
        if len(title.encode("utf-8")) > 72:
            return "（名字太长了 —— DSH 的标题上限是 80 字节，起短一点。）"

        conversation = event.unified_msg_origin
        # ⚠️ **这里故意不加 `_conversation_lock`。**
        # 改名只写一条 title 事件、**不动会话映射**（不像 dsh_task/dsh_fork/dsh_new 那样
        # 换工作台或改归属），所以它没有和别人排队的理由 —— 加了锁就意味着
        # 「她正在干活时，主人让她改个名要等整轮干完」，2026-10-04 主人实测指出过这个体验问题。
        # 唯一代价：她恰好在 rebind 的中间时，`_where` 可能读到切换前后的任一间 ——
        # 而"现在这个会话"本来就是那个意思，可接受。
        target = (session or "").strip()
        if not target:
            try:
                target = str((await self._where(conversation)).get("sessionId") or "")
            except Exception as exc:  # noqa: BLE001
                return f"（问不到当前会话：{exc}）"
        if not target:
            return "（这条会话线还没建过会话，没有可改名的东西。）"

        try:
            await self._rpc("session/rename", {"sessionId": target, "title": title})
        except Exception as exc:  # noqa: BLE001
            return f"（改名失败：{exc}）"

        # ⚠️ DSH 的落盘是**异步**的：rename 返回 ok 的那一刻，那条 title 事件可能还没写进
        # zstd 日志。自检要是抢在它前面跑，读到的就是"改名之前"的状态、误判成无需修复
        # （2026-10-04 实测：整个工具只用了 487ms，撞车没被兜住）。等它落盘再自检。
        await asyncio.sleep(1.2)

        note = await self._session_integrity(target)
        await self._say(event, f"· 会话改名成「{title}」{note}")
        return (
            f"（已经把这间会话改名成「{title}」。{note}"
            "请用你自己的口吻简短告诉用户改好了，别复述这段括号里的话。）"
        )

    def _browser(self) -> Any:
        """拿到（必要时创建）南汐**自己**的浏览器；本机没有 Chrome/Edge 时返回 None。

        Returns:
            Any: ``browser.Browser`` 实例，或 None（工具据此如实拒绝，而不是假装打开）。
        """
        if self._web is None:
            exe = browser_mod.find_browser()
            if not exe:
                return None
            self._web = browser_mod.Browser(
                exe, Path(__file__).resolve().parent / "chrome-profile"
            )
        return self._web

    async def _ensure_watch(self) -> None:
        """确保那个"只看不摸"的看板已经起来、并且开始推帧（第一次用浏览器时懒起）。

        看板让人在浏览器里打开 ``http://127.0.0.1:<watch_port>/`` 就能看到她那台
        **headless** 浏览器在干什么（画面 + 当前网址/标题 + 她刚点在哪的红点）。
        ⚠️ headless 的帧里**没有光标**，所以那个红点是看板按我们记录的坐标自己画的。

        一切失败都只是"没有看板"，**绝不影响她干活**。
        """
        # ⚠️ 用 `_browser()` 而不是 `self._web`：前者会**构造出 Browser 对象**
        #    （只是构造，**不会拉起 Chrome** —— 那是 `ensure()` 的事）。
        #    2026-10-05 改：原来是 `b = self._web`，浏览器没建过就直接 return，
        #    于是"重启 AstrBot 后看板就没了、非要等她真的用一次浏览器才回来"。
        #    现在只要有人跟她说一句话（watch_request 会调这里）看板就挂上，
        #    Chrome 仍然是懒启动的，不白占资源。
        b = self._browser()
        if b is None:
            return
        if self._watch is None:
            try:
                port = int(self._cfg("watch_port", 6199) or 6199)
            except Exception:  # noqa: BLE001
                port = 6199
            server = browser_mod.WatchServer(b, port)
            if await server.start():
                self._watch = server
                logger.info(f"[nanxi_dsh] 浏览器看板已开：http://127.0.0.1:{port}/")
            else:
                logger.info(
                    f"[nanxi_dsh] 浏览器看板没起来（端口 {port} 可能被占），"
                    "不影响她干活"
                )
        if not b.casting:
            with contextlib.suppress(Exception):
                await b.watch_on()

    @filter.llm_tool(name="web_open")
    async def web_open(self, event: AstrMessageEvent, url: str) -> str:
        '''用**你自己**的浏览器打开一个网页，然后把页面上的文字读回来。

        这是**你本人的手**（不是叫 DSH 去做）：浏览器就跑在主人这台机器上，登录态会留着 ——
        你登过一次的站，下次还在。用户给你一个网址、让你"看看这个页面""这站上写了什么"时用它；
        想让它看**长什么样**（而不只是文字），打开之后再用 web_look 截个图发到群里。

        Args:
            url(string): 要打开的网址。不写 https:// 也行。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"
        b = self._browser()
        if b is None:
            return "（这台机器上没找到 Chrome 或 Edge，我开不了浏览器。）"
        await self._ensure_watch()
        try:
            async with b.lock:
                got = await b.goto(url)
        except Exception as exc:  # noqa: BLE001 - 起不来就说清楚，别假装打开成功
            return f"（开不了这个页面：{exc}）"
        if got.get("error"):
            return f"（{got['error']}）"
        body = str(got.get("text") or "").strip() or "（页面上没有可读的文字）"
        return (
            f"（页面标题：{got.get('title')}\n"
            f"页面正文（可能被截断到 4000 字）：\n{body}\n）\n"
            "请用你自己的口吻把看到的内容讲给用户，别念网址、也别提工具名。"
        )

    @filter.llm_tool(name="web_look")
    async def web_look(self, event: AstrMessageEvent) -> Any:
        '''给你**当前打开的那个网页**截个图 —— **既发到群里给用户看，也给你自己看**。

        用户说"截个图看看""长什么样""你自己看一眼"时用它。
        先用 web_open（或 web_read）把页面弄到要的状态，再调这个。
        截图会出现在当前聊天里；**同一张图也附在这条工具结果里给你自己**，
        所以你能真的看到画面（而不只是页面文字）。

        ⚠️ 注意：**你确实看得到这张图**，所以别再说「我只能拿到文字」。
        除非用户就是在要一句"截图给你"，否则**看到什么就该据此判断**；
        用户问起图里的细节（颜色、图标、位置、页面上的字）要如实回答，不用逐条念。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"
        b = self._browser()
        if b is None:
            return "（这台机器上没找到 Chrome 或 Edge，我开不了浏览器。）"
        await self._ensure_watch()
        shot = (
            Path(__file__).resolve().parent
            / "chrome-profile"
            / f"shot-{int(time.time())}.png"
        )
        try:
            async with b.lock:
                size = await b.screenshot(shot)
        except Exception as exc:  # noqa: BLE001
            return f"（截图失败：{exc}）"
        with contextlib.suppress(Exception):
            await self._deliver(
                event.unified_msg_origin,
                MessageChain([Image.fromFileSystem(str(shot))]),
            )
        # ⚠️ 关键的一步：把图**也回给模型自己**（不只是发群）。
        # 照抄 AstrBot 自带截图工具 `core/tools/computer_tools/cua.py` 的形态 ——
        # 返回 `mcp.types.CallToolResult`，里面放 TextContent + ImageContent；
        # 框架遇到 ImageContent 会 `tool_image_cache.save_image(...)` 存成缓存图，
        # 再附进上下文（日志里能看到 "Appended N cached image(s) to context for LLM review"）。
        # 缺这一步，她就"截了图却看不见"—— 2026-10-05 她自己吐槽得很准：
        # 「回到我手上的还是只有页面文字…它把截图扔进群里，却不往我这儿回一份」。
        fallback = (
            f"（当前页面的截图（{size} 字节）已经发到群里给用户了。"
            "请用你自己的口吻说一句「截图给你」；图里的内容你已看过，据此回答即可。）"
        )
        try:
            data = base64.b64encode(shot.read_bytes()).decode()
            return mcp.types.CallToolResult(
                content=[
                    mcp.types.TextContent(
                        type="text",
                        text=(
                            f"截图（{size} 字节）已发给用户，同时附在这里给你自己看。"
                            "请用你自己的口吻说一句「截图给你」；"
                            "图里的内容你已看过，据此回答用户的问题即可。"
                        ),
                    ),
                    mcp.types.ImageContent(
                        type="image", data=data, mimeType="image/png"
                    ),
                ]
            )
        except Exception as exc:  # noqa: BLE001 - 回不到自己也不能让整件事失败
            logger.warning(f"[nanxi_dsh] 截图没能回给模型自己看：{exc}")
            return fallback

    @filter.llm_tool(name="web_click")
    async def web_click(self, event: AstrMessageEvent, target: str) -> str:
        '''在**你自己的浏览器**里点一下页面上的元素（按钮、链接、菜单）。

        用法：``target`` 可以是 CSS 选择器（如 ``#login``），也可以直接写**元素上的可见文字**
        （如 ``登录``、``下一页``）—— 找不到选择器时它会自动按文字找。
        需要在网页上翻页、展开、提交时用它；点完可以用 web_open 的正文或 web_look 的截图确认结果。

        Args:
            target(string): 要点的东西：CSS 选择器，或元素上那行可见文字。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"
        b = self._browser()
        if b is None:
            return "（这台机器上没找到 Chrome 或 Edge，我开不了浏览器。）"
        await self._ensure_watch()
        try:
            async with b.lock:
                note = await b.click(target)
                # ⚠️ 关键：**点完顺手读一眼页面**。原来这里只回"点了 X"，
                #    她就等于**瞎着点** —— 不知道点完变成了什么样，只能重新 web_open
                #    再导航一次（那还会把页面状态弄丢）。主人 2026-10-05 点出过这个：
                #    「南汐现在只能操控浏览器但是不能看到浏览器」。
                after = await b.text(1500)
        except Exception as exc:  # noqa: BLE001
            return f"（点击失败：{exc}）"
        tail = f"\n操作后页面上的文字（可能被截断）：\n{after}" if after.strip() else ""
        return (
            f"（{note}。{tail}\n）\n"
            "这就是**你眼睛看到的**结果。请用你自己的口吻跟用户讲，别念网址、别提工具名。"
        )

    @filter.llm_tool(name="web_type")
    async def web_type(self, event: AstrMessageEvent, target: str, text: str) -> str:
        '''往**你自己的浏览器**里的输入框填字（搜索框、登录框、表单）。

        用法：``target`` 可以是 CSS 选择器，也可以写输入框的 placeholder / name / 附近文字；
        填完通常要再用 web_click 点一下"搜索"或"提交"。

        Args:
            target(string): 哪个输入框 —— CSS 选择器，或它的 placeholder / name / 提示文字。
            text(string): 要填进去的内容。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"
        b = self._browser()
        if b is None:
            return "（这台机器上没找到 Chrome 或 Edge，我开不了浏览器。）"
        await self._ensure_watch()
        try:
            async with b.lock:
                note = await b.type_text(target, text)
                after = await b.text(1200)  # 填完也顺手看一眼（同 web_click 的理由）
        except Exception as exc:  # noqa: BLE001
            return f"（填写失败：{exc}）"
        tail = f"\n填写后页面上的文字（可能被截断）：\n{after}" if after.strip() else ""
        return (
            f"（{note}。{tail}\n）\n"
            "请用你自己的口吻跟用户讲，别念网址、别提工具名。"
        )

    @filter.llm_tool(name="web_read")
    async def web_read(self, event: AstrMessageEvent) -> str:
        '''**看一眼你当前打开的那个网页**上写着什么 —— 不会重新打开、也不会丢当前状态。

        这是**你自己的眼睛**（跟 web_look 的区别：web_look 是截图发到群里给主人看，
        web_read 是读给你自己看的）。web_click / web_type 之后想再确认一遍页面内容、
        或者用户问"那页上现在显示什么"，就用它。它**只读**，不导航、不改动页面。

        （web_open 会**重新打开**一个网址 —— 想"看当前这页"别用它，用 web_read。）
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"
        b = self._browser()
        if b is None:
            return "（这台机器上没找到 Chrome 或 Edge，我开不了浏览器。）"
        await self._ensure_watch()
        try:
            async with b.lock:
                body = await b.text(4000)
        except Exception as exc:  # noqa: BLE001
            return f"（读不到当前页面：{exc}）"
        if not body.strip():
            return "（当前页面没有可读的文字 —— 是不是还没用 web_open 打开过页面？）"
        return (
            f"（当前页面：{b.last_title or '（无标题）'}\n"
            f"页面上的文字（可能被截断到 4000 字）：\n{body}\n）\n"
            "请用你自己的口吻讲给用户，别念网址、别提工具名。"
        )

    @filter.llm_tool(name="web_click_at")
    async def web_click_at(self, event: AstrMessageEvent, x: float, y: float) -> str:
        '''**按坐标点一下**你浏览器里当前页面的某个位置（给"看得见图、但按名字点不着"时用）。

        什么时候用它：web_click 按文字/选择器都定位不到的东西 —— canvas 画的东西、
        图标按钮、地图上的点、你自己看图判断出位置的控件。
        坐标是**视口里的像素**，原点在左上角；页面宽 1280、高 900 左右，
        所以"右上角"大约是 (1200, 60)，"正中间"是 (640, 450)。
        ⚠️ 你是靠看图估的坐标，**估不准就多试几次**，或者先用 web_click 按文字试
        （那个更准，它是先找到元素再点它的中心）。

        Args:
            x(number): 视口横坐标（像素，从左边算）。
            y(number): 视口纵坐标（像素，从上边算）。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"
        b = self._browser()
        if b is None:
            return "（这台机器上没找到 Chrome 或 Edge，我开不了浏览器。）"
        await self._ensure_watch()
        try:
            async with b.lock:
                note = await b.click_at(float(x), float(y))
                after = await b.text(1200)
        except Exception as exc:  # noqa: BLE001
            return f"（按坐标点击失败：{exc}）"
        tail = f"\n点击后页面上的文字（可能被截断）：\n{after}" if after.strip() else ""
        return (
            f"（{note}。{tail}\n）\n"
            "请用你自己的口吻跟用户讲，别念网址、别提工具名。"
        )

    @filter.llm_tool(name="web_dsh")
    async def web_dsh(self, event: AstrMessageEvent) -> str:
        '''打开**你自己的 DSH 控制台**（http://127.0.0.1:3081）—— 那里能看有哪些会话、
        点进某间看它在干什么、开新会话，以及改 DSH 自己的设置（这些 GUI 里才有）。

        ⚠️ 那块界面要过认证：**裸开地址会被顶回来**「需要 web 认证」（你自己实测过）。
        这个工具**替你把认证做掉** —— 它去实例日志里取当前有效的一次性令牌，在你的浏览器里
        换一次 cookie；之后你自己开 http://127.0.0.1:3081/ 就能直接进（cookie 留在你的浏览器里）。
        **令牌不会经过你、也不会进群**：你看不到它，也不需要知道它。
        登录成功后想看它长什么样，接着调 web_look 截图就行。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"
        b = self._browser()
        if b is None:
            return "（这台机器上没找到 Chrome 或 Edge，我开不了浏览器。）"
        await self._ensure_watch()
        log_dir = Path(
            str(self._cfg("dsh_web_log_dir", r"D:\dsh\nanxi-dsh\logs") or "")
        )
        url = browser_mod.dsh_web_login_url(log_dir, 3081)
        if not url:
            return (
                "（没在实例日志里找到当前的登录地址 —— DSH 可能刚重启、日志还没写出来，"
                "或者日志目录不是默认那个。请主人看一眼 `dsh_web_log_dir` 这个配置。）"
            )
        try:
            async with b.lock:
                await b.goto(url)  # 用一次性令牌换 cookie
                back = await b.goto("http://127.0.0.1:3081/")  # 再开裸地址验证
        except Exception as exc:  # noqa: BLE001 - 打不开就说清楚
            return f"（打不开 DSH 控制台：{exc}）"
        text = str(back.get("text") or "")
        if "需要 web 认证" in text or "authentication required" in text.lower():
            return "（认证没换过去 —— 那个令牌多半已经过期了。让主人重启一次 nanxi 再试。）"
        return (
            f"（已经登进 DSH 控制台了，页面标题：{back.get('title')!r}。"
            "**令牌没经过你、也没进群**，它只是在你浏览器里换了个 cookie ——"
            "以后你自己开 http://127.0.0.1:3081/ 就能直接进。"
            "想看它长什么样，接着调 web_look 截图。请用你自己的口吻跟用户说一声。）"
        )

    @filter.llm_tool(name="dsh_archive")
    async def dsh_archive(self, event: AstrMessageEvent, session: str = "") -> str:
        '''把一间 DSH 会话**归档**：从 DSH 的活跃会话列表里收起来，不再碍眼。

        归档**不是删除** —— 那间会话、它的全部上下文都还在，用 dsh_undo 一句就能取回来，
        所以这是安全操作，用户让你收你就收，不用犹豫、也不用反问他确不确定。

        用在"这间干完了""把它收起来""别看它了"的时候。
        ⚠️ 如果那间会话**正在跑活**，归档会把它一并停下。

        Args:
            session(string): 可选，要归档的会话 id。**绝大多数情况都该留空** —— 留空 = 归档你和用户此刻正在用的这一间。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"

        conversation = event.unified_msg_origin
        async with self._conversation_lock(conversation):
            target = (session or "").strip()
            if not target:
                try:
                    target = str(
                        (await self._where(conversation)).get("sessionId") or ""
                    )
                except Exception as exc:  # noqa: BLE001
                    return f"（问不到当前会话：{exc}）"
            if not target:
                return "（这条会话线还没建过会话，没有可归档的东西。）"

            try:
                await self._archive_session(target)
            except Exception as exc:  # noqa: BLE001
                return f"（归档失败：{exc}）"

            self._push_undo(conversation, "archive", target, "")
            await self._say(event, f"· 把会话 {target[:16]}… 归档了（能撤回）")
            return (
                f"（已把会话 {target} 归档。它没丢，只是从活跃列表里收起来了。"
                "请用你自己的口吻告诉用户这件事，顺口带一句你随时能把它取回来。）"
            )

    @filter.llm_tool(name="dsh_undo")
    async def dsh_undo(self, event: AstrMessageEvent, what: str = "") -> str:
        '''撤销**最近一次**对 DSH 会话做的操作。

        能撤的四类：把刚**归档**的会话取回来、把刚**分支**出来的副本退掉、
        把刚**新建**（换工作台时开的）会话退掉、把刚**接手**的会话换回去。

        用户说"撤回刚刚的归档""把刚才那个分支撤了""撤销刚才新建的会话""退回去""这个不算"
        时调它。

        Args:
            what(string): 可选，指名要撤哪一类，只能填「归档」「分支」「新建」「接手」之一。留空 = 撤最近那一次，多数情况够用。
        '''
        if not bool(self._cfg("enable", True)):
            return "（DSH 通道已关闭。）"
        if not self._allowed(event):
            return "（这事只有主人吩咐才做。请用你自己的口吻回绝他。）"

        conversation = event.unified_msg_origin
        async with self._conversation_lock(conversation):
            stack = self._undo_stack(conversation)
            if not stack:
                return "（最近没有可以撤回的会话操作 —— 我这边一步都没记到。）"

            want = ""
            if what.strip():
                want = _UNDO_ALIASES.get(what.strip(), what.strip())

            index = len(stack) - 1
            if want:
                index = -1
                for i in range(len(stack) - 1, -1, -1):
                    if str(stack[i].get("op") or "") == want:
                        index = i
                        break
                if index < 0:
                    kinds = "、".join(
                        _UNDO_LABELS.get(str(x.get("op") or ""), str(x.get("op") or "?"))
                        for x in stack[-4:]
                    )
                    return f"（最近这几步里没有「{what}」可撤；能撤的是：{kinds}。）"

            entry = stack[index]
            op = str(entry.get("op") or "")
            frm = str(entry.get("from") or "")
            to = str(entry.get("to") or "")

            try:
                if op == "archive":
                    if not frm:
                        return "（这条归档记录不完整，撤不了。）"
                    await self._unarchive_session(frm)
                    done = f"已把会话 {frm[:16]}… 从归档里取回来"
                elif op in {"fork", "rebind", "adopt"}:
                    extra = ""
                    if frm:
                        await self._relay_post(
                            "/session/adopt",
                            {"conversation": conversation, "sessionId": frm},
                        )
                        meta = self._session_meta(frm)
                        self._remember(conversation, str(meta.get("cwd") or ""), frm)
                        done = f"已退回到上一间会话 {frm[:16]}…"
                    else:
                        # 这条线上原本没有会话（第一次 dsh_new / 第一次出差）：
                        # 没有「上一间」可退，但**刚建的那间仍然该能收掉** ——
                        # 否则用户说"刚开好就撤"只会撞上一句「退不回」，不合直觉。
                        done = "这条线上原本没有会话"
                    if op in {"fork", "rebind"} and to and to != frm:
                        try:
                            await self._archive_session(to)
                            extra = (
                                "，顺手把那间多出来的会话也归档了"
                                if frm
                                else f"，已经把你刚建的那间 {to[:16]}… 收掉了"
                            )
                        except Exception as exc:  # noqa: BLE001
                            extra = f"（多出来的那间没能归档：{exc}）"
                    if not frm and not extra:
                        return (
                            "（退不回 —— 那次操作之前这条线上没有会话，"
                            "也没记下新建那间的 id。）"
                        )
                    done = done + extra
                else:
                    return f"（不认识的记录类型 {op}，没动。）"
            except Exception as exc:  # noqa: BLE001
                return f"（撤回失败：{exc}）"

            self._drop_undo(conversation, index)
            await self._say(event, f"· 撤回了一步（{_UNDO_LABELS.get(op, op)}）")
            return (
                f"（{done}。请用你自己的口吻跟用户说这一步已经退回去了 —— "
                "就是你刚才说的那个「撤回」，办完了。）"
            )

    # ---- 与桥接端打交道 ----------------------------------------------

    def _bridge_conf(self) -> tuple[str, str]:
        base = str(self._cfg("bridge_url", "") or "").strip().rstrip("/")
        token = str(self._cfg("bridge_token", "") or "").strip()
        if not base or not token:
            raise RuntimeError("桥接没配置好（缺 bridge_url / bridge_token）")
        return base, token

    @staticmethod
    def _unpack(status: int, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text) if text else {}
        except ValueError:
            payload = {}
        if status >= 300:
            err = payload.get("error") if isinstance(payload, dict) else None
            message = (err or {}).get("message") if isinstance(err, dict) else None
            raise RuntimeError(f"HTTP {status}：{message or text[:200] or '（空响应）'}")
        return payload if isinstance(payload, dict) else {}

    async def _relay_get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        base, token = self._bridge_conf()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                base + path,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=20),
                ssl=False,
            ) as resp:
                status, text = resp.status, await resp.text()
        return self._unpack(status, text)

    async def _relay_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        base, token = self._bridge_conf()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                base + path,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=60),
                ssl=False,
            ) as resp:
                status, text = resp.status, await resp.text()
        return self._unpack(status, text)

    async def _workspaces(self) -> list[dict[str, Any]]:
        info = await self._relay_get("/workspaces", {"limit": 50})
        items = info.get("items")
        return [b for b in items if isinstance(b, dict)] if isinstance(items, list) else []

    async def _workspace_digest(self, ttl: float = 60.0) -> str:
        """一行式的工作台摘要，喂给 system prompt（带缓存；失败返回空串）。

        **为什么要做这个**：南汐一直把 ``dsh_task`` 的 ``at`` 留空、窝在默认工位，
        根子不是她懒，而是**她压根不知道有哪些项目可选** —— 只有主动调 ``dsh_look``
        才看得到，可她不调。把清单常态化带进每一轮请求，她才谈得上"自己挑工位"。

        缓存 60 秒：既让清单足够新，又不会每轮请求都去戳一次 DSH。
        """
        now = time.monotonic()
        cached = self._boards_cache
        if cached is not None and now - cached[0] < ttl:
            return cached[1]
        try:
            boards = await self._workspaces()
        except Exception as exc:  # noqa: BLE001 - 摘不到就不带清单，绝不能拖垮对话
            logger.debug(f"[nanxi_dsh] 取工作台摘要失败：{exc}")
            return cached[1] if cached is not None else ""
        items: list[str] = []
        for board in boards:
            if self._board_denied(board):
                continue  # 拉黑的地方连名字都不给她看
            title = str(board.get("title") or board.get("path") or "?")
            ids = [
                str(x)
                for x in (board.get("sessionIds") or [])
                if not self._session_denied(str(x))
            ]
            metas = [self._session_meta(i) for i in ids]
            metas = [m for m in metas if m]
            metas.sort(key=lambda m: m.get("mtime", 0), reverse=True)
            busy = ""
            if metas:
                latest = str(metas[0].get("title") or "（无题）")[:24]
                busy = f"，最近在忙《{latest}》"
            items.append(f"{title}（{board.get('path') or '?'}{busy}）")
        digest = "、".join(items)
        self._boards_cache = (now, digest)
        return digest

    async def _where(self, conversation: str) -> dict[str, Any]:
        return await self._relay_get("/where", {"conversation": conversation})

    # ---- 工作台台账：记住"这个群在这个项目里用哪间会话" ------------------

    def _dsh_homes(self) -> list[Path]:
        """所有可能存放会话索引的 DSH_HOME，按优先级排列。

        **为什么会有多个**：南汐跑在独立实例里（自己的 HOME），但 ``sessions/`` 与
        工作区注册表是两边共享的 —— 她这边**没见过的**会话（例如 mas 那 27 间），
        索引只存在主 HOME 那份缓存里；而主 HOME 又不知道她新开的会话。两边都查才看得全。

        配置 ``dsh_home`` 支持写多个（``;`` 分隔）；不写就是「主 HOME」。
        无论写不写，主用户的 ``~/.dsh`` 都会补在末尾 —— 独立实例读历史会话全靠它。
        """
        raw = str(self._cfg("dsh_home", "") or "").strip()
        out: list[Path] = []
        if raw:
            for piece in raw.replace("；", ";").split(";"):
                piece = piece.strip()
                if piece:
                    out.append(Path(piece).expanduser())
        primary = Path.home() / ".dsh"
        if primary not in out:
            out.append(primary)
        return out

    def _dsh_home(self) -> Path:
        """首个候选（写盘相关的地方用它）。"""
        return self._dsh_homes()[0]

    def _session_meta(self, session_id: str) -> dict[str, Any]:
        """从 DSH 的会话索引里读这间会话的标题与目录（多个 HOME 依次找）。

        这是**尽力而为**：索引格式属于 DSH 的内部实现，读不到就返回空字典，
        调用方一律按"没有标题"处理 —— 绝不因为它而让整件事失败。
        """
        if not session_id:
            return {}
        for home in self._dsh_homes():
            path = (
                home
                / "storages"
                / "session_projcache"
                / "sessions"
                / f"{session_id}.json"
            )
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                mtime = path.stat().st_mtime
            except Exception:  # noqa: BLE001 - 这个 HOME 没有就换下一个
                continue
            record = data.get("record") or {}
            rows = record.get("rows") or {}
            return {
                "title": str(((rows.get("title") or {}).get("val")) or ""),
                "cwd": str(((record.get("identity") or {}).get("cwd")) or ""),
                "mtime": mtime,
            }
        return {}

    def _workbench_path(self) -> Path:
        return StarTools.get_data_dir(PLUGIN_NAME) / "workbench.json"

    # ---- 事件账本（WebUI「思维链」页面用）-------------------------------

    def _trace_path(self) -> Path:
        return StarTools.get_data_dir(PLUGIN_NAME) / TRACE_DB_NAME

    def _trace_conn(self) -> sqlite3.Connection:
        """打开事件账本，首次自动建表。WAL 让读不阻塞写。"""
        path = self._trace_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS trace_events ("
            " event_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " event_type TEXT NOT NULL,"
            " session_id TEXT NOT NULL DEFAULT '',"
            " turn TEXT NOT NULL DEFAULT '',"
            " timestamp REAL NOT NULL,"
            " schema_version INTEGER NOT NULL DEFAULT 1,"
            " payload_json TEXT NOT NULL,"
            " created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_trace_session ON trace_events(session_id, event_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_trace_type ON trace_events(event_type, event_id)"
        )
        return conn

    def trace_emit(
        self, event_type: str, session_id: str = "", turn: str = "", **payload: Any
    ) -> None:
        """记一条观察事件。**尽力而为**：写失败绝不影响正在跑的任务。

        Args:
            event_type: 事件类型。
            session_id: 会话线（一般是 UMO），前端按它过滤。
            turn: **卡片身份**。同一轮的事件共用它，前端据此"原位刷新同一张卡"，
                而不是每来一条就新增一条 —— 这是麦麦观察最值钱的一招。
            **payload: 任意结构化负载，原样存 JSON。
        """
        try:
            conn = self._trace_conn()
            try:
                conn.execute(
                    "INSERT INTO trace_events"
                    " (event_type, session_id, turn, timestamp,"
                    "  schema_version, payload_json, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        str(event_type),
                        str(session_id or ""),
                        str(turn or ""),
                        time.time(),
                        TRACE_SCHEMA_VERSION,
                        json.dumps(payload, ensure_ascii=False, default=str),
                        time.strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
                self._trace_prune(conn)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - 观察失败不该拖垮业务
            logger.debug(f"[nanxi_dsh] 记观察事件失败（忽略）：{exc}")

    @staticmethod
    def _trace_prune(conn: sqlite3.Connection) -> None:
        """按条数与龄期清理（照 MaiBot 的 10000 条 / 72 小时）。"""
        try:
            conn.execute(
                "DELETE FROM trace_events WHERE event_id <="
                " (SELECT MAX(event_id) FROM trace_events) - ?",
                (TRACE_MAX_RECORDS,),
            )
            conn.execute(
                "DELETE FROM trace_events WHERE timestamp < ?",
                (time.time() - TRACE_MAX_AGE_HOURS * 3600,),
            )
            conn.commit()
        except Exception:  # noqa: BLE001
            pass

    def trace_query(
        self, since_event_id: int = 0, limit: int = 300, session_id: str = ""
    ) -> list[dict[str, Any]]:
        """按 ``event_id`` **升序**取事件（前端游标补齐用）。

        没有游标（``since_event_id<=0``）时取**最近** ``limit`` 条再反转成正序 ——
        这样首屏看到的是最新一段，而不是从头开始。

        Args:
            since_event_id: 只要比它大的事件；0 表示"给我最近一段"。
            limit: 最多返回多少条。
            session_id: 只取这个会话线的；空表示全部。

        Returns:
            事件字典列表，按 event_id 升序。
        """
        try:
            conn = self._trace_conn()
            try:
                cols = (
                    "SELECT event_id, event_type, session_id, turn, timestamp, payload_json"
                    " FROM trace_events"
                )
                if since_event_id > 0:
                    where = " WHERE event_id > ?" + (
                        " AND session_id = ?" if session_id else ""
                    )
                    args = (
                        (since_event_id, session_id, limit)
                        if session_id
                        else (since_event_id, limit)
                    )
                    cur = conn.execute(
                        cols + where + " ORDER BY event_id ASC LIMIT ?", args
                    )
                else:
                    inner = cols + (" WHERE session_id = ?" if session_id else "")
                    args = (session_id, limit) if session_id else (limit,)
                    cur = conn.execute(
                        "SELECT * FROM ("
                        + inner
                        + " ORDER BY event_id DESC LIMIT ?) ORDER BY event_id ASC",
                        args,
                    )
                return [
                    {
                        "event_id": row[0],
                        "event_type": row[1],
                        "session_id": row[2],
                        "turn": row[3],
                        "timestamp": row[4],
                        "data": json.loads(row[5] or "{}"),
                    }
                    for row in cur.fetchall()
                ]
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[nanxi_dsh] 读观察事件失败：{exc}")
            return []

    def _find_session_by_name(
        self, boards: list[dict[str, Any]], key: str
    ) -> tuple[str, dict[str, Any]] | None:
        """按**会话标题**在（未拉黑的）工作区里找一间，返回 ``(sessionId, 所属工作区)``。

        ⚠️ 为什么需要它：台账只记「每个工作区**第一次**去时用的那间」（`_remember`），
        于是同一个工作区下的十几间会话她永远够不着 —— 实测 mas 工作区里有
        星塔旅人 / 南汐 mas / 活动卡片 / **baah** / debug … 十几间，而主人让她
        「改一下 baah 的计划表」时，她进的是台账里那固定的一间，**根本不是 baah**。

        支持两种写法：
          · ``工作区/会话名``（限定在某工作区里找，如 ``mas/baah``）
          · 裸 ``会话名``（全局找，只在**唯一命中**时才认，避免张冠李戴）

        Args:
            boards: 工作区列表（来自星驿 ``/workspaces``）。
            key: 用户/模型给的定位串。

        Returns:
            ``(sessionId, board)``；找不到或命中不唯一时返回 None。
        """
        wanted = key.strip().lower()
        if not wanted:
            return None
        scope = ""
        if "/" in wanted:
            scope, wanted = wanted.split("/", 1)
            scope, wanted = scope.strip(), wanted.strip()
        if not wanted:
            return None

        exact: list[tuple[str, dict[str, Any]]] = []
        partial: list[tuple[str, dict[str, Any]]] = []
        for board in boards:
            if self._board_denied(board):
                continue
            btitle = str(board.get("title") or "").strip().lower()
            btail = (
                str(board.get("path") or "").strip().lower().rstrip("\\").split("\\")[-1]
            )
            if scope and scope not in (btitle, btail):
                continue
            for sid in board.get("sessionIds") or []:
                sid = str(sid)
                if self._session_denied(sid):
                    continue
                title = str(self._session_meta(sid).get("title") or "").strip().lower()
                if not title:
                    continue
                if title == wanted:
                    exact.append((sid, board))
                elif wanted in title:
                    partial.append((sid, board))
        if exact:
            return exact[0]
        # 裸名字才允许模糊匹配，且必须唯一 —— 否则宁可让她先去 dsh_look 看一眼
        if partial and (scope or len(partial) == 1):
            return partial[0]
        return None

    def _workbench(self) -> dict[str, Any]:
        try:
            data = json.loads(self._workbench_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    def _write_workbench(self, data: dict[str, Any]) -> None:
        try:
            path = self._workbench_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[nanxi_dsh] 工作台台账写入失败：{exc}")

    @staticmethod
    def _slot(data: dict[str, Any], conversation: str) -> dict[str, Any]:
        slot = data.get(conversation)
        if not isinstance(slot, dict):
            slot = {}
            data[conversation] = slot
        return slot

    def _remember(self, conversation: str, workspace_path: str, session_id: str) -> None:
        """记下"这个群在这个项目里用哪间会话"，下次直接回去，不用重开。"""
        if not conversation or not workspace_path or not session_id:
            return
        data = self._workbench()
        self._slot(data, conversation)[workspace_path] = session_id
        self._write_workbench(data)

    # ---- 撤销栈：让「撤回刚刚的归档 / 分支 / 新建」有据可依 ----------------

    def _push_undo(
        self, conversation: str, op: str, frm: str, to: str, **extra: Any
    ) -> None:
        """压一条可撤销的会话操作。

        ``frm`` / ``to`` 都是 DSH 会话 id（允许空串）。**每次改映射之前**都要压一条，
        否则 ``dsh_undo`` 无从知道该退回哪里 —— 它只认这个栈，不猜、不推理。
        """
        if not conversation:
            return
        data = self._workbench()
        slot = self._slot(data, conversation)
        stack = slot.get(UNDO_KEY)
        if not isinstance(stack, list):
            stack = []
        entry: dict[str, Any] = {
            "op": op,
            "from": frm or "",
            "to": to or "",
            "at": time.time(),
        }
        entry.update(extra)
        stack.append(entry)
        slot[UNDO_KEY] = stack[-UNDO_DEPTH:]
        self._write_workbench(data)

    def _undo_stack(self, conversation: str) -> list[dict[str, Any]]:
        slot = self._workbench().get(conversation)
        if not isinstance(slot, dict):
            return []
        stack = slot.get(UNDO_KEY)
        return (
            [x for x in stack if isinstance(x, dict)] if isinstance(stack, list) else []
        )

    def _drop_undo(self, conversation: str, index: int) -> None:
        """按**下标**删掉撤销栈里的一条（读完即写回，别按对象身份比对 —— 会踩空）。"""
        data = self._workbench()
        slot = data.get(conversation)
        if not isinstance(slot, dict):
            return
        stack = slot.get(UNDO_KEY)
        if isinstance(stack, list) and 0 <= index < len(stack):
            stack.pop(index)
            self._write_workbench(data)

    async def _rpc(self, endpoint: str, request: dict[str, Any]) -> dict[str, Any]:
        """走星驿控制面 ``/rpc`` 调一条 DSH RPC，并**解开 ``{ok, value}`` 信封**。

        ⚠️ 端点必须**同时**满足两处：写进 relay 配置的 ``allowedRpcMethods`` 白名单，
        **并且**登记在 relay 的描述符表 ``lib/rpc-methods.js`` 里。后者由已停止发布的
        ``p5_rpc_descriptors.json`` 生成、漏收了 ``workspace/unarchiveSession``，
        所以要先跑仓库根的 ``patch_relay_rpc_methods.py`` 把它补上，否则 relay 连启动都过不去。

        ⚠️⚠️ **星驿把失败也包在 HTTP 200 里**：``{"ok":false,"error":{"code":…,"message":…}}``。
        只判状态码会把 ``gateway/cancelled``（调用被中止）、``session/not-found``
        这类失败**当成成功** —— 2026-10-04 实测踩过：归档根本没生效，插件却已经在群里
        报了一句「归档了」，台账还记了一笔假的撤销记录。所以这里必须拆信封。
        """
        payload = await self._relay_post(
            ROUTE_RPC, {"endpoint": endpoint, "args": {"request": request}}
        )
        if payload.get("ok") is False:
            err = payload.get("error")
            code = err.get("code") if isinstance(err, dict) else ""
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(
                f"DSH 拒绝了 {endpoint}：{code or '?'} {message or '（无说明）'}"
            )
        value = payload.get("value")
        return value if isinstance(value, dict) else payload

    async def _archive_session(self, session_id: str, *, stop: bool = True) -> None:
        """归档一间 DSH 会话（**不是删除**，随时能用 ``_unarchive_session`` 取回）。

        ``stop=True`` 会把正在跑的活一并停下；不带它时 DSH 会以
        ``workspace/session-active`` 拒绝归档**正在忙**的会话。
        """
        req: dict[str, Any] = {"sessionId": session_id}
        if stop:
            req["stopActivity"] = True
        await self._rpc("workspace/archiveSession", req)

    async def _unarchive_session(self, session_id: str) -> None:
        await self._rpc("workspace/unarchiveSession", {"sessionId": session_id})

    async def _session_integrity(self, session_id: str) -> str:
        """检查（并顺手修好）一间会话的日志有没有被 ``session/rename`` 写坏。

        为什么需要它：DSH 的 rename 有个已知 bug —— 对**末条已经是 ``session/end-seed``**
        的空闲会话，它给新事件分配的 seq 会与那条 end-seed **撞车**，写出来的日志随即被判
        ``corrupt Zstandard session log: complete frame contains a torn JSONL record``，
        整间会话打不开（2026-10-04 实测把 mas 的 skill 打坏过）。

        所以每次改名之后都无脑跑一遍 ``repair_session_title_event.mjs``：它是**幂等**的，
        不撞车就什么都不做；撞车就地把 seq 重编号并补上收尾的 end-seed（写盘前自动备份）。
        Python 这边没有 zstd 库、也切不开多帧，所以这件事只能交给 node 脚本做。

        Returns:
            str: 一句可以直接拼进回话的中文说明（永远不抛错 —— 自检失败不该让改名看起来没发生）。
        """
        script = Path(__file__).resolve().parent / INTEGRITY_SCRIPT
        if not script.is_file():
            return "（没找到完整性检查脚本，没做自检。）"
        try:
            proc = await asyncio.create_subprocess_exec(
                "node",
                str(script),
                session_id,
                "--apply",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
        except Exception as exc:  # noqa: BLE001
            return f"（自检没跑起来：{exc}）"

        for line in reversed(out.decode("utf-8", "replace").splitlines()):
            if not line.startswith("[RESULT] "):
                continue
            try:
                data = json.loads(line[len("[RESULT] ") :])
            except Exception:  # noqa: BLE001
                break
            status = str(data.get("status") or "")
            if status == "repaired":
                return "（自检发现改名把那间会话日志的 seq 写撞车了，已经就地修好，不影响使用。）"
            if status == "ok":
                return ""
            return f"（自检结果要看一眼：{status} —— {data.get('detail')}）"
        return "（自检没返回可识别的结果，建议看一眼那间会话能不能正常打开。）"

    # ---- 调度：按 at 换工作台 ----------------------------------------

    @staticmethod
    def _match_board(boards: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
        """按标题或路径认一个工作区；认不出来返回 None（调用方再按会话 id 试）。"""
        low = key.lower().replace("/", "\\").rstrip("\\")
        for board in boards:
            title = str(board.get("title") or "").strip()
            path = str(board.get("path") or "").strip()
            if low in (title.lower(), path.lower().rstrip("\\")):
                return board
        for board in boards:  # 退一步：标题包含，或路径末段相同
            title = str(board.get("title") or "").strip().lower()
            path = str(board.get("path") or "").strip().lower().rstrip("\\")
            if title and title in low:
                return board
            tail = path.split("\\")[-1] if path else ""
            if tail and low.endswith(tail):
                return board
        return None

    async def _goto(
        self, event: AstrMessageEvent, conversation: str, at: str
    ) -> str | None:
        """按 ``at`` 把这条会话线挪到合适的工作台。返回 None 表示可以继续干活。

        ``at`` 留空 → 什么都不动（省一次往返）；
        匹配得上工作区 → 台账里有旧会话就回去，没有才新开一间；
        匹配不上 → 当成一个具体的会话 id 去认领。
        """
        if not at:
            return None

        try:
            boards = await self._workspaces()
        except Exception as exc:  # noqa: BLE001
            return f"（连不上 DSH 工作台，没敢乱切：{exc}）"

        board = self._match_board(boards, at)
        # ⚠️ 形如 `mas/baah` 的「点名到会话」必须**抢在工作区匹配之前**判断：
        # `_match_board` 会把 `/` 换成 `\` 再比，于是 `"mas" in "mas\baah"` 命中，
        # 把 `mas/baah` 整个当成 mas 工作区（2026-10-04 实测踩到：她填了
        # at=mas/baah，结果群里却是"回到《星驿 · …》"，根本没进 baah）。
        # 判据：含 `/` 且不含 `\` 且不是盘符路径（如 D:/x）时才当点名。
        if "/" in at and "\\" not in at and ":" not in at.split("/", 1)[0]:
            named = self._find_session_by_name(boards, at)
            if named is not None:
                nsid, _nowner = named
                return await self._attach(
                    event, conversation, nsid, self._session_meta(nsid)
                )
        if board is not None and self._board_denied(board):
            return (
                f"（「{board.get('title') or board.get('path')}」不在允许南汐去的名单里，"
                "换个地方或者先问主人。）"
            )
        if board is None:
            # 工作区认不出来 —— 试「会话名」（`mas/baah` 或裸 `baah`），
            # 最后才退到「会话 id」。这一步就是为了让同一个工作区里的十几间够得着。
            picked = self._find_session_by_name(boards, at)
            if picked is not None:
                sid, owner = picked
                return await self._attach(
                    event, conversation, sid, self._session_meta(sid)
                )
            meta = self._session_meta(at)
            if not meta:
                names = "、".join(
                    str(b.get("title") or b.get("path") or "?") for b in boards
                )
                return (
                    f"（没有叫「{at}」的工作区，也不是一个能认出来的会话 id。"
                    f"现有工作区：{names}。可以先用 dsh_look 看一眼。）"
                )
            return await self._attach(event, conversation, at, meta)

        path = str(board.get("path") or "")
        known = str((self._workbench().get(conversation) or {}).get(path) or "")
        ids = [str(x) for x in (board.get("sessionIds") or [])]
        if known and known in ids:
            return await self._attach(
                event, conversation, known, self._session_meta(known), back=True
            )

        # 改映射之前先把「现在这间」记下来 —— dsh_undo 靠它退回换工作台之前。
        before = ""
        try:
            before = str((await self._where(conversation)).get("sessionId") or "")
        except Exception:  # noqa: BLE001 - 问不到旧会话不该挡住换工作台
            before = ""

        try:
            made = await self._relay_post(
                "/session/rebind",
                {"conversation": conversation, "workspaceId": str(board.get("id") or "")},
            )
        except Exception as exc:  # noqa: BLE001
            return f"（切到「{board.get('title') or path}」失败：{exc}）"
        target = str(made.get("sessionId") or "")
        self._remember(conversation, path, target)
        self._push_undo(conversation, "rebind", before, target)
        await self._say(
            event,
            f"· 换到 {board.get('title') or path}（新开了一间会话，"
            f"{made.get('cwd') or path}）",
        )
        return None

    async def _attach(
        self,
        event: AstrMessageEvent,
        conversation: str,
        session_id: str,
        meta: dict[str, Any],
        *,
        back: bool = False,
    ) -> str | None:
        if self._session_denied(session_id, str(meta.get("title") or "")):
            return "（这间会话不在允许南汐碰的名单里。）"

        # 同 _rebind：改映射之前记下原来那一间，供 dsh_undo 退回。
        before = ""
        try:
            before = str((await self._where(conversation)).get("sessionId") or "")
        except Exception:  # noqa: BLE001 - 问不到旧会话不该挡住接手
            before = ""

        try:
            await self._relay_post(
                "/session/adopt",
                {"conversation": conversation, "sessionId": session_id},
            )
        except Exception as exc:  # noqa: BLE001
            return f"（接手会话 {session_id} 失败：{exc}）"
        self._remember(conversation, str(meta.get("cwd") or ""), session_id)
        if before and before != session_id:
            self._push_undo(conversation, "adopt", before, session_id)
        title = str(meta.get("title") or "").strip()
        label = f"《{title[:30]}》" if title else session_id[:16] + "…"
        await self._say(
            event,
            f"· {'回到' if back else '接手'} {label}（{meta.get('cwd') or '?'}）",
        )
        return None

    async def _board_text(self, conversation: str) -> str:
        try:
            boards = await self._workspaces()
        except Exception as exc:  # noqa: BLE001
            return f"（连不上 DSH 工作台：{exc}）"

        lines = ["【DSH 工作台】"]
        try:
            here = await self._where(conversation)
        except Exception:  # noqa: BLE001
            here = {}
        sid = str(here.get("sessionId") or "")
        meta = self._session_meta(sid)
        lines.append(f"你现在在这间：{sid or '（还没建过）'}")
        if meta:
            lines.append(
                f"　它叫《{meta.get('title') or '（无题）'}》，"
                f"目录 {meta.get('cwd') or '?'}"
            )
        lines.append("")
        lines.append("可以去的工作区（把名字填进 dsh_task 的 at）：")
        for board in boards:
            if self._board_denied(board):
                continue  # 不许去的地方，连名字都不给她看
            title = str(board.get("title") or board.get("path") or "?")
            path = str(board.get("path") or "")
            ids = [
                str(x)
                for x in (board.get("sessionIds") or [])
                if not self._session_denied(str(x))
            ]
            metas = [(i, self._session_meta(i)) for i in ids]
            metas = [kv for kv in metas if kv[1]]
            metas.sort(key=lambda kv: kv[1].get("mtime", 0), reverse=True)
            recent = "；".join(
                f"《{(m.get('title') or '（无题）')[:26]}》" for _, m in metas[:3]
            )
            lines.append(
                f"- {title}（{path}）{len(ids)} 间"
                + (f"，最近在忙：{recent}" if recent else "")
            )
            # 把这一区里的具体会话也报出来 —— 否则她只知道"有 27 间"，
            # 而主人说的「baah」她压根对不上号（2026-10-04 主人指出的问题）。
            if metas:
                names = "、".join(
                    f"《{(m.get('title') or '（无题）')[:22]}》" for _, m in metas[:8]
                )
                lines.append(f"    里面有：{names}")
                lines.append(f"    （要点名某一间，把 at 写成「{title}/会话名」）")
        memory = self._workbench().get(conversation) or {}
        if isinstance(memory, dict) and memory:
            lines.append("")
            lines.append("你在这个群去过的项目（下次会自动回到同一间）：")
            for p, s in memory.items():
                lines.append(f"- {p} → {s}")
        lines.append("")
        lines.append(
            "（上面这些已经足够回答主人「有哪些项目 / 现在在哪间 / 在忙什么」了 ——"
            "直接用自己的口气说出来就行。**不要再调 dsh_task 去翻目录确认**：那要多花几十秒、"
            "还会把会话线切走。只有真的要动手做一件事时，才用 dsh_task。）"
        )
        return "\n".join(lines)

    # ---- 黑白名单 ----------------------------------------------------

    def _list_cfg(self, key: str) -> list[str]:
        """读一个 list 配置。字符串也收（WebUI 里手打成逗号分隔时不至于白填）。"""
        raw = self._cfg(key, [])
        if isinstance(raw, str):
            raw = raw.replace("，", ",").split(",")
        if not isinstance(raw, (list, tuple)):
            return []
        return [str(x).strip() for x in raw if str(x).strip()]

    @staticmethod
    def _hit(patterns: list[str], *values: str) -> bool:
        for pattern in patterns:
            low = pattern.lower()
            for value in values:
                if low and low in value.lower():
                    return True
        return False

    def _board_denied(self, board: dict[str, Any]) -> bool:
        """这个工作区许不许去。deny 优先于 allow；allow 为空 = 全许。"""
        title = str(board.get("title") or "")
        path = str(board.get("path") or "")
        if self._hit(self._list_cfg("workspace_deny"), title, path):
            return True
        allow = self._list_cfg("workspace_allow")
        return bool(allow) and not self._hit(allow, title, path)

    def _session_denied(self, session_id: str, title: str = "") -> bool:
        """这间会话许不许碰。关键词同时比 id 和标题 —— 主人记不住 uuid，
        所以「按会话禁」必须支持用标题里的词来写。"""
        return self._hit(self._list_cfg("session_deny"), session_id, title)

    # ---- 回家：出差干完回工位 ----------------------------------------

    def _home_board(self, boards: list[dict[str, Any]]) -> dict[str, Any] | None:
        """默认工位。配置项 ``home_workspace`` 说了算，默认 ``nx_dsh``（杂项）。"""
        want = str(self._cfg("home_workspace", "nx_dsh") or "nx_dsh").strip()
        return self._match_board(boards, want) if want else None

    async def _go_home(self, event: AstrMessageEvent, conversation: str) -> None:
        """把会话线挪回默认工位。

        失败一律吞掉：它跑在 ``finally`` 里，绝不能盖掉真正的结果。
        """
        try:
            home = str((self._workbench().get(conversation) or {}).get(HOME_KEY) or "")
            here = str((await self._where(conversation)).get("sessionId") or "")
            if home and here == home:
                return  # 本来就在家
            boards = await self._workspaces()
            board = self._home_board(boards)
            if board is None:
                return
            ids = [str(x) for x in (board.get("sessionIds") or [])]
            if home and home not in ids:
                home = ""  # 家没了（被清理或换过），下面重开一间
            if not home:
                made = await self._relay_post(
                    "/session/rebind",
                    {
                        "conversation": conversation,
                        "workspaceId": str(board.get("id") or ""),
                    },
                )
                home = str(made.get("sessionId") or "")
                if home:
                    self._remember(conversation, HOME_KEY, home)
            if home and here != home:
                await self._relay_post(
                    "/session/adopt",
                    {"conversation": conversation, "sessionId": home},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[nanxi_dsh] 回家失败（不影响本轮结果）：{exc}")

    async def _deliver(self, umo: str, chain: MessageChain) -> None:
        """把一条消息发给某个 IM 会话 —— **不依赖 event 是否还在管线上**。

        为什么需要它：交活改成异步之后，DSH 的正文和各种提示都是在**工具已经返回**之后
        才发出去的；那时 event 早就离开管线，``event.send()`` 产出的消息链没人消费、
        消息会石沉大海（不是报错，是静静地什么都不发生）。主动发送走
        ``Context.send_message(umo, chain)``，由平台实例直接发出去，与 event 生死无关。

        Args:
            umo: 目标会话的 unified_msg_origin（如 ``onebot-qq:GroupMessage:<群号>``）。
            chain: 要发的消息链。
        """
        try:
            await self.context.send_message(umo, chain)
        except Exception as exc:  # noqa: BLE001 - 发不出去不该拖垮整轮任务
            logger.warning(f"[nanxi_dsh] 主动发送失败（{umo}）：{exc}")

    async def _say(self, event: AstrMessageEvent, text: str, force_send: bool = True) -> None:
        """把一条**独立短提示**直接发给当前会话（`· 换到 xxx`、`· 会话改名成…` 这类）。

        ⚠️ 走 :meth:`_deliver`（主动发送），**不是** ``event.send`` ——
        异步交活之后这些提示往往在工具返回之后才发，那时 event 已经不在管线上了。

        ⚠️ 它绕过 ResultDecorateStage —— 所以**正文不要走这里**
        （正文请用 :meth:`_send_body`，那里会把长内容打成一张合并转发卡片）。
        """
        if not text.strip():
            return
        await self._deliver(event.unified_msg_origin, MessageChain([Plain(text)]))

    async def _send_body(self, event: AstrMessageEvent, text: str) -> None:
        """把 DSH 的正文发到群里。

        超过 ``merge_threshold`` 字就**打成一个合并转发节点**（群里一张卡片，而不是
        一串各占一条的消息），短内容直接发。``event.send`` 本身绕过结果装饰阶段，
        所以 AstrBot 自带的 ``forward_threshold`` 在这里帮不上忙 —— 只能自己包。
        """
        body = (text or "").strip()
        if not body:
            return
        umo = event.unified_msg_origin
        limit = int(self._cfg("merge_threshold", 300) or 0)
        try:
            if limit > 0 and len(body) > limit:
                node = Node(content=[Plain(body)], name="DSH", uin="0")
                await self._deliver(umo, MessageChain([node]))
            else:
                await self._deliver(umo, MessageChain([Plain(body)]))
        except Exception as exc:  # noqa: BLE001 - 打包失败就退化成直发，别把内容丢了
            logger.warning(f"[nanxi_dsh] 合并转发失败，改为直接发送：{exc}")
            try:
                await self._deliver(umo, MessageChain([Plain(body)]))
            except Exception as inner:  # noqa: BLE001
                logger.warning(f"[nanxi_dsh] 群内推送失败：{inner}")

    async def _dsh_cancel(self, token: str, base: str, conversation: str) -> bool:
        """让 DSH **真正**停下这一轮：星驿控制面 ``/rpc`` → ``session/cancel``。

        ⚠️ 为什么不能只靠 AstrBot 的停止：内置 ``stop`` 只做两件事 —— 掐断 AstrBot
        自己的 LLM 输出、取消本插件的 SSE 消费协程。**DSH 侧的 agent 完全不知道**，
        会继续把活干完（2026-10-04 实测：主人叫停后 baah 那轮照跑）。
        星驿的 13 个路由里**没有** cancel（它自有的 ``agent.cancel({kind:'user'})``
        只在插件卸载时用），唯一的出口是控制面 ``POST /rpc``；
        而 ``session/cancel`` **不在默认白名单**（默认只放行 26 条只读方法），
        必须在星驿配置里写进 ``allowedRpcMethods`` 才放行。
        参数形状：``args.request`` 就是 ACP 的 ``session/cancel`` 参数（``{sessionId}``）。

        Args:
            token: 星驿的 ``bridge_token``。
            base: 星驿基址（如 ``http://127.0.0.1:3081/astrbot-relay``）。
            conversation: 该 IM 会话的 UMO，用于查它当前指向哪间 DSH 会话。

        Returns:
            是否成功发出取消。**尽力而为**：失败只记日志，绝不抛出。
        """
        headers = {"Authorization": f"Bearer {token}"}
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(
                    f"{base}{ROUTE_WHERE}",
                    params={"conversation": conversation},
                    headers=headers,
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"[nanxi_dsh] 叫停 DSH 失败：/where 返回 {resp.status}"
                        )
                        return False
                    where = await resp.json()
                session_id = str(where.get("sessionId") or "")
                if not session_id:
                    logger.warning("[nanxi_dsh] 叫停 DSH 失败：/where 没给出 sessionId")
                    return False
                async with sess.post(
                    f"{base}{ROUTE_RPC}",
                    json={
                        "endpoint": "session/cancel",
                        "args": {"request": {"sessionId": session_id}},
                    },
                    headers=headers,
                ) as resp:
                    body = await resp.text()
                    if resp.status != 200:
                        logger.warning(
                            "[nanxi_dsh] 叫停 DSH 失败：/rpc 返回 "
                            f"{resp.status} {body[:200]}"
                        )
                        return False
                    logger.info(f"[nanxi_dsh] 已叫停 DSH 会话 {session_id}")
                    return True
        except Exception as exc:  # noqa: BLE001 - 叫停失败不该影响本轮收尾
            logger.warning(f"[nanxi_dsh] 叫停 DSH 出错（不影响本轮结束）：{exc}")
            return False

    async def _execute(
        self, event: AstrMessageEvent, conversation: str, task: str, turn: str = ""
    ) -> str:
        """把活**丢进后台队列**就返回 —— 不在这里等 DSH 干完。

        ⚠️ 2026-10-04 从"同步等"改成"异步交活"。改的原因：同步等的时候，一个长任务会把
        南汐**整个 turn 占住**，主人这时再发消息就得排队 —— 实测让她改个名等了 **61 秒**
        （22:13:24 发的指令，22:14:25 才执行）。异步之后工具立刻返回、她的 turn 立刻结束，
        能马上接主人下一句话；DSH 那边照跑，正文由后台 worker 发进群。

        ⚠️ 同一会话的活**串行**：DSH 侧一个会话同时只能跑一个 turn，并发投递会互相踩；
        所以这里用队列，第二件活排在后面，回话里也如实说"前面还有活"。

        ⚠️ `@南汐 stop` 在异步之后**不再能靠 active_event_registry** —— 工具一返回，那个
        event 就不在活跃表里了，注册在它身上的停止回调永远等不到。改由
        :meth:`on_message_maybe_stop` 在消息钩子里认领。

        Args:
            event: 触发这次交活的消息事件（后台只读它取 UMO，不靠它发消息）。
            conversation: 该 IM 会话的 UMO。
            task: 交给 DSH 的任务描述。
            turn: 这一轮的追踪 id（前端卡片按它归并）。

        Returns:
            str: 给 LLM 的回话（"已经交出去了、别等"），或配置缺失时的说明。
        """
        base = str(self._cfg("bridge_url", "") or "").strip().rstrip("/")
        token = str(self._cfg("bridge_token", "") or "").strip()
        if not base or not token:
            return (
                "（DSH 桥接没配置好：插件配置里缺 bridge_url 或 bridge_token，"
                "请告诉主人去 AstrBot 插件配置里补上。）"
            )

        queue = self._queues.get(conversation)
        if queue is None:
            queue = asyncio.Queue()
            self._queues[conversation] = queue
        running = self._workers.get(conversation)
        ahead = queue.qsize() + (1 if running is not None and not running.done() else 0)
        #: 会话正忙（有活在手上 / 前面还排着）时，这条消息**插队**投递 —— body 里带
        #: `mode: 'steer'`，星驿透传给 DSH 的 `agent.steer`，投到当前 turn **最近的 step
        #: 边界**，不用等它跑完（`followup` 才要等）。空闲时照旧 followup，不乱插。
        #: 2026-10-04 主人实测反馈过这个：「她忙着时补一句话，不该干等」。
        busy = queue.qsize() > 0 or (running is not None and not running.done())
        await queue.put(
            {
                "event": event,
                "task": task,
                "base": base,
                "token": token,
                "turn": turn,
                "steer": busy,
            }
        )
        if running is None or running.done():
            self._workers[conversation] = asyncio.ensure_future(
                self._run_queue(conversation)
            )

        tail = f"前面还排着 {ahead} 件，会按顺序来。" if ahead else ""
        return (
            "（活已经交给 DSH 了，它在后台干，过程和结果都会自动发到群里。"
            "**你不要等它、也不要复述它的内容**；请用你自己的口吻跟用户说一声已经交出去了，"
            f"然后就可以接着聊别的、或处理他下一句话。{tail}）"
        )

    async def _run_queue(self, conversation: str) -> None:
        """后台 worker：把该会话排队的活一件件跑完（串行）。

        每件活跑完会在群里补一句 `· DSH 干完了（用时 …）` —— 异步模式下 LLM 那一轮早结束了，
        没人在收尾，这句话就是"干完了"的唯一交代。

        ⚠️ 被 `@南汐 stop` 取消时**不回家**：取消中的协程里再 await 会被立刻二次取消，
        `_go_home` 跑不完。下次交活前 `dsh_task` 会先 `_go_home` 一遍，映射不会一直错着。

        Args:
            conversation: 要消费的会话 UMO（队列与 worker 都按它索引）。
        """
        queue = self._queues.get(conversation)
        if queue is None:
            return
        try:
            while True:
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                event: AstrMessageEvent = item["event"]
                started = time.monotonic()
                try:
                    result = await self._run_turn(
                        event,
                        conversation,
                        item["task"],
                        item["base"],
                        item["token"],
                        item["turn"],
                        bool(item.get("steer")),
                        True,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - 一件活失败不该让 worker 死掉
                    logger.warning(f"[nanxi_dsh] 后台任务出错（{conversation}）：{exc}")
                else:
                    spent = time.monotonic() - started
                    await self._say(event, f"· DSH 干完了（用时 {spent:.0f} 秒）")
                    # ⚠️ 结果必须**补回她的上下文**：异步交活之后 tool result 只有一句
                    # "已交出去"，正文只发进了群 —— 她手上是空的，主人一问细节就抓瞎
                    # （2026-10-04 主人实测点名："刚刚的返回你没看到吗"）。
                    # 这里只存下，真正注入在 on_llm_request 钩子里（见 watch_request）。
                    if result:
                        self._inbox[conversation] = result
                    with contextlib.suppress(Exception):
                        await self._go_home(event, conversation)
        finally:
            self._workers.pop(conversation, None)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_maybe_stop(self, event: AstrMessageEvent):
        """``@南汐 stop`` 在「异步交活」之后的新落点。

        为什么需要它：工具一返回，那个 event 就不再是活跃事件，注册在它身上的停止回调
        永远等不到（异步交活的代价）。所以改在**消息层**认领：这条消息是当前会话的
        ``stop``，就把该会话的后台任务取消掉，并顺手 ``session/cancel`` 掉 DSH 那一轮
        （否则 DSH 不知道你停过，会继续把活干完）。

        ⚠️ 内置 `stop` **看不见**这里的后台任务（它数的是 AstrBot 自己的活跃事件，异步交活
        之后那里是空的），所以它必定回一句「（这边没有正在跑的任务）」—— **那句是错的**。
        因此这里取消成功后**要补一句**，否则用户会以为没停、或者根本没注意到已经停了。

        Args:
            event: 任意一条进来的消息（本钩子只看它开头是不是 stop、或者是不是审批回执）。

        Yields:
            None: AstrBot 的钩子靠 async generator 走流程；原样放行、不改 event。
        """
        raw = (event.get_message_str() or "").strip()
        conversation = event.unified_msg_origin

        # ① **审批回执**：主人回一句「同意」/「拒绝」，替他打回星驿的 `POST /approval`。
        #    （这条路必须走消息层：审批是 agent 在等，不是某一轮 LLM 在等。）
        pending = self._pending_approval.get(conversation)
        if pending and (raw in _APPROVE_WORDS or raw in _REJECT_WORDS):
            allow = raw in _APPROVE_WORDS
            self._pending_approval.pop(conversation, None)
            note = await self._reply_approval(conversation, pending, allow)
            await self._say(event, note)
            yield
            return

        # ② **叫停后台任务**（异步交活之后 stop 的新落点）。
        if raw.split(" ")[0].lower() == "stop":
            worker = self._workers.pop(conversation, None)
            if worker is not None and not worker.done():
                worker.cancel()
                logger.info(f"[nanxi_dsh] 后台任务已按 stop 取消（{conversation}）")
                base = str(self._cfg("bridge_url", "") or "").strip().rstrip("/")
                token = str(self._cfg("bridge_token", "") or "").strip()
                if base and token:
                    with contextlib.suppress(Exception):
                        await self._dsh_cancel(token, base, conversation)
                # 只在**真的取消了**的时候补这一句：内置那句"没有正在跑的任务"会让主人
                # 以为白停了，这里如实交代一句（没任务时保持安静，不刷屏）。
                await self._say(event, "· 已叫停后台任务（DSH 那边也停了）")
        yield

    async def _reply_approval(
        self, conversation: str, pending: dict[str, Any], allow: bool
    ) -> str:
        """替主人把一次审批回执打回星驿（``POST /approval``）。

        契约 §3.3：请求体是 ``{conversation, callId, outcome, code}``，其中
        ``outcome`` **只能**是 ``allowed-once``（只放行这一次）或 ``rejected``；
        ``code`` 是审批请求里那个 4 位一次性码；已决议/已超时/码不对都会回到 ``ok:false``。

        Args:
            conversation: 该 IM 会话的 UMO。
            pending: :attr:`_pending_approval` 里那一条（含 callId、code、tool）。
            allow: True → ``allowed-once``；False → ``rejected``。

        Returns:
            str: 给群里的一句中文回执（成功与失败都说清楚，绝不假装成功）。
        """
        base = str(self._cfg("bridge_url", "") or "").strip().rstrip("/")
        token = str(self._cfg("bridge_token", "") or "").strip()
        if not base or not token:
            return "（桥接没配好，没法替你回执这次审批。）"
        tool = pending.get("tool") or "那项操作"
        try:
            await self._relay_post(
                ROUTE_APPROVAL,
                {
                    "conversation": conversation,
                    "callId": pending.get("callId"),
                    "outcome": "allowed-once" if allow else "rejected",
                    "code": pending.get("code"),
                },
            )
        except Exception as exc:  # noqa: BLE001 - 回执失败要说出来，别让主人以为批了
            logger.warning(f"[nanxi_dsh] 审批回执失败（{conversation}）：{exc}")
            return f"（这次审批的回执没打过去：{exc}）"
        return f"· 已{'放行' if allow else '否掉'}这一次 —— {tool}"

    async def _collect_images(self, event: AstrMessageEvent) -> list[dict[str, Any]]:
        """把这条消息里的图片收成星驿 ``/message`` 要的形状：``{mediaType, data}``，data 是**裸 base64**。

        背景：DSH 那边的 ``deepseek-flash`` 声明了 ``inputModalities: ["text","image"]``，
        星驿的 ``/message`` 也收 ``images[]``（它把 base64 存进 DSH 的附件库，再以 image 块
        投给 agent）—— 但 AstrBot 这一侧**从来没人把图递过去**，
        所以用户在群里发的图对 DSH 一直是不可见的。

        上限：星驿的请求体上限是按"三张 20 MiB 原图"反推的（base64 后 4/3 膨胀），
        这里给单图留 12 MiB（base64 后）余量；超了就跳过那一张 ——
        宁可少递一张图，也不能让整条消息投不出去。

        Args:
            event: AstrBot 的消息事件（图片组件从它身上取）。

        Returns:
            list[dict[str, Any]]: 可直接塞进请求体的图片数组；没有图片时是空列表。
        """
        out: list[dict[str, Any]] = []
        limit = 12 * 1024 * 1024
        comps = list(event.get_messages())
        # 诊断用：这条消息到底带了哪些组件（图片有没有进消息链、是什么类）。
        logger.info(
            "[nanxi_dsh] 这条消息的组件："
            + str([f"{type(c).__name__}({getattr(c, 'type', '?')})" for c in comps])
        )
        for comp in event.get_messages():
            if not isinstance(comp, Image):
                continue
            try:
                data = await comp.convert_to_base64()
            except Exception as exc:  # noqa: BLE001 - 单张图失败不该拖垮整轮
                logger.warning(f"[nanxi_dsh] 有张图转 base64 失败，已跳过：{exc}")
                continue
            if not data:
                continue
            if len(data) > limit:
                logger.warning(
                    f"[nanxi_dsh] 有张图太大（base64 后 {len(data)} 字节 > {limit}），已跳过"
                )
                continue
            out.append({"mediaType": _sniff_image_media_type(data), "data": data})
        return out

    async def _run_turn(
        self,
        event: AstrMessageEvent,
        conversation: str,
        task: str,
        base: str,
        token: str,
        turn: str = "",
        steer: bool = False,
        announce: bool = False,
    ) -> str:
        """连 SSE → 投递 → 消费到 turn/end → 组装给 LLM 的返回值。"""
        self.trace_emit("dsh/start", conversation, turn, task=task[:300])
        tools_seen: list[str] = []
        flush_chars = max(1, int(self._cfg("flush_chars", 200) or 1))
        throttle = max(0.0, float(self._cfg("throttle_ms", 2500) or 0) / 1000.0)
        chunk_size = int(self._cfg("chunk_size", 800) or 0)
        #: 逐片直发（旧的流式行为）。默认关：正文在本地攒到最后一次性交付，
        #: 长了由 _send_body 打成一张合并转发卡片 —— 免得刷屏。
        stream_body = bool(self._cfg("stream", False))
        # 软阈值之上找不到句子边界时，最多再容忍到这一长度才硬切。
        hard_chars = max(flush_chars * 3, 600)
        if chunk_size > 0:
            hard_chars = min(hard_chars, chunk_size)
        total = max(30.0, float(self._cfg("request_timeout", 600) or 600))
        deadline = time.monotonic() + total

        parts = conversation.split(":")
        headers = {"Authorization": f"Bearer {token}"}
        # 用户这条消息里带的图，一并交给 DSH —— 它那边的 deepseek-flash 声明了 image 模态，
        # 是真能看图的；星驿会把 base64 存进附件库，再以 image 块投给 agent（图在前、文在后）。
        images = await self._collect_images(event)
        payload: dict[str, Any] = {
            "conversation": conversation,
            "text": task,
            "messageId": str(getattr(event.message_obj, "message_id", "") or ""),
            "sender": {
                "id": str(event.get_sender_id()),
                "name": str(event.get_sender_name() or ""),
            },
            "meta": {
                "platform": parts[0] if parts else "",
                "messageType": parts[1] if len(parts) > 1 else "",
            },
        }
        if images:
            payload["images"] = images
            self.trace_emit("dsh/images", conversation, turn, count=len(images))
        if steer:
            # 插队：星驿那边打好 `patch_relay_steer.py` 后会把 mode 透传给 DSH 的
            # `agent.steer`（投到当前 turn 最近的 step 边界，不等它跑完）。
            # ⚠️ 没打补丁时星驿会**忽略**这个字段 —— 退化成普通的排队投递，
            # 不会出错，只是还得等。
            payload["mode"] = "steer"
            self.trace_emit("dsh/steer", conversation, turn)
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        #: 已经交付给会话的正文：流式时=已经直发出去，非流式时=已经写进结果链。
        #: 两者都算「内容已经在群里了」，所以返回口径都是「只收尾、别重复」。
        emitted = ""
        pending = ""  # 已收到但还没发的增量
        final_text = ""
        notes: list[str] = []
        last_flush = time.monotonic()
        last_tool = ""  # 进度播报去重：同名工具 30 秒内只报一次
        last_tool_at = 0.0

        try:
            async with aiohttp.ClientSession() as session:
                stream_timeout = aiohttp.ClientTimeout(
                    total=None,
                    sock_connect=10,
                    sock_read=max(
                        30.0,
                        float(
                            self._cfg("sse_read_timeout", _DEFAULT_SSE_READ_SECONDS)
                            or _DEFAULT_SSE_READ_SECONDS
                        ),
                    ),
                )
                async with session.get(
                    base + ROUTE_EVENTS,
                    params={"conversation": conversation},
                    headers={**headers, "Accept": "text/event-stream"},
                    timeout=stream_timeout,
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        detail = (await resp.text())[:200]
                        return f"（DSH 事件流握手失败：HTTP {resp.status} {detail}）"

                    # ★ 顺序是硬要求：SSE 先连上，再投递。
                    try:
                        async with session.post(
                            base + ROUTE_MESSAGE,
                            data=raw,
                            headers={
                                **headers,
                                "Content-Type": "application/json",
                                "Idempotency-Key": str(uuid.uuid4()),
                            },
                            timeout=aiohttp.ClientTimeout(total=30),
                            ssl=False,
                        ) as post:
                            detail = (await post.text())[:200]
                            if post.status >= 300:
                                return f"（投递给 DSH 失败：HTTP {post.status} {detail}）"
                    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                        return f"（投递给 DSH 失败：{exc}）"

                    data_lines: list[str] = []
                    async for raw_line in resp.content:
                        if time.monotonic() > deadline:
                            notes.append("等待 DSH 回复超时，本轮结果可能不完整")
                            break
                        line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                        if line.startswith(":"):
                            continue  # 注释帧（服务端连上先发 ": connected" 热身）
                        if line:
                            data_lines.append(line)
                            continue
                        payload = _parse_sse_block(data_lines)
                        data_lines = []
                        if payload is None:
                            continue
                        kind = str(payload.get("type") or "")
                        if kind in (
                            _EVENT_HEARTBEAT,
                            _EVENT_TURN_START,
                            _EVENT_REASONING_DELTA,
                            _EVENT_APPROVAL_RESOLVED,
                            _EVENT_QUESTION_RESOLVED,
                        ):
                            continue

                        if kind == _EVENT_TEXT_DELTA:
                            pending += str(payload.get("text") or "")
                            if pending and (
                                len(pending) >= flush_chars
                                or (
                                    throttle <= 0
                                    or time.monotonic() - last_flush >= throttle
                                )
                            ):
                                cut = _pick_cut(pending, flush_chars, hard_chars)
                                if cut:
                                    emitted += pending[:cut]
                                    # 只有开了 stream 才逐片直发；默认只累计，
                                    # 等收尾时由 _send_body 一次性交付（长了打成合并转发卡片）。
                                    if stream_body:
                                        await self._say(event, pending[:cut].rstrip("\n"))
                                    pending = pending[cut:]
                                    last_flush = time.monotonic()
                            continue

                        if kind == _EVENT_TOOL_CALL:
                            name = str(payload.get("name") or "工具")
                            # 观察面板要**每一次**调用 —— 面板不会刷屏，群才会。
                            tools_seen.append(name)
                            self.trace_emit("dsh/tool", conversation, turn, name=name)
                            # 进度播报**默认关**：同名工具连着调十几次是常态
                            # （翻目录、逐个读文件），播报出来就是刷屏 —— 主人明确说不要。
                            # 想开就把配置里的 tool_progress 打开（那时同名 30 秒仍只报一次）。
                            if bool(self._cfg("tool_progress", False)):
                                now = time.monotonic()
                                if name != last_tool or now - last_tool_at >= 30.0:
                                    last_tool, last_tool_at = name, now
                                    await self._say(event, f"· DSH 正在用 {name}")
                            continue

                        if kind == _EVENT_GAP:
                            await self._say(event, "（链路抖动，中间有内容丢了）")
                            continue

                        if kind == _EVENT_APPROVAL_REQUIRED:
                            # 星驿**接管了**这次审批（approval waterfall 命中本桥）：
                            # 把请求转述到群里，等主人一句话回执（见 on_message_maybe_stop）。
                            # 契约 §3.3：`POST /approval` 要 {conversation, callId, outcome, code}，
                            # outcome 只能 `allowed-once` / `rejected`，code 是 4 位一次性码，
                            # 默认 120 秒超时 → 超时按 rejected（fail closed）。
                            call_id = str(payload.get("callId") or "")
                            code = str(payload.get("code") or "")
                            tool = str(payload.get("toolName") or "未知工具")
                            why = str(payload.get("reason") or "").strip() or "（它没说明理由）"
                            left = ""
                            try:
                                expires = float(payload.get("expiresAt") or 0) / 1000.0
                                if expires:
                                    left = f"，{max(0, int(expires - time.time()))} 秒内有效"
                            except Exception:  # noqa: BLE001
                                left = ""
                            if call_id and code:
                                self._pending_approval[conversation] = {
                                    "callId": call_id,
                                    "code": code,
                                    "tool": tool,
                                }
                                await self._say(
                                    event,
                                    "⚠️ DSH 要动一项敏感操作，等你点头喵：\n"
                                    f"· 工具：{tool}\n"
                                    f"· 它说：{why}\n"
                                    f"· 一次性码：{code}{left}\n"
                                    "回「同意」放行这一次，回「拒绝」否掉；"
                                    "不吭声到点算拒绝。",
                                )
                            notes.append(
                                "DSH 请求了一项敏感操作授权，已经把请求和一次性码转到群里，"
                                "等主人回「同意」或「拒绝」；没回应会在超时后按拒绝处理。"
                            )
                            continue

                        if kind == _EVENT_APPROVAL_RESOLVED:
                            # 审批落地（主人回执 / 超时 / turn 被取消），如实说一声。
                            outcome = str(payload.get("outcome") or "")
                            via = str(payload.get("via") or "")
                            self._pending_approval.pop(conversation, None)
                            word = {
                                "allowed-once": "放行了",
                                "rejected": "否掉了",
                                "cancelled": "作废了",
                            }.get(outcome, outcome or "结束了")
                            await self._say(event, f"· 那项审批{word}（{via}）")
                            continue

                        if kind == _EVENT_QUESTION_REQUIRED:
                            notes.append(
                                "DSH 中途向用户提问了，但自主调用这条链路还不支持作答，"
                                "该问题已被搁置。"
                            )
                            continue

                        if kind == _EVENT_MESSAGE_FINAL:
                            final_text = str(payload.get("text") or "")
                            continue

                        if kind == _EVENT_TURN_END:
                            reason = payload.get("reason") or {}
                            if str(reason.get("kind") or "") == "error":
                                err = reason.get("error") or {}
                                notes.append(
                                    "DSH 报错："
                                    f"{err.get('message') or err or '未知错误'}"
                                )
                            break
                        # 其余类型忽略（前向兼容）
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if not emitted:
                return f"（DSH 链路中断：{exc}）"
            notes.append(f"链路中断：{exc}")
        except Exception as exc:  # noqa: BLE001 - 单次工具调用失败不得拖垮插件
            logger.error(f"[nanxi_dsh] 调用 DSH 失败：{exc}", exc_info=True)
            if not emitted:
                return f"（调用 DSH 出错：{exc}）"
            notes.append(f"出错：{exc}")

        tail = (
            final_text[len(emitted) :]
            if final_text.startswith(emitted)
            else (final_text or pending)
        )
        suffix = f"\n（另外：{'；'.join(notes)}）" if notes else ""
        self.trace_emit(
            "dsh/end",
            conversation,
            turn,
            chars=len(final_text or pending or ""),
            tools=tools_seen,
            notes=notes,
        )

        if emitted:
            # 正文已经交付过了：流式模式下是逐片发出去的，非流式模式下还没发 ——
            # 后者在这里一次性交给 _send_body（超过 merge_threshold 会自动打成一张卡片）。
            #
            # ⚠️ 「交付给群」≠「交付给南汐」，这两件事必须分开做（2026-10-04 修）。
            #   正文走 _send_body 直接进群、**不过 LLM**；如果 tool result 里只回一句
            #   「已经发出去了，别重复」，南汐的上下文里就只剩「干完了」三个字 ——
            #   她手上根本没有这份成果，用户回头问内容时她只能现编，或者绕远去翻群历史。
            #   所以这里把正文**同时**塞进 tool result：她要记住它；同时用最硬的措辞
            #   禁止她再讲一遍（防群里出现两份）。
            body_text = final_text or pending or emitted
            if stream_body:
                if tail.strip():
                    await self._say(event, tail.rstrip("\n"))
            else:
                await self._send_body(event, body_text)
            return (
                "（下面这段是 DSH 的成果，它**已经自动发到群里了**，所以"
                "你**不要**再说一遍、不要复述、不要总结、也不要逐条转述 —— "
                "群里已经有它了，重复一遍会让人看到两份。"
                "你只需要用自己的口吻补一两句收尾或点评。\n"
                "但**你要记住**这段成果：之后用户问起它的内容时，"
                "你要凭它回答，不要再说「我只知道干完了」，也不要现编。\n"
                f"--- DSH 的成果开始 ---\n{body_text}\n--- DSH 的成果结束 ---）" + suffix
            )

        text = (final_text or pending).strip()
        if not text:
            return (
                "（DSH 这一轮什么也没返回。请用你自己的口吻告诉用户它没吭声，"
                "别编造它做了什么。）" + suffix
            )
        if announce:
            # ⚠️ 异步交活专用的一条路：这一轮**没有 LLM 在等结果**（工具早就返回了），
            # 所以「请南汐用人设转述」的下场是**没人转述** —— 群里只剩一句「干完了」，
            # 主人什么内容都看不到（2026-10-04 主人实测：只看到 `· DSH 干完了（用时 2 秒）`）。
            # 这里直接发进群；返回值照样带正文，好让 worker 存进 _inbox 补回她的上下文。
            await self._send_body(event, text)
            return (
                "（下面这段是 DSH 的结果，它**已经自动发到群里了**，所以"
                "你**不要**再说一遍、不要复述、不要总结、也不要逐条转述 —— "
                "群里已经有它了，重复一遍会让人看到两份。"
                "但**你要记住**这段结果：之后用户问起它的内容时，"
                "你要凭它回答，不要再说「我只知道干完了」，也不要现编。\n"
                f"--- DSH 的结果开始 ---\n{text}\n--- DSH 的结果结束 ---）" + suffix
            )
        return (
            "（DSH 已经执行完毕，下面是它的原始结果：\n"
            f"{text}\n）{suffix}\n"
            "请用南汐自己的口吻把结果讲给用户听：事实不许改，语气和排版都换成你的，"
            "不要照搬它的小标题和代码块结构，除非那本来就是用户要的东西。"
        )
