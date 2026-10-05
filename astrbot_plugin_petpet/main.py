# -*- coding: utf-8 -*-
"""摸头杀（petpet）插件 —— @南汐 说「摸摸 / 摸头 / 摸摸头」即生成摸头 GIF。

触发方式（@ 的位置不限，带不带 `/` 都行）：
    @南汐 摸摸
    @用户 @南汐 摸摸
    @用户 摸摸 @南汐
    @南汐 @用户 摸摸
    @南汐 /摸摸            ← / 唤醒前缀同样支持

群聊里必须 @ 南汐 或使用 `/` 前缀（即 AstrBot 的唤醒判定），否则只含"摸摸"的
闲聊不会被理会 —— 这一点靠 `event.is_at_or_wake_command` 把关。

图片来源优先级：
  1. 引用的消息里的图片（推荐：引用一张图 + 摸摸）
  2. 本条消息里直接发的图片
  3. 被 @ 的人的头像
  4. 发送者自己的头像

回复只有一张 GIF，不带任何文字。
渲染算法见同目录 petpet_render.py（Pillow 复刻 toolwa.com/petpet 网页版）。
"""

import asyncio
import re
import sys
import time
from pathlib import Path

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Image, Reply
from astrbot.core.star.star_tools import StarTools

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

import petpet_render  # noqa: E402

AVATAR_URL = "https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640"
KEEP_SECONDS = 3600  # 生成的 GIF 保留时长，超过即在下次生成时清理

# 触发词：摸摸 / 摸头 / 摸摸头 / 拍头 / petpet / rua。
# 前后都要求词边界（行首行尾、空白、`/`、`@`），这样 gradual 这类含 "rua" 的
# 英文单词不会被误伤；用 search 而非 match，所以 @ 在前面也无所谓。
PETPET_PATTERN = re.compile(
    r"(?:^|[\s/])(?:摸摸头|摸摸|摸头|拍头|petpet|rua)(?=$|[\s/@])",
    re.IGNORECASE,
)


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context

    @filter.regex(PETPET_PATTERN)
    async def petpet(self, event: AstrMessageEvent):
        """生成摸头 GIF，只回复图片。"""
        # 唤醒判定：群聊里必须 @南汐 或用 `/` 前缀，否则这条"摸摸"只是闲聊
        if not event.is_at_or_wake_command:
            return

        try:
            image = await self._pick_image(event)
            src = await image.convert_to_file_path()
            out_dir = StarTools.get_data_dir("astrbot_plugin_petpet") / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            # PIL 合成是 CPU 密集操作，放线程里跑，别阻塞事件循环
            gif = await asyncio.to_thread(
                petpet_render.make_gif,
                src,
                out_dir / f"petpet_{int(time.time() * 1000)}.gif",
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[petpet] 生成摸头 GIF 失败: {e}")
            event.stop_event()
            yield event.plain_result("呜…这张图南汐摸不动喵(´・ω・`)")
            return

        self._cleanup(out_dir)
        # 拦下事件，避免南汐再走一遍 LLM 聊天流程多说一句
        event.stop_event()
        yield event.image_result(str(gif))

    async def _pick_image(self, event: AstrMessageEvent) -> Image:
        """按优先级挑出要摸的图。

        Args:
            event: 当前消息事件。

        Returns:
            可直接交给 convert_to_file_path 处理的 Image 组件。
        """
        at_qq = None
        #: 本平台机器人自己的 QQ —— 从事件里取，**不要硬编码**。
        #: 硬编码有两个毛病：换号/多机器人就得改代码；而且会把号码写进公开仓库。
        self_qq = str(getattr(event, "get_self_id", lambda: "")() or "")
        for seg in event.message_obj.message or []:
            if isinstance(seg, Reply):
                # aiocqhttp 适配器已把被引用消息的完整消息链放进 Reply.chain
                for sub in seg.chain or []:
                    if isinstance(sub, Image):
                        return sub
            elif isinstance(seg, Image):
                return seg
            elif isinstance(seg, At):
                qq = getattr(seg, "qq", None)
                # 排除 @全体成员 和 @机器人自己（否则会变成摸自己的头）
                if qq and str(qq) not in ("all", self_qq):
                    at_qq = qq
        return Image.fromURL(AVATAR_URL.format(qq=at_qq or event.get_sender_id()))

    @staticmethod
    def _cleanup(out_dir: Path) -> None:
        """清理过期 GIF，避免输出目录无限增长。

        Args:
            out_dir: GIF 输出目录。
        """
        deadline = time.time() - KEEP_SECONDS
        for old in out_dir.glob("*.gif"):
            try:
                if old.stat().st_mtime < deadline:
                    old.unlink()
            except OSError:
                pass
