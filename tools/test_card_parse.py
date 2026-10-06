# -*- coding: utf-8 -*-
"""离线单测：验证点歌插件能从「网易云音乐卡片」里提出歌曲 id 和歌名。

## 为什么需要它（而不是靠 QQ 实测）
引用卡片这条路在本机**走不通**，两个原因都实测过：
  1. `send_group_msg` 返回的 message_id 对 **json 段**消息**不能用于 reply** ——
     SnowLuma 会把 reply 整段丢掉，日志里那条消息只剩 `[At:…]`；
  2. 而从 `get_group_msg_history` 也捞不到刚发的那条卡片。
   （顺带一个更普遍的坑：本机的 message_id 会**漂移** —— 隔一会儿拿同一个 id 去引用，
     会引用到**另一条**消息上，所以"引用群里那条旧卡片"根本不可靠。）
所以这里直接把**真实的卡片结构**喂给插件的解析函数，快且可重复。

卡片结构是 2026-10-06 从测试群 `get_group_msg_history` 里抓的原样：
    {"type":"json","data":{"data":"{\\"app\\":\\"com.tencent.music.lua\\",…,\\"meta\\":
      {\\"music\\":{\\"title\\":\\"兄弟难当\\",\\"desc\\":\\"杜歌\\",
                  \\"jumpUrl\\":\\"https://y.music.163.com/m/song?id=26545127&…\\"}}}"}}

跑法（需要仓库里 `astrbot/data/site-packages` 提供的 aiohttp）：::

    C:\\Python310\\python.exe tools\\test_card_parse.py
"""
import json
import logging
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: 插件目录：本项目的开发仓里它在 `REPO/astrbot_plugin_netease_pick`；
#: 独立发布仓（本文件在 `tests/`）里**仓根就是插件目录**，`main.py` 就在旁边。
PLUGIN_DIR = HERE.parent
if not (PLUGIN_DIR / "main.py").is_file():
    PLUGIN_DIR = HERE.parent / "astrbot_plugin_netease_pick"
#: aiohttp 的来源：本项目把它放在 `astrbot/data/site-packages`；
#: 独立仓 / 系统 Python 里没有这一层也无所谓 —— 找不到就用解释器自己的。
SITE = HERE.parent / "astrbot" / "data" / "site-packages"

logging.basicConfig(level=logging.CRITICAL)


def _mock_astrbot() -> None:
    """塞进最小可用的假 astrbot 模块树，好让插件的 import 过得去。"""
    root = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = logging.getLogger("mock")
    api.star = types.SimpleNamespace(Star=object, Context=object)
    root.api = api

    event = types.ModuleType("astrbot.api.event")

    class _Event:
        pass

    class _Chain(list):
        pass

    def _deco(*_a, **_kw):
        """假的过滤器装饰器：原样返回函数就行，这里只关心解析逻辑。"""

        def wrap(fn):
            return fn

        return wrap

    event.AstrMessageEvent = _Event
    event.MessageChain = _Chain
    event.filter = types.SimpleNamespace(
        event_message_type=_deco, regex=_deco, command=_deco
    )

    ev_filter = types.ModuleType("astrbot.api.event.filter")
    ev_filter.EventMessageType = types.SimpleNamespace(ALL="ALL")

    components = types.ModuleType("astrbot.api.message_components")

    class _Seg:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Plain(_Seg):
        pass

    class Reply(_Seg):
        pass

    class Record(_Seg):
        pass

    class Json(_Seg):
        """照抄 AstrBot 的 Json：给 str 就 json.loads，给 dict 就原样留着。"""

        def __init__(self, data, **_):
            super().__init__(data=json.loads(data) if isinstance(data, str) else data)

    for cls in (Plain, Reply, Record, Json):
        setattr(components, cls.__name__, cls)

    star_tools = types.ModuleType("astrbot.core.star.star_tools")

    class _StarTools:
        @staticmethod
        def get_data_dir(name):
            return Path(".")

    star_tools.StarTools = _StarTools

    for name, mod in {
        "astrbot": root,
        "astrbot.api": api,
        "astrbot.api.event": event,
        "astrbot.api.event.filter": ev_filter,
        "astrbot.api.message_components": components,
        "astrbot.core": types.ModuleType("astrbot.core"),
        "astrbot.core.star": types.ModuleType("astrbot.core.star"),
        "astrbot.core.star.star_tools": star_tools,
    }.items():
        sys.modules[name] = mod


_mock_astrbot()
# 插件 import 期要 aiohttp —— 本机只有 AstrBot 的 site-packages 里有，借它一用
sys.path.insert(0, str(SITE))
sys.path.insert(0, str(PLUGIN_DIR))
import main as plugin  # noqa: E402

components = sys.modules["astrbot.api.message_components"]

CARD_INNER = json.dumps(
    {
        "app": "com.tencent.music.lua",
        "view": "music",
        "meta": {
            "music": {
                "app_type": 1,
                "desc": "杜歌",
                "jumpUrl": (
                    "https://y.music.163.com/m/song?id=26545127&uct2=N91vt25PbWgJ8YyLiMNH1w%3D%3D"
                    "&fx-wechatnew=t1&dlt=0846&app_version=9.6.05"
                ),
                "musicUrl": (
                    "http://music.163.com/song/media/outer/url?id=26545127&userid=0&sc=wm&tn="
                ),
                "preview": "https://p1.music.126.net/xxx.jpg",
                "tag": "网易云音乐",
                "title": "兄弟难当",
            }
        },
        "prompt": "[分享]兄弟难当",
    },
    ensure_ascii=False,
)

#: 三种喂法都要能过 —— `Json` 组件拿到的到底是哪一层，随 QQ / 适配器版本变。
SHAPES = {
    "data.data 是字符串（本机实测）": {"data": CARD_INNER},
    "整个消息段": {"type": "json", "data": {"data": CARD_INNER}},
    "已经是卡片对象": json.loads(CARD_INNER),
}

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = want in got if isinstance(want, str) and isinstance(got, str) else got == want
    print(f"  [{'✓' if ok else '✗'}] {label}: {got!r}")
    if not ok:
        failures.append(f"{label} 期望 {want!r} 实得 {got!r}")


for shape_name, payload in SHAPES.items():
    print(f"\n=== 卡片形态：{shape_name} ===")
    reply = components.Reply(text="", qq="10003", chain=[components.Json(payload)])

    text = plugin.Main._reply_text(reply)
    print(f"  （_reply_text 拿到 {len(text)} 字）")
    m = plugin.ID_RE.search(text)
    check("能提取歌曲 id", m.group(1) if m else None, "26545127")
    check("能挑出网易云 URL", bool(plugin.Main._pick_netease_url(text)), True)
    check("能取到「歌名 - 歌手」", plugin.Main._card_song_name(reply.chain), "兄弟难当 - 杜歌")

print("\n=== 回归：纯文本分享仍然可用 ===")
plain_reply = components.Reply(
    text="分享塞壬唱片-MSR/DAZBEE的单曲《酸橙色信笺》: https://163cn.tv/bhu1nHlF (来自@网易云音乐)",
    chain=[
        components.Plain(text="分享塞壬唱片-MSR/DAZBEE的单曲《酸橙色信笺》: https://163cn.tv/bhu1nHlF")
    ],
)
check("纯文本仍能挑出短链", plugin.Main._pick_netease_url(plugin.Main._reply_text(plain_reply)) or "", "163cn.tv")
check("纯文本没有歌名可挖（应为空）", plugin.Main._card_song_name(plain_reply.chain), "")

print("\n=== 直接 @ 的链接（不经引用）===")
#: 主人 2026-10-06 要的用法：`@南汐 <链接>`，不必引用。
for raw in [
    # uct2 是网易云 App 分享时自带的用户上下文参数，对提 id 毫无影响，
    # 这里用中性占位值（别把真实的贴进公开仓）。
    "@南汐 https://music.163.com/song?id=3413072220&uct2=EXAMPLE_TOKEN&from=app",
    "https://music.163.com/song?id=3413072220",
    "https://music.163.com/#/song?id=3413072220&fx-wxqd=&playerUIModeId=1379005",
    "https://y.music.163.com/m/song?id=3413072220",
]:
    picked = plugin.Main._pick_netease_url(raw)
    ids = plugin.ID_RE.search(picked or "")
    check(f"从「{raw[:38]}…」提 id", ids.group(1) if ids else None, "3413072220")

print("\n=== 结论 ===")
if failures:
    print("  ✗ 有失败：")
    for f in failures:
        print(f"     · {f}")
    sys.exit(1)
print("  ✓ 全部通过")
