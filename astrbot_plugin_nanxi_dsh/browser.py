"""南汐**自己**的浏览器 —— 纯 Python 驱动 Chrome（CDP），不需要 playwright。

## 为什么要有它

DSH 那侧早就装了 ``dsh-ego-browser``，但那是 **DSH agent 的手**：南汐（AstrBot 侧的聊天
人格）只能 ``dsh_task`` 指挥它去做，看不见、点不了、也没法自己看页面。
2026-10-04 主人明确要的是「**南汐自己操控**」—— 所以这一套是给她**本人**的工具：
她自己开页面、自己读正文、自己点、自己输入、自己截图发到群里。

## 实现要点（都是趟出来的）

- **不装 playwright**：Chrome 自带 DevTools Protocol（CDP）——HTTP 拿目标列表、
  WebSocket 发命令。AstrBot 的 site-packages 里已经有 ``aiohttp``（自带 ``ws_connect``），
  所以**零新依赖**。实测（``logs/_probe_cdp.py``）：导航 + 读正文 + 截图全通。
- **``--headless=new``**：不弹窗口，但和真 Chrome 同一个渲染引擎 —— 截图和 JS 执行都是真的。
- **持久 profile**：登录态留着。她登过一次的站，下次还在（**这是特性**：能登录才有用）。
- **懒启动 + 空闲回收**：第一次用才起 Chrome；闲置 ``idle_timeout`` 秒后自动关掉，
  不常驻吃内存。
- **一把锁**：只有一个浏览器、一个当前页面，多个群同时用会互相踩，所以全部串行。
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import pathlib
import re
import subprocess
import tempfile
import time
from typing import Any

import aiohttp

# ⚠️ 这个模块是**动态加载**的（`main.py` 用 spec_from_file_location 装进来），
#    所以它拿不到 main.py 那个 `logger` 变量，得自己接一个。
#    为什么值得接：2026-10-05 排查"看板只有 1 帧"时，兜底轮询**静默失败**、
#    一行日志都没有，只能靠人肉盯着 /state 的秒数变化猜 —— 太贵了。
#    优先用 AstrBot 的插件 logger（这样日志会落到 logs\astrbot.log 里，
#    和 main.py 的那份在一起）；单独跑探针脚本时退回标准 logging。
try:  # noqa: SIM105
    from astrbot.api import logger as logger
except Exception:  # noqa: BLE001 - 脱离 AstrBot 单独跑时没有这个包
    import logging

    logger = logging.getLogger("nanxi_dsh_browser")

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)

#: screencast 静默多久算"哑了"、该由轮询截图接管（秒）。
#: 实测 headless 里 screencast 只在页面加载/重绘时推帧，页面一静就没声了，
#: 所以这个阈值取小一点（1.5 秒）让看板尽快接上；接管之后按稳定 1 fps 走。
_FRAME_SILENT = 1.5

#: 超过这么久没人看看板，兜底轮询就停手（秒）。
#: 看板页面每 700ms 打一次 `/state`，所以"有人看"是很容易判断的；
#: 没人看还每秒截一张图纯属白烧 CPU。
_VIEWER_GRACE = 30.0

#: 本机第一个存在的浏览器可执行文件；都没有就返回 None（工具会如实拒绝）。
def find_browser() -> str | None:
    """找一个可用的 Chromium 内核浏览器。

    Returns:
        str | None: 可执行文件路径；Chrome 与 Edge 都没有时返回 None。
    """
    for path in CHROME_CANDIDATES:
        if path and pathlib.Path(path).is_file():
            return path
    return None


def dsh_web_login_url(log_dir: pathlib.Path, port: int = 3081) -> str | None:
    """从 DSH 实例的控制台日志里挖出**当前有效**的一次性登录 URL。

    为什么得这么绕：DSH 0.2.0 起给 Web 加了认证 —— 裸开 ``http://127.0.0.1:<port>/``
    只会得到 401，必须先拿启动时打印的 ``…/?token=…`` 换一次 cookie。
    而那个 token **只存在内存里、不落盘**（``~/.dsh/guard/logs`` 里那份是**上一个进程**的
    陈旧值，用它换必然 401）。唯一能找到当前 token 的地方就是启动时那行 stdout ——
    本项目的 ``启动\\start-nanxi-dsh.ps1`` 正好把它落到了 ``logs/nanxi-web-*.log``。

    换到 cookie 之后它会留在浏览器 profile 里，往后直接开根路径就行，不必再带 token。

    Args:
        log_dir: 实例控制台日志所在目录（``…\\nanxi-dsh\\logs``）。
        port: 实例端口，用来认准是哪一条 URL。

    Returns:
        str | None: 带 token 的完整 URL；日志不在或没匹配到就 None。
    """
    if not log_dir.is_dir():
        return None
    logs = sorted(
        log_dir.glob("nanxi-web-*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    pattern = re.compile(
        r"http://127\.0\.0\.1:%d/\?token=[A-Za-z0-9_\-]+" % port
    )
    for path in logs[:4]:  # 只看最近几份；更早的 token 早失效了
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 读不了就跳过，绝不能因此抛错
            continue
        hits = pattern.findall(text)
        if hits:
            return hits[-1]  # 同一个进程可能打印过多次，取最后一次
    return None


class WatchServer:
    """一个**只看不摸**的小网页：让人在浏览器里看她那台 headless 浏览器在干什么。

    她跑的是 headless（不弹窗、不抢你的焦点），代价就是"看不见"。这里把她的
    **最新一帧**（CDP screencast 推来的）刷成一个网页：

        http://127.0.0.1:<port>/        看板：画面 + 当前网址/标题 + "她刚点在哪"的红点
        http://127.0.0.1:<port>/frame   最新一帧（JPEG）
        http://127.0.0.1:<port>/state   她在哪、标题是什么、鼠标坐标（JSON）

    ⚠️ **headless 的帧本身不含光标** —— 所以那个红点是前端按我们记录的坐标画上去的，
    不是截出来的（这正是 ego-browser 让人"看得见鼠标"的办法）。
    ⚠️ **只读**：这里不对她的页面做任何操作。
    """

    def __init__(self, browser: "Browser", port: int = 6199) -> None:
        self._b = browser
        self._port = port
        self._runner: Any = None

    async def start(self) -> bool:
        """起这个只读看板；端口被占等失败都只是返回 False，不影响别的功能。

        Returns:
            bool: 是否起来了。
        """
        try:
            from aiohttp import web
        except Exception:  # noqa: BLE001 - 没有 aiohttp.web 就不提供看板
            return False

        async def index(_req):
            return web.Response(
                text=_PAGE_HTML.replace("__PORT__", str(self._port)),
                content_type="text/html",
                charset="utf-8",
            )

        async def frame(_req):
            self._b.touch_viewer()
            data = self._b.frame
            if not data:
                return web.Response(status=204)  # 还没收到帧
            return web.Response(
                body=data,
                content_type="image/jpeg",
                headers={"Cache-Control": "no-store"},
            )

        async def state(_req):
            self._b.touch_viewer()
            cur = self._b.cursor
            return web.json_response(
                {
                    "seq": self._b.frame_seq,
                    "hasFrame": self._b.frame is not None,
                    "url": self._b.last_url,
                    "title": self._b.last_title,
                    "cursor": cur,
                    # 这一帧是"浏览器推的"还是"我们截图补的" —— 看板会显示，
                    # 一眼就能看出 screencast 是不是又哑了（哑了不该再静默地卡住）。
                    "mode": self._b.frame_src,
                    "ageSec": (
                        None
                        if self._b.frame_age is None
                        else round(self._b.frame_age, 1)
                    ),
                    # 这两项纯粹是**排障用**的：2026-10-05 那轮"看板只有 1 帧"，
                    # 从外面只看得到 seq 不动，分不清是"轮询根本没起来"还是"起来了但截图失败"。
                    "casting": self._b.casting,
                    "poller": self._b.poller_state,
                }
            )

        app = web.Application()
        app.router.add_get("/", index)
        app.router.add_get("/frame", frame)
        app.router.add_get("/state", state)
        try:
            self._runner = web.AppRunner(app)
            await self._runner.setup()
            site = web.TCPSite(self._runner, "127.0.0.1", self._port)
            await site.start()
        except Exception:  # noqa: BLE001 - 端口被占之类，静默放弃
            with contextlib.suppress(Exception):
                await self._runner.cleanup()
            self._runner = None
            return False
        return True

    async def stop(self) -> None:
        """关掉看板（幂等）。"""
        if self._runner is not None:
            with contextlib.suppress(Exception):
                await self._runner.cleanup()
            self._runner = None


#: 看板页面：一秒钟换一张画面，右上角标出"她刚才点在哪"。
#: （`__PORT__` 由 :meth:`WatchServer.start` 替换成真实端口。）
_PAGE_HTML = """<!doctype html>
<meta charset="utf-8">
<title>南汐的浏览器</title>
<style>
  html,body{margin:0;height:100%;background:#111;color:#ddd;font:13px/1.5 system-ui,sans-serif}
  #bar{padding:8px 12px;background:#1b1b1f;border-bottom:1px solid #333;
       display:flex;gap:14px;align-items:center;flex-wrap:wrap}
  #bar b{color:#8fd3ff;font-weight:600}
  #bar .k{color:#888}
  #wrap{position:relative;display:inline-block;margin:10px;box-shadow:0 0 0 1px #333}
  #shot{display:block;max-width:calc(100vw - 20px)}
  /* 她刚才点/填的地方 —— headless 帧里没有光标，所以这个点是画上去的 */
  #dot{position:absolute;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;
       background:rgba(255,60,60,.85);box-shadow:0 0 10px 3px rgba(255,60,60,.5);
       pointer-events:none;display:none;transition:left .25s,top .25s}
  #off{padding:40px;color:#888}
</style>
<div id="bar">
  <span><b>南汐的浏览器</b>（只看不摸）</span>
  <span><span class="k">页面:</span> <span id="title">—</span></span>
  <span><span class="k">地址:</span> <span id="url">—</span></span>
  <span><span class="k">帧:</span> <span id="seq">0</span></span>
  <span><span class="k">来源:</span> <span id="mode">—</span></span>
  <span><span class="k">静默:</span> <span id="ago">—</span>s</span>
</div>
<div id="off">她还没开浏览器（或已经收工了）。她一开始用，这里就会动起来。</div>
<div id="wrap" style="display:none">
  <img id="shot" alt="她的画面">
  <div id="dot"></div>
</div>
<script>
let lastSeq = -1;
const shot = document.getElementById('shot');
const dot = document.getElementById('dot');
const wrap = document.getElementById('wrap');
async function tick() {
  try {
    const s = await (await fetch('/state', {cache:'no-store'})).json();
    document.getElementById('title').textContent = s.title || '—';
    document.getElementById('url').textContent = s.url || '—';
    document.getElementById('seq').textContent = s.seq;
    document.getElementById('mode').textContent =
      s.mode === 'poll' ? '截图兜底' : (s.mode === 'screencast' ? '浏览器推流' : '—');
    document.getElementById('ago').textContent =
      (s.ageSec === null || s.ageSec === undefined) ? '—' : s.ageSec;
    if (s.hasFrame && s.seq !== lastSeq) {
      lastSeq = s.seq;
      shot.src = '/frame?t=' + Date.now();
      document.getElementById('off').style.display = 'none';
      wrap.style.display = 'inline-block';
    }
    if (s.cursor && wrap.style.display !== 'none') {
      const r = shot.getBoundingClientRect();
      dot.style.left = (s.cursor.x * r.width) + 'px';
      dot.style.top  = (s.cursor.y * r.height) + 'px';
      dot.style.display = 'block';
    } else {
      dot.style.display = 'none';
    }
  } catch (e) { /* 服务没起来就算了 */ }
}
setInterval(tick, 700);
tick();
</script>
"""


class Browser:
    """一个常驻的 headless 浏览器 + 一条 CDP 连接。所有方法都必须在锁里调。"""

    def __init__(
        self,
        exe: str,
        profile_dir: pathlib.Path,
        port: int = 9333,
        idle_timeout: float = 600.0,
        window: str = "1280,900",
    ) -> None:
        self._exe = exe
        self._profile = profile_dir
        self._port = port
        self._idle = idle_timeout
        self._window = window
        self._proc: subprocess.Popen | None = None
        self._http: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._pump: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._seq = 0
        self._last_used = 0.0
        self._lock = asyncio.Lock()
        #: 观察窗用的状态：最新一帧（JPEG 字节）、帧序号、以及"鼠标在哪"（归一化坐标）。
        self._frame: bytes | None = None
        self._frame_seq = 0
        self._cursor: dict[str, float] | None = None
        self._casting = False
        #: 最近一帧是**什么时候**到的（monotonic）。screencast 是流控的 ——
        #: 只要 Chrome 那边不再推，`_frame` 就会永久冻在旧画面上，看板于是"只有 1 帧"。
        #: 靠这个时间戳判断"screencast 是不是哑了"，哑了就降级成轮询截图（见 `_poll_frames`）。
        self._frame_at = 0.0
        #: 这一帧是哪儿来的：``"screencast"`` / ``"poll"``（看板会显示，便于一眼看出走的哪条路）。
        self._frame_src = ""
        self._poller: asyncio.Task | None = None
        #: 兜底轮询的两条"只报一次"开关（一路每秒重试，不能每秒刷一行日志）。
        self._poll_warned = False
        self._poll_err = False
        #: 轮询是否已经"接管"（screencast 哑过一次就算接管，直到它重新推帧）。
        self._polling = False
        #: 最近一次"有人在看看板"的时间。没人看就不必每秒截一张图（见 `_poll_frames`）。
        self._viewer_at = 0.0
        #: 看板要显示"她在哪"：最近一次导航的网址与标题。
        self._last_url = ""
        self._last_title = ""

    @property
    def frame_seq(self) -> int:
        """已经收到多少帧（看板据此判断"有没有新画面"）。"""
        return self._frame_seq

    @property
    def frame_src(self) -> str:
        """这一帧的来源：``screencast``（浏览器主动推）还是 ``poll``（我们按秒截图兜底）。"""
        return self._frame_src

    @property
    def frame_age(self) -> float | None:
        """距离最近一帧过了多少秒；还没收到过帧时是 None。

        看板顶部把它显示出来 —— **"画面冻住了"和"她没在动"是两回事**，
        有这两个数（来源 + 静默秒数）就能一眼分清。
        """
        if not self._frame_at:
            return None
        return time.monotonic() - self._frame_at

    def touch_viewer(self) -> None:
        """记下"此刻有人在看看板"（`WatchServer` 的 /state、/frame 每次都会调）。

        用途：没有人看的时候，兜底轮询就**不必每秒截一张图**白烧 CPU。
        """
        self._viewer_at = time.monotonic()

    @property
    def poller_state(self) -> str:
        """兜底轮询任务现在是什么状态（排障用，看板 /state 会带出来）。

        Returns:
            str: ``none`` / ``running`` / ``done`` / ``exc:<异常>`` / ``cancelled``。
        """
        p = self._poller
        if p is None:
            return "none"
        if not p.done():
            return "running"
        if p.cancelled():
            return "cancelled"
        exc = p.exception()
        return "done" if exc is None else f"exc:{exc!r}"

    @property
    def last_url(self) -> str:
        """最近一次打开的网址（看板顶部显示）。"""
        return self._last_url

    @property
    def last_title(self) -> str:
        """最近一次页面的标题。"""
        return self._last_title

    # ---- 生命周期 ----------------------------------------------------

    @property
    def lock(self) -> asyncio.Lock:
        """全局互斥锁：一个浏览器、一个当前页，多个群并发会互相踩。"""
        return self._lock

    @property
    def running(self) -> bool:
        """浏览器是不是**还能用**（CDP 连接还在就算能用）。

        ⚠️ **不能只看 `_proc`** —— 2026-10-05 实测踩了这个坑：
        Windows 上 Chrome 有"单例"行为 —— 若 `--user-data-dir` 已经有一个实例在跑，
        新起的 `chrome.exe` 会把请求**交给那个实例然后自己立刻退出**。
        于是 `self._proc.poll()` 立刻非空 ⇒ `running` 永远 False ⇒
        **每一次 `ensure()` 都误判成"死了"，走 `close()` 把 CDP 连接拆掉重建** ——
        连带把 `_casting` 和兜底轮询任务一起复位。
        症状就是主人的看板：`帧: 1`，画面永远冻在那一刻
        （`/state` 里 `casting=false`、`poller=none` 一眼可见）。
        正解：**CDP 连接还在，就说明浏览器活着**；启动器进程退不退出不关我们的事。
        """
        if self._ws is not None and not self._ws.closed:
            return True
        return self._proc is not None and self._proc.poll() is None

    async def _find_target(self, deadline: float) -> tuple[str | None, bool]:
        """在 ``deadline`` 秒内轮询 CDP 的目标列表。

        Args:
            deadline: 最多等多少秒。

        Returns:
            tuple: ``(ws_url, 启动器进程是否已退出)``；前者为 None 表示没等到。
        """
        if self._http is None:
            return None, False
        end = time.monotonic() + deadline
        exited = False
        while True:
            if self._proc is not None and self._proc.poll() is not None:
                exited = True
            try:
                async with self._http.get(
                    f"http://127.0.0.1:{self._port}/json/list", timeout=2.0
                ) as resp:
                    tabs = await resp.json()
                ws_url = next(
                    (t["webSocketDebuggerUrl"] for t in tabs if t.get("type") == "page"),
                    None,
                )
                if ws_url:
                    return ws_url, exited
            except Exception:  # noqa: BLE001 - CDP 还没起来，继续等
                pass
            if time.monotonic() >= end:
                return None, exited
            await asyncio.sleep(0.4)

    async def ensure(self) -> None:
        """确保浏览器与 CDP 连接可用（懒启动；闲置太久会先回收）。

        Raises:
            RuntimeError: 浏览器起不来或 CDP 连不上（带可读原因）。
        """
        if self._ws is not None and not self._ws.closed:
            if self._last_used and time.monotonic() - self._last_used > self._idle:
                await self.close(reason="闲置超时")
            else:
                return
        await self.close(reason="重启")
        self._profile.mkdir(parents=True, exist_ok=True)
        self._http = aiohttp.ClientSession()
        # ⚠️ **先试着接管已经在跑的那个 headless**，别急着开新的。两个理由：
        #   ① 上一个 AstrBot 进程被强杀时，它的 Chrome 会变成孤儿还在监听 9333 ——
        #      再起一个只会"交接完自己退出"，把 `running` 搞成永远 False（见 `running`）；
        #   ② 反复交接还会不停堆 Chrome 子进程（实测攒了 17 个）。
        #   接管是安全的：那就是**同一个 profile**、同一个调试端口，本来就该是同一个浏览器。
        ws_url, launcher_exited = await self._find_target(deadline=3.0)
        if ws_url:
            logger.info("[nanxi 看板] 接管已经在跑的 headless 浏览器（未另起进程）")
        else:
            self._proc = subprocess.Popen(  # noqa: S603 - 路径是本机已知的浏览器
                [
                    self._exe,
                    "--headless=new",
                    f"--remote-debugging-port={self._port}",
                    f"--user-data-dir={self._profile}",
                    f"--window-size={self._window}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-gpu",
                    "--disable-background-timer-throttling",
                    # ⚠️ 这三条是给**看板**加的：headless 里这个标签页一旦被 Chrome 判成
                    #    "后台/被遮挡"，渲染器就不再出新合成帧 —— 于是 `Page.startScreencast`
                    #    只推得出**第一帧**，看板就永久冻在那张画面上（2026-10-05 实测踩到：
                    #    主人打开 127.0.0.1:6199 看到的正是"帧: 1"、画面还是上一页）。
                    #    ego-browser 的源码里也记着同类现象：*"A backgrounded or unfocused tab
                    #    silently drops CDP input"*。
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-features=CalculateNativeWinOcclusion",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            ws_url, launcher_exited = await self._find_target(deadline=30.0)
            # ⚠️ 这里**故意不因"启动器退了"而报错** —— 那正是 Chrome 单例交接的正常表现，
            #    真正的浏览器已经在端口上服务了（旧代码在这里 raise，等于把正常情况判成失败）。
            del launcher_exited
        if not ws_url:
            raise RuntimeError("等不到 CDP 调试目标（30 秒超时）")
        self._ws = await self._http.ws_connect(ws_url, max_msg_size=0)
        self._pump = asyncio.ensure_future(self._read_loop())
        with contextlib.suppress(Exception):
            await self.call("Page.enable")
        # 让标签页保持"前台"—— 被遮挡的渲染器不出新帧，看板就看不到东西。
        with contextlib.suppress(Exception):
            await self.call("Page.bringToFront")
        self._last_used = time.monotonic()

    async def _read_loop(self) -> None:
        """把 CDP 的响应按 id 派回各自的 future；**事件**里只捞 screencast 的帧。"""
        ws = self._ws
        if ws is None:
            return
        with contextlib.suppress(Exception):
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except Exception:  # noqa: BLE001
                    continue
                if data.get("method") == "Page.screencastFrame":
                    # ⚠️ 帧是**事件**，不是响应：必须自己收、并且**每帧都要 ack**，
                    # 不 ack 浏览器就不再推下一帧（这是最容易漏的一步）。
                    params = data.get("params") or {}
                    b64 = params.get("data")
                    if b64:
                        self._frame = base64.b64decode(b64)
                        self._frame_seq += 1
                        self._frame_at = time.monotonic()
                        self._frame_src = "screencast"
                    sid = params.get("sessionId")
                    if sid is not None:
                        with contextlib.suppress(Exception):
                            await ws.send_json(
                                {
                                    "id": self._seq + 100000,
                                    "method": "Page.screencastFrameAck",
                                    "params": {"sessionId": sid},
                                }
                            )
                    continue
                fut = self._pending.pop(data.get("id"), None)
                if fut is not None and not fut.done():
                    fut.set_result(data)

    async def close(self, reason: str = "") -> None:
        """关掉 CDP 连接与浏览器进程（幂等，任何时候都能调）。"""
        # ⚠️ `_casting` 必须在这里复位：原来 `close()` 不动它，于是"闲置回收 / 重启"
        #    之后它仍是 True，`_ensure_watch()` 里的 `if not b.casting: watch_on()`
        #    永远不会再触发 —— 看板从此**永久停在最后一帧**，谁也救不回来。
        self._casting = False
        if self._poller is not None:
            self._poller.cancel()
            self._poller = None
        if self._pump is not None:
            self._pump.cancel()
            self._pump = None
        self._pending.clear()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._http is not None:
            with contextlib.suppress(Exception):
                await self._http.close()
            self._http = None
        if self._proc is not None:
            with contextlib.suppress(Exception):
                self._proc.terminate()
                self._proc.wait(timeout=5)
            with contextlib.suppress(Exception):
                self._proc.kill()
            self._proc = None
        self._last_used = 0.0
        del reason  # 只为日志可读性保留形参

    # ---- CDP ---------------------------------------------------------

    async def call(self, method: str, timeout: float = 30.0, **params: Any) -> dict:
        """发一条 CDP 命令并等它的响应。

        Args:
            method: CDP 方法名，如 ``Page.navigate``。
            timeout: 等待响应的秒数。
            **params: CDP 参数。

        Returns:
            dict: CDP 原始响应（``{"id":…, "result":…}`` 或 ``{"error":…}``）。

        Raises:
            RuntimeError: 连接不在或超时。
        """
        if self._ws is None or self._ws.closed:
            raise RuntimeError("浏览器连接不在")
        self._seq += 1
        mid = self._seq
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send_json({"id": mid, "method": method, "params": params})
        self._last_used = time.monotonic()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(mid, None)

    async def _js(self, expression: str, timeout: float = 30.0) -> Any:
        """在页面里跑一段 JS 并取回它的值。

        Args:
            expression: 要执行的 JS 表达式。
            timeout: 等待秒数。

        Returns:
            Any: JS 的返回值（序列化后的）；出错时返回错误字符串。
        """
        res = await self.call(
            "Runtime.evaluate",
            timeout=timeout,
            expression=expression,
            returnByValue=True,
            awaitPromise=True,
        )
        if "error" in res:
            return f"（JS 出错：{res['error'].get('message')}）"
        inner = (res.get("result") or {}).get("result") or {}
        return inner.get("value")

    # ---- 给工具用的高层动作 -------------------------------------------

    async def goto(self, url: str) -> dict:
        """打开一个网址，等它基本加载完，返回标题与正文。

        Args:
            url: 目标网址（没写协议时补 ``https://``）。

        Returns:
            dict: ``{"url":…, "title":…, "text":…}``；加载失败时 ``error`` 里带原因。
        """
        if "://" not in url:
            url = "https://" + url
        await self.ensure()
        res = await self.call("Page.navigate", timeout=45.0, url=url)
        if "error" in res:
            return {"error": f"导航失败：{res['error'].get('message')}"}
        await asyncio.sleep(1.5)  # 等首屏；重活（动态渲染）交给下一次 text/截图的等待
        title = await self._js("document.title")
        text = await self._text_now()
        self._last_url = url
        self._last_title = str(title or "")
        return {"url": url, "title": title, "text": text}

    async def _sync_location(self) -> None:
        """把"当前网址/标题"同步到看板用的缓存里。

        为什么需要：看板（``/state``）上的网址原来只在 ``goto()`` 里写一次，
        于是**点一个链接跳走之后，看板还停在上一个网址** —— 人看着那块牌子会以为
        她没动。实测：她点完 example.com 的 Learn more（已经跳到 iana.org），
        ``/state`` 里还是 ``https://example.com``。
        每次动手之后（点、填、读）都同步一次，牌子就跟得上。
        失败不算错 —— 页面正在跳转时读不到很正常，保留上一次的值即可。
        """
        try:
            here = await self._js("location.href")
            title = await self._js("document.title")
        except Exception:  # noqa: BLE001 - 同步不上不影响主流程
            return
        if here:
            self._last_url = str(here)
        if title is not None:
            self._last_title = str(title)

    async def _text_now(self, limit: int = 4000) -> str:
        raw = await self._js(
            "(() => { const b = document.body; return b ? b.innerText : ''; })()"
        )
        return str(raw or "")[:limit]

    async def text(self, limit: int = 4000) -> str:
        """读当前页面的可见文字。

        Args:
            limit: 最多返回多少字符。

        Returns:
            str: 页面正文（截断）。
        """
        await self.ensure()
        out = await self._text_now(limit)
        await self._sync_location()
        return out

    async def screenshot(self, path: pathlib.Path) -> int:
        """给当前页面截个图，存到 ``path``。

        Args:
            path: 目标 PNG 路径。

        Returns:
            int: 写出的字节数。

        Raises:
            RuntimeError: 截图没拿到数据。
        """
        await self.ensure()
        res = await self.call("Page.captureScreenshot", timeout=45.0, format="png")
        b64 = (res.get("result") or {}).get("data")
        if not b64:
            raise RuntimeError(f"截图失败：{json.dumps(res)[:200]}")
        data = base64.b64decode(b64)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return len(data)

    async def watch_on(self, quality: int = 70) -> None:
        """开始把画面**持续**推给我（CDP 的 ``Page.startScreencast``）。

        为什么不用定时截图：截图有延迟、还会打断渲染；screencast 是浏览器**主动**推帧，
        又顺滑又省。帧在 :meth:`_read_loop` 里收（那是**事件**，不是响应），只留最新一张，
        给观察页取用。

        Args:
            quality: JPEG 质量（0-100），越小越省。
        """
        await self.ensure()
        with contextlib.suppress(Exception):
            await self.call(
                "Page.startScreencast",
                format="jpeg",
                quality=quality,
                maxWidth=1280,
                maxHeight=900,
                everyNthFrame=1,
            )
        self._casting = True
        # 从"现在"开始算静默：否则首帧还没到时，兜底轮询会立刻把它当成"哑了"。
        self._frame_at = time.monotonic()
        self._poll_warned = False
        self._poll_err = False
        self._polling = False
        if self._poller is None or self._poller.done():
            self._poller = asyncio.ensure_future(self._poll_frames())
        logger.info(
            "[nanxi 看板] 已请求 startScreencast，兜底轮询已挂上（poller=%s）",
            self.poller_state,
        )

    async def _poll_frames(self) -> None:
        """兜底推帧：**screencast 哑了就改成按秒截图**，保证看板不会卡在第 1 帧。

        为什么必须有它：`Page.startScreencast` 是**流控**的，而且实测在 headless 里
        它只在**页面加载/重绘**时推帧 —— 页面一静下来它就没声了（2026-10-05 实测：
        打开 example.com 之后 `seq` 永远停在 1，主人的看板就冻在那张画面上）。
        所以策略是**两条腿**：screencast 能推就白拿（顺滑、省），
        静默超过 :data:`_FRAME_SILENT` 秒就自己 `Page.captureScreenshot` 接着推。
        截图这条路是**验过能用**的 —— `web_look` 走的正是它。

        ⚠️ 一旦接管就按**稳定 1 fps** 走，而不是"截一张再等 3 秒"：
        后者会让看板 3 秒才动一下。等 screencast 重新推帧了（导航/重绘时它会活过来），
        `_frame_src` 一变成 ``screencast`` 就让位。
        """
        logger.info("[nanxi 看板] 兜底轮询启动（casting=%s）", self._casting)
        while self._casting:
            await asyncio.sleep(1.0)
            if not self._casting:
                logger.info("[nanxi 看板] 兜底轮询退出：casting 变成 False")
                break
            if self._ws is None or self._ws.closed:
                logger.info("[nanxi 看板] 兜底轮询退出：CDP 连接没了")
                break
            silent = time.monotonic() - self._frame_at
            if silent >= _FRAME_SILENT:
                self._polling = True
            elif self._frame_src == "screencast":
                # screencast 又活过来了 —— 让位给它，我们不再插一脚。
                self._polling = False
            if not self._polling:
                continue
            # 没人看就不截：看板只在被人打开时才有意义（页面每 700ms 打一次 /state）。
            # 30 秒的宽限是为了"人刚关掉页面"和"网络抖了一下"不来回切换。
            if time.monotonic() - self._viewer_at > _VIEWER_GRACE:
                continue
            if not self._poll_warned:
                self._poll_warned = True
                logger.info(
                    "[nanxi 看板] screencast 静默 %.1f 秒，改用轮询截图兜底", silent
                )
            try:
                res = await self.call(
                    "Page.captureScreenshot", timeout=10.0, format="jpeg", quality=60
                )
            except Exception as exc:  # noqa: BLE001 - 兜底失败不影响主流程，下一轮再试
                if not self._poll_err:
                    self._poll_err = True
                    logger.warning(f"[nanxi 看板] 兜底截图失败（之后不再重复报）：{exc}")
                continue
            b64 = (res.get("result") or {}).get("data")
            if not b64:
                if not self._poll_err:
                    self._poll_err = True
                    logger.warning(
                        "[nanxi 看板] 兜底截图没拿到数据："
                        + json.dumps(res, ensure_ascii=False)[:200]
                    )
                continue
            with contextlib.suppress(Exception):
                self._frame = base64.b64decode(b64)
                self._frame_seq += 1
                self._frame_at = time.monotonic()
                self._frame_src = "poll"
        logger.info("[nanxi 看板] 兜底轮询结束")

    @property
    def casting(self) -> bool:
        """是否已经在往观察窗推帧。"""
        return self._casting

    async def watch_off(self) -> None:
        """停止推帧（幂等）。"""
        self._casting = False
        if self._poller is not None:
            self._poller.cancel()
            self._poller = None
        with contextlib.suppress(Exception):
            await self.call("Page.stopScreencast")

    @property
    def frame(self) -> bytes | None:
        """最新一帧（JPEG 字节）；还没收到帧时是 None。"""
        return self._frame

    @property
    def cursor(self) -> dict[str, float] | None:
        """最近一次操作落点（归一化 0..1），用来在画面上画"鼠标在哪"。"""
        return self._cursor

    async def click(self, target: str) -> str:
        """点击页面上匹配的元素 —— 先当 CSS 选择器找，找不到再按可见文字找。

        ⚠️ 用的是 **CDP 的真实鼠标事件**（`Input.dispatchMouseEvent`），不是 JS 的
        `el.click()`。这一点是照 `dsh-ego-browser` 抄的，它源码里写着
        *"Input.dispatchMouseEvent, exactly like Playwright"*。区别很实际：
          - `el.click()` 是**程序化点击** —— React/Vue 的很多控件只认真实指针事件，
            点了没反应；它还会**绕过命中测试**，点到"其实被别的层盖住"的元素上。
          - 真实鼠标事件走完整的命中测试，跟人拿鼠标点是一样的。
        另外它源码里还记了一条：*"Input.dispatchMouseEvent can hang waiting for a frame
        that never comes"* —— 所以这里每一步都给超时，卡住就报错，不干等。

        Args:
            target: CSS 选择器（如 ``#submit``）或元素上的可见文字（如 ``登录``）。

        Returns:
            str: 一句中文结果说明（成功点了什么 / 没找到 / 不可见）。
        """
        await self.ensure()
        # 第一步：找元素，并**挑一个真正落在它身上的落点**。
        # 三处比原来强：
        #   ① 搜索面更大 —— 很多 UI 用 div/span + role/onclick/tabindex 做按钮。
        #   ② 命中**文字最短**的那个 —— 取"最小、最具体"的元素，而不是外层大容器。
        #   ③ **落点做命中测试**（关键）：原来直接取元素中心，而很多界面的行尾会
        #      绝对定位一个「…」菜单按钮 —— 元素中心一算就砸在那个按钮上（南汐实测：
        #      "我一按「nx_dsh」这三个字，落点就正好砸在那个「…」上"）。
        #      现在从中心开始试，用 elementFromPoint 验证"底下确实是它（或它的子孙）"，
        #      不成就往左/上退，实在都不行才退回中心。
        js = (
            "(() => {"
            " const t = %s;"
            " const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim();"
            " const needle = norm(t);"
            " const hasText = (el) => {"
            "   const s = norm(el.innerText || el.textContent);"
            "   return s.length > 0 && s.indexOf(needle) >= 0;"
            " };"
            " let el = null;"
            " try { el = document.querySelector(t) } catch (e) {}"
            # 第二步：按可见文字找 —— 扫**所有**元素，取"最内层"那个。
            # 这一条是照 `dsh-ego-browser` 的 `textElementsExpression()` 抄的：
            #   ① 它查的是 `document.querySelectorAll('body *')`，**不是**只查交互元素；
            #   ② 它用「子孙里没有也匹配的」把结果收敛到最内层那个叶子
            #      （`!Array.from(el.children).some(child => childMatch(child))`）；
            #   ③ 比较前先 `replace(/\s+/g,' ').trim()` 归一化空白。
            # 为什么必须这样：只搜 a/button/[role] 会**漏掉裸 span 里的文字** ——
            # 实测 `web_click('nx_dsh')` 就是这么失败的（那个名字是个裸 span，
            # 而它右边的「…」按钮的 aria-label 里**也**含 "nx_dsh 的更多操作"，
            # 所以第三步那种"最短可访问名字"的挑法单独用会点到「…」上）。
            " if (!el && needle) {"
            "   const cands = [];"
            "   for (const n of document.querySelectorAll('body *')) {"
            "     if (!hasText(n)) continue;"
            "     if (Array.from(n.children || []).some((c) => hasText(c))) continue;"
            "     cands.push(n);"
            "   }"
            # 多个叶子都命中时（比如列表里重复的行），取**文字最短**、再取**面积最小**的，
            # 尽量落在"最小、最具体"的那个元素上。
            "   cands.sort((a, b) => {"
            "     const la = norm(a.innerText || a.textContent).length;"
            "     const lb = norm(b.innerText || b.textContent).length;"
            "     if (la !== lb) return la - lb;"
            "     const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();"
            "     return ra.width * ra.height - rb.width * rb.height;"
            "   });"
            "   el = cands[0] || null;"
            " }"
            # 第三步：兜底找"可访问名字"（aria-label / title / placeholder / value）。
            # 有些控件**没有可见文字**，名字只挂在属性上 —— 那只有这一步能捞到。
            " if (!el) {"
            "   const sel = 'a,button,input,textarea,select,summary,label,'"
            "     + '[role],[onclick],[tabindex]:not([tabindex=\"-1\"]),[contenteditable=true]';"
            "   let best = null, bestLen = 1e9;"
            "   for (const n of document.querySelectorAll(sel)) {"
            "     const s = ((n.innerText || n.value || n.getAttribute('aria-label')"
            "       || n.getAttribute('title') || n.getAttribute('placeholder') || '') + '').trim();"
            "     if (!s || !s.includes(t)) continue;"
            "     if (s.length < bestLen) { best = n; bestLen = s.length }"
            "   }"
            "   el = best;"
            " }"
            " if (!el) return 'not-found';"
            " el.scrollIntoView({block:'center', inline:'center'});"
            " const r = el.getBoundingClientRect();"
            " if (r.width <= 0 || r.height <= 0) return 'zero-size';"
            # 候选落点：中心 → 左侧 25% → 左侧 12% → 上方 25%（越靠前越"正常"）
            " const cands = ["
            "   [r.left + r.width*0.5,  r.top + r.height*0.5],"
            "   [r.left + r.width*0.25, r.top + r.height*0.5],"
            "   [r.left + r.width*0.12, r.top + r.height*0.5],"
            "   [r.left + r.width*0.5,  r.top + r.height*0.25],"
            " ];"
            " let px = cands[0][0], py = cands[0][1], hitNote = '';"
            " for (const [cx, cy] of cands) {"
            "   if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) continue;"
            "   const hit = document.elementFromPoint(cx, cy);"
            "   if (!hit) continue;"
            "   if (hit === el || el.contains(hit) || hit.contains(el)) { px = cx; py = cy; break }"
            "   hitNote = hit.tagName + ':' + ((hit.innerText||hit.getAttribute('aria-label')||'')+'').trim().slice(0,20);"
            " }"
            " return JSON.stringify({"
            "   tag: el.tagName,"
            "   text: ((el.innerText||el.value||el.getAttribute('aria-label')||'')+'').trim().slice(0,40),"
            "   px: px, py: py,"
            "   blocked: hitNote,"
            "   vw: Math.max(1, window.innerWidth), vh: Math.max(1, window.innerHeight),"
            " });"
            "})()"
        ) % json.dumps(target)
        got = await self._js(js)
        if got == "not-found":
            return f"页面上没找到「{target}」（既不是 CSS 选择器，也没有这段可见文字）"
        if got == "zero-size":
            return f"「{target}」在页面上是不可见的（尺寸为 0），点不到"
        info = json.loads(got)
        px, py = float(info["px"]), float(info["py"])
        # 第二步：真实鼠标 —— 移动 → 按下 → 抬起（顺序不能省：只发 pressed/released
        # 有些控件收不到 hover 状态；只发 moved 就不是点击了）。
        for mtype, extra in (
            ("mouseMoved", {}),
            ("mousePressed", {"button": "left", "clickCount": 1}),
            ("mouseReleased", {"button": "left", "clickCount": 1}),
        ):
            await self.call("Input.dispatchMouseEvent", timeout=8.0, type=mtype, x=px, y=py, **extra)
        await asyncio.sleep(1.2)
        # 记下她点在哪：看板据此画红点（headless 的帧里没有光标，红点是画上去的）。
        self._cursor = {
            "x": px / max(1.0, float(info["vw"])),
            "y": py / max(1.0, float(info["vh"])),
        }
        # 点一下很可能就跳走了 —— 立刻把看板上的网址/标题对齐（否则牌子停在旧页面）。
        await self._sync_location()
        return f"点了 {info['tag']}:{info['text']}"

    async def click_at(self, x: float, y: float) -> str:
        """在**视口坐标**（CSS 像素）上点一下 —— 给"看得见图、知道大概位置"时用。

        它不做元素查找，**直接用真实鼠标事件点那个坐标**，所以能点到那些
        选择器/文字都定位不到的东西（canvas、图标按钮、地图上的点）。

        Args:
            x: 视口横坐标（CSS 像素，从左边算）。
            y: 视口纵坐标（CSS 像素，从上边算）。

        Returns:
            str: 一句中文结果说明；坐标落在窗口外会如实拒绝。
        """
        await self.ensure()
        info = await self._js(
            "JSON.stringify({vw: Math.max(1, window.innerWidth), vh: Math.max(1, window.innerHeight)})"
        )
        vw, vh = 1.0, 1.0
        with contextlib.suppress(Exception):
            d = json.loads(info) if isinstance(info, str) else {}
            vw, vh = float(d.get("vw") or 1), float(d.get("vh") or 1)
        if not (0 <= x <= vw and 0 <= y <= vh):
            return f"坐标 ({x:.0f}, {y:.0f}) 不在当前视口里（视口是 {vw:.0f}×{vh:.0f}）"
        # 先看看那个点底下是什么 —— 方便她/我们判断点对了没有（返回文字，不当成失败）
        what = await self._js(
            "(() => { const el = document.elementFromPoint(%s, %s);"
            " if (!el) return '';"
            " return (el.tagName + ':' + ((el.innerText||el.value||el.getAttribute('aria-label')||'')+'')"
            ".trim().slice(0,40)); })()" % (x, y)
        )
        for mtype, extra in (
            ("mouseMoved", {}),
            ("mousePressed", {"button": "left", "clickCount": 1}),
            ("mouseReleased", {"button": "left", "clickCount": 1}),
        ):
            await self.call("Input.dispatchMouseEvent", timeout=8.0, type=mtype, x=x, y=y, **extra)
        await asyncio.sleep(1.0)
        self._cursor = {"x": x / vw, "y": y / vh}
        await self._sync_location()
        return f"在 ({x:.0f}, {y:.0f}) 点了一下，那里是 {what or '（取不到元素）'}"

    async def type_text(self, target: str, value: str) -> str:
        """往输入框里填字 —— 先当 CSS 选择器找，找不到再按 placeholder/名字/文字找。

        Args:
            target: CSS 选择器，或输入框的 placeholder / name / 邻近文字。
            value: 要填进去的内容。

        Returns:
            str: 一句中文结果说明。
        """
        await self.ensure()
        # 第一步：找到输入框，并把焦点真正交到它手上（用真实鼠标点一下）。
        # 为什么不沿用 `el.focus()` + `el.value = v`：那是"程序化赋值"，React/Vue
        # 的受控输入框经常**不认**（它们盯着真实的 input 事件链）。这跟 click 那个坑同源。
        js = (
            "(() => { const t = %s;"
            " let el = null;"
            " try { el = document.querySelector(t) } catch (e) {}"
            " if (!el) {"
            "   const all = document.querySelectorAll("
            "     'input:not([type=hidden]),textarea,[contenteditable=true],[role=textbox]');"
            "   for (const n of all) {"
            "     const s = ((n.placeholder||n.name||n.id||n.getAttribute('aria-label')||'')+'');"
            "     if (s && s.includes(t)) { el = n; break }"
            "   }"
            " }"
            " if (!el) return 'not-found';"
            " el.scrollIntoView({block:'center', inline:'center'});"
            " const r = el.getBoundingClientRect();"
            " if (r.width <= 0 || r.height <= 0) return 'zero-size';"
            " return JSON.stringify({"
            "   tag: el.tagName,"
            "   text: ((el.placeholder||el.name||el.id||el.getAttribute('aria-label')||'')+'').slice(0,40),"
            "   px: r.left + r.width/2, py: r.top + r.height/2,"
            "   vw: Math.max(1, window.innerWidth), vh: Math.max(1, window.innerHeight),"
            " });"
            "})()"
        ) % json.dumps(target)
        got = await self._js(js)
        if got == "not-found":
            return f"页面上没找到输入框「{target}」"
        if got == "zero-size":
            return f"输入框「{target}」在页面上不可见（尺寸为 0）"
        info = json.loads(got)
        px, py = float(info["px"]), float(info["py"])
        # 用真实鼠标点进输入框（拿到焦点）
        for mtype, extra in (
            ("mouseMoved", {}),
            ("mousePressed", {"button": "left", "clickCount": 1}),
            ("mouseReleased", {"button": "left", "clickCount": 1}),
        ):
            await self.call("Input.dispatchMouseEvent", timeout=8.0, type=mtype, x=px, y=py, **extra)
        # 第二步：清空已有内容（Ctrl+A 后按 Backspace —— 真实键盘事件，不是改 value）
        with contextlib.suppress(Exception):
            for ktype, extra in (
                ("keyDown", {"key": "a", "code": "KeyA", "modifiers": 2}),  # 2 = Ctrl
                ("keyUp", {"key": "a", "code": "KeyA", "modifiers": 2}),
                ("keyDown", {"key": "Backspace", "code": "Backspace"}),
                ("keyUp", {"key": "Backspace", "code": "Backspace"}),
            ):
                await self.call("Input.dispatchKeyEvent", timeout=8.0, type=ktype, **extra)
        # 第三步：用 CDP 的 insertText 真正"打字"进去（框架收到的是真实文本输入）
        await self.call("Input.insertText", timeout=10.0, text=value)
        await asyncio.sleep(0.6)
        self._cursor = {
            "x": px / max(1.0, float(info["vw"])),
            "y": py / max(1.0, float(info["vh"])),
        }
        await self._sync_location()
        return f"已往 {info['tag']}:{info['text']} 填了 {len(value)} 个字"
