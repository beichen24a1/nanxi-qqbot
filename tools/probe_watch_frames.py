# -*- coding: utf-8 -*-
"""独立探针：脱离 AstrBot，单独驱动插件里的 ``Browser``，把看板推帧的每一步打在屏幕上。

为什么需要它：`Page.startScreencast` 在 headless 里**只推了第一帧就哑了**
（看板 /state 的 seq 永远是 1），我加的"静默就降级轮询截图"兜底也没生效。
在 AstrBot 里排查的代价是"改一行 → 重启 20 秒 → 发一条 QQ → 再猜"，
所以这里把它单独拎出来跑：**一轮就能看清轮询任务卡在哪**。

用法（必须带上 AstrBot 的 site-packages，aiohttp 在那里）：
    C:\\Python310\\python.exe tools\\probe_watch_frames.py [url]
"""
import asyncio
import importlib.util
import pathlib
import sys
import time

ROOT = pathlib.Path(r"D:\dsh\QQbot")
SP = ROOT / "astrbot" / "data" / "site-packages"
sys.path.insert(0, str(SP))

# 把 browser.py 按**和 main.py 一样的方式**动态加载（它就是这个用法）
spec = importlib.util.spec_from_file_location(
    "nanxi_dsh_browser", ROOT / "astrbot_plugin_nanxi_dsh" / "browser.py"
)
browser_mod = importlib.util.module_from_spec(spec)
sys.modules["nanxi_dsh_browser"] = browser_mod
spec.loader.exec_module(browser_mod)

URL = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
# ⚠️ 用一个独立的临时 profile —— 绝不碰她那份 chrome-profile（里面有登录态）。
PROFILE = ROOT / "_tmp-watch-probe-profile"


async def main() -> int:
    exe = browser_mod.find_browser()
    print(f"浏览器: {exe}")
    if not exe:
        return 2
    b = browser_mod.Browser(exe, PROFILE, port=9444, idle_timeout=120.0)

    print("--- ensure() ---")
    t0 = time.monotonic()
    await b.ensure()
    print(f"  Chrome 起来了，用时 {time.monotonic() - t0:.1f}s")

    print("--- watch_on() ---")
    await b.watch_on()
    print(f"  casting={b.casting}  poller={b._poller!r}")

    print(f"--- goto({URL}) ---")
    r = await b.goto(URL)
    print(f"  title={r.get('title')!r}  text={len(r.get('text') or '')} 字")

    print("--- 采样 12 秒（每秒一次）---")
    for i in range(12):
        await asyncio.sleep(1.0)
        poller = b._poller
        state = "done" if (poller is not None and poller.done()) else "running"
        if poller is not None and poller.done() and poller.exception() is not None:
            state = f"EXC {poller.exception()!r}"
        print(
            f"  {i + 1:2}s  seq={b.frame_seq:<4} src={b.frame_src or '-':<11} "
            f"casting={b.casting!s:<5} poller={state:<9} "
            f"age={b.frame_age if b.frame_age is None else round(b.frame_age, 1)}"
        )

    print("--- 再打开一个页面，看帧会不会动 ---")
    await b.goto("https://www.iana.org/help/example-domains")
    for i in range(4):
        await asyncio.sleep(1.0)
        print(f"  {i + 1}s  seq={b.frame_seq}  src={b.frame_src}")

    with_file = b.frame is not None
    print(f"有帧: {with_file}  字节={len(b.frame) if with_file else 0}")
    await b.close(reason="探针结束")
    return 0


raise SystemExit(asyncio.run(main()))
