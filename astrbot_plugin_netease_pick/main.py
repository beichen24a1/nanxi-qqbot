# -*- coding: utf-8 -*-
"""网易云点歌 —— 引用一条含网易云链接的消息 + @南汐，就把那首歌下载发到群里。

## 为什么自己写（2026-10-06 调研过现成的）
社区里点歌插件不少，但**清一色走「第三方 API + key/cookie」路线**：
  · `Aoi-Karlin/astrbot_plugin_netease_music_pro_max` —— 要自建 NeteaseCloudMusicApi + 导入 Cookies
  · `Dayanshifu/astrbot_plugin_music_pro`            —— 要注册第三方 API key（柠柚）+ 公开音源站
  · `ApproLight01/astrbot_netease_mus`               —— 只把 id 解析成文本发出来，不下载
而本插件走**官方直链**：``http://music.163.com/song/media/outer/url?id=<歌曲ID>.mp3``
**零依赖、免 key、免登录**，不会因为第三方服务挂掉而失效。
代价：拿不到 VIP / 版权受限的歌（那些只能靠登录态 + 别的接口）。

## 实测出来的坑（都踩过，别再踩）
1. **必须带浏览器 User-Agent**：aiohttp/urllib 的默认 UA 会被网易云拒掉，
   返回 83 字节 JSON ``{"code":-460,"message":"检测到您的网络环境存在风险…"}``；
   带 UA 才是 3.5 MB 的 audio/mpeg。
2. **HTTP 200 完全不可信**：
   · 歌不存在/下架 → 200 + ``text/html`` 的 404 页面（~104 KB）
   · UA 不对       → 200 + ``application/json`` 的 -460 错误（83 字节）
   ⇒ 必须**三个判据一起卡**：Content-Type 是 ``audio/*``、
     最终 URL 落到了 ``music.126.net`` CDN、体积够大。
3. **短链要先跟随重定向**：群友分享的多半是 ``https://163cn.tv/xxxx``，它本身不含 id；
   302 之后才是 ``y.music.163.com/m/song?id=xxx``。
4. **被引用的消息在 ``Reply`` 段里，而且 ``Reply.text`` 直接是被引用消息的全文**
   （实测 dump：``Reply{text:"https://163cn.tv/bhu1nHlF", qq:"…", chain:[Plain{…}]}``），
   不用去遍历 chain。
5. **`async def` 处理器里「多次 `yield` + 中间干活」是行不通的** —— AstrBot 在
   `stop_event()` 之后**不再往下迭代生成器**，于是「收到喵」发出去了、后面的下载代码
   **一行没跑**（日志里连一条 `[netease]` 都没有，最坑的是它**不报错**）。
   petpet 那种「stop + 只 yield 一次」才是安全形态。
   ⇒ 中间反馈一律用 ``await event.send(MessageChain([...]))`` 主动发，**最后只 yield 一次**。
6. **AstrBot 的 `File`（群文件）组件在「AstrBot 在宿主机、OneBot 在容器」的架构下必然失败。**
   它的 ``file`` 是个 property，会在 **AstrBot 本机** ``os.path.exists()`` 检查：
   容器内路径在宿主机不存在 ⇒ 返回空串 ⇒ 发出去的是 ``{'type':'file','data':{'file':''}}``
   ⇒ ``retcode=1400 message segment "file" is missing required or usable fields``。
   **发群文件只能用 OneBot 的 ``upload_group_file``**（读容器内路径，所以要 ``docker cp``）。
7. **`Record` 是安全的**：适配器对 ``Image | Record`` 走的是
   ``convert_to_base64()`` → ``file: "base64://…"``，**与两边文件系统无关**，
   传宿主机路径即可。实测一首 229 秒 / 3.5 MB 的歌当语音发出去没被平台拒。

## 触发方式
``@南汐`` + **引用**一条含网易云链接的消息。群聊必须 @（`event.is_at_or_wake_command` 把关），
所以链接单纯发在群里不会被理。带一层**每群冷却**防刷屏。
"""

import asyncio
import re
import time
from pathlib import Path

import aiohttp

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.message_components import Plain, Record, Reply
from astrbot.core.star.star_tools import StarTools

#: 浏览器 UA —— **不能省**，见模块 docstring 的坑 1。
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

#: 从一段文本里抠出所有 http(s) 链接（网易云分享文本里长这样：
#: `分享XXX的单曲《YYY》: https://163cn.tv/zzz (来自@网易云音乐)`）。
LINK_RE = re.compile(r"https?://[^\s\"'<>()（）【】]+")
#: 歌曲 id：`?id=123` / `&id=123`
ID_RE = re.compile(r"[?&]id=(\d+)")
#: 短链域名（本身不含 id，必须跟随重定向）
SHORT_HOSTS = ("163cn.tv",)
#: 认可的网易云域名（避免去解析无关链接）
NETEASE_HOSTS = (
    "music.163.com",
    "y.music.163.com",
    "163cn.tv",
    "music.126.net",
)
#: 下载地址模板 —— 主人给的、也是官方那个"外链播放"接口。
OUTER_URL = "http://music.163.com/song/media/outer/url?id={sid}.mp3"

#: 音频体积下限：比这还小的一律当失败（真歌至少几百 KB；错误页 ~104 KB）。
MIN_AUDIO_BYTES = 200 * 1024
#: 下载超时（秒）
DOWNLOAD_TIMEOUT = 90
#: 每群冷却（秒），防刷屏
COOLDOWN_SECONDS = 20


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        #: 上一次响应时间，按 unified_msg_origin 记（简单冷却，不必持久化）
        self._last_reply: dict[str, float] = {}

    # ---- 主入口 --------------------------------------------------------

    @filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """只在「被 @ + 引用了含网易云链接的消息」时动手。

        ⚠️ **中间反馈必须用 `await event.send()`，不能 `yield`。**
        实测踩过：写成 `async def` + 多次 `yield` 时，AstrBot 在 `stop_event()`
        之后就不再往下迭代生成器了 —— 于是"收到喵"发出去了，**后面的下载代码一行没跑**
        （日志里连一条 `[netease]` 都没有）。petpet 那种"stop + 只 yield 一次"才是安全的。
        所以这里：中间状态用 `await event.send(...)` 主动发，**最后只 yield 一次**（发歌）。
        """
        if not event.is_at_or_wake_command:
            return

        reply = next(
            (seg for seg in (event.message_obj.message or []) if isinstance(seg, Reply)),
            None,
        )
        if reply is None:
            return

        text = self._reply_text(reply)
        if not text:
            return
        url = self._pick_netease_url(text)
        if not url:
            return

        async def say(msg: str) -> None:
            """中间反馈：主动发送，不占用 yield。"""
            await event.send(MessageChain([Plain(msg)]))

        umo = event.unified_msg_origin
        now = time.monotonic()
        last = self._last_reply.get(umo, 0.0)
        if now - last < COOLDOWN_SECONDS:
            left = int(COOLDOWN_SECONDS - (now - last))
            await say(f"喵…刚点过一首，{left} 秒后再来 ｀へ´*")
            event.stop_event()
            return
        self._last_reply[umo] = now

        await say("收到喵，去找这首歌…")

        try:
            song_id = await self._resolve_song_id(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[netease] 解析链接失败 {url}: {exc}")
            await say("这个链接我打不开喵(´・ω・`)")
            event.stop_event()
            return
        if not song_id:
            await say("这个链接里没找着歌曲 id 喵…")
            event.stop_event()
            return

        try:
            path, size = await self._download(song_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[netease] 下载失败 id={song_id}: {exc}")
            await say(
                f"这首下不了喵 —— {exc}\n"
                "（多半是 VIP / 版权受限，官方外链接口只给能免费听的歌）"
            )
            event.stop_event()
            return

        name = f"{song_id}.mp3"
        logger.info(f"[netease] id={song_id} 下载完成 {size} 字节 -> {path}")

        # 发送。两条路都实测过（2026-10-06，测试群）：
        #   · record —— 走 AstrBot 的 Record 组件。适配器对 `Image | Record` 会
        #     **读成本地文件转 base64 内联**（`aiocqhttp_message_event._from_segment_to_dict`），
        #     所以传**宿主机路径**即可，不受跨文件系统影响；群里显示为可播放的语音。
        #     实测一首 229 秒 / 3.5 MB 的歌照样发得出去。
        #   · file   —— 走 OneBot 的 `upload_group_file`：它读的是**容器内**路径，
        #     所以必须先 `docker cp` 进去。群里显示为群文件（可下载、留存）。
        # ⚠️ 千万别用 AstrBot 的 `File` 组件 —— 它的 `file` 是个 property，会在
        #    **AstrBot 本机** `os.path.exists()` 检查，而容器内路径在宿主机不存在
        #    ⇒ 返回空串 ⇒ `retcode=1400 message segment "file" is missing required or usable fields`
        #    （2026-10-06 实测踩过，日志里能看到发出去的 `'file': ''`）。
        want = str(self._cfg("send_as", "record") or "record").lower()
        try:
            if want == "file":
                remote = await self._publish_to_container(path, song_id)
                await event.bot.call_action(
                    "upload_group_file",
                    group_id=event.get_group_id(),
                    file=remote,
                    name=name,
                )
                logger.info(f"[netease] 已用群文件发出 id={song_id}")
                event.stop_event()
                return
            # 默认：语音（Record 组件，宿主机路径即可）
            event.stop_event()
            yield event.chain_result([Record(file=str(path))])
            logger.info(f"[netease] 已用语音发出 id={song_id}")
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[netease] 发送失败（{want}）：{exc}")
            await say(f"下是下好了，可发不进群里喵…(´・ω・`)\n{exc}")
            event.stop_event()

    # ---- 各种小工具 ----------------------------------------------------

    def _cfg(self, key: str, default):
        """读插件配置；读不到就回默认值（不能因为配置缺失就不干活）。"""
        try:
            conf = self.context.get_config()
            if hasattr(conf, "get"):
                sub = conf.get("astrbot_plugin_netease_pick")
                if isinstance(sub, dict) and key in sub:
                    return sub[key]
                if key in conf:
                    return conf[key]
        except Exception:  # noqa: BLE001
            pass
        return default

    @staticmethod
    def _reply_text(reply) -> str:
        """把被引用消息的文字拼出来。

        ``Reply.text`` 通常直接就是全文（实测如此）；没有的话退回去遍历 ``chain``。
        """
        parts: list[str] = []
        direct = getattr(reply, "text", None)
        if direct:
            parts.append(str(direct))
        for seg in getattr(reply, "chain", None) or []:
            if isinstance(seg, Plain) and seg.text:
                parts.append(str(seg.text))
            else:
                for attr in ("text", "name", "url"):
                    val = getattr(seg, attr, None)
                    if isinstance(val, str) and val:
                        parts.append(val)
        return "\n".join(parts)

    @staticmethod
    def _pick_netease_url(text: str) -> str | None:
        """从一段文本里挑出第一个网易云链接。"""
        for url in LINK_RE.findall(text):
            low = url.lower()
            if any(host in low for host in NETEASE_HOSTS):
                return url.rstrip(".,;，。；")
        return None

    async def _resolve_song_id(self, url: str) -> str | None:
        """拿到歌曲 id：直接链就地提取；短链先跟随重定向。"""
        m = ID_RE.search(url)
        if m:
            return m.group(1)
        if not any(host in url.lower() for host in SHORT_HOSTS):
            return None
        # 短链：只看重定向，不下载页面正文
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": UA},
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                final = str(resp.url)
        logger.info(f"[netease] 短链解析：{url} -> {final[:120]}")
        m = ID_RE.search(final)
        return m.group(1) if m else None

    async def _download(self, song_id: str) -> tuple[Path, int]:
        """下载 mp3 并**验证它真是音频**（HTTP 200 不可信，见模块 docstring 坑 2）。

        Returns:
            tuple: ``(本地路径, 字节数)``。

        Raises:
            RuntimeError: 拿到的东西不像音频（文案会直接回给群友，所以写人话）。
        """
        url = OUTER_URL.format(sid=song_id)
        out_dir = StarTools.get_data_dir("astrbot_plugin_netease_pick") / "cache"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{song_id}.mp3"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": UA},
                timeout=aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT),
            ) as resp:
                ctype = str(resp.headers.get("Content-Type") or "")
                final = str(resp.url)
                data = await resp.read()

        if not ctype.startswith("audio/"):
            raise RuntimeError(f"接口没给音频（{ctype or '未知类型'}）")
        if "music.126.net" not in final:
            raise RuntimeError("没跳到 CDN，多半是空壳")
        if len(data) < MIN_AUDIO_BYTES:
            raise RuntimeError(f"文件太小（{len(data)} 字节）")

        out.write_bytes(data)
        self._cleanup(out_dir)
        return out, len(data)

    async def _publish_to_container(self, local: Path, song_id: str) -> str:
        """把下载好的文件送进 QQ 容器，返回**容器内**路径。

        ⚠️ **这一步不能省。** 本项目的三件套是跨文件系统的：
          · AstrBot 跑在**宿主机**（下载的文件在 `D:\\dsh\\QQbot\\...`）
          · OneBot（SnowLuma）跑在 **Docker 容器**里，而容器的挂载**全是命名卷**
            （`/var/lib/docker/volumes/...`），**没有绑定任何宿主目录**
        ⇒ 把宿主机路径直接交给 OneBot，它会报
          `ActionFailed retcode=100: ENOENT: no such file or directory, realpath 'D:/dsh/...'`
          （2026-10-06 实测踩过，日志里就这一行）。
        所以先把文件 `docker cp` 进容器，再把**容器内路径**发出去。

        Args:
            local: 宿主机上的文件路径。
            song_id: 歌曲 id，用来给容器内文件起名。

        Returns:
            str: 容器内路径（如 ``/tmp/nanxi-song-3410744228.mp3``）。

        Raises:
            RuntimeError: `docker cp` 失败（带 stderr 片段）。
        """
        container = str(self._cfg("container", "snowluma") or "snowluma")
        remote = f"/tmp/nanxi-song-{song_id}.mp3"
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "cp",
            str(local),
            f"{container}:{remote}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"docker cp 失败({proc.returncode}): "
                f"{err.decode('utf-8', 'replace')[:200]}"
            )
        return remote

    @staticmethod
    def _cleanup(out_dir: Path, keep_seconds: int = 3600) -> None:
        """清掉过期缓存，别让目录无限长。"""
        deadline = time.time() - keep_seconds
        for f in out_dir.glob("*.mp3"):
            try:
                if f.stat().st_mtime < deadline:
                    f.unlink()
            except OSError:
                pass
