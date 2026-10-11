# -*- coding: utf-8 -*-
"""把 AstrBot 的「群聊上下文 - 图片描述」关掉（`provider_ltm_settings.image_caption`）。

## 为什么需要它

`provider_settings.enable`（AstrBot 的「不启用 AI 能力」总开关）**只管人格对话**，
它**管不到**群聊上下文的图片描述 —— 两者是不同的机制。后者的触发条件是
`image_caption AND bool(image_caption_provider_id)`
（`builtin_stars/astrbot/group_chat_context.py:63-65`）：

    **群里每来一张图，就调一次视觉模型**生成描述存进群聊上下文。
    **不需要 @ 机器人**，它是纯被动监听。

于是你明明"没在对话"，账单却在涨。本项目 2026-10-06~10 的日志里因此攒了
**990 次 `Insufficient Balance`**（从 01:16 一路烧到 22:25），把主人的 API key 烧到欠费。

> ⚠️ 删掉 API key **不能止血** —— 它只会从"花钱"变成"报 401"，你一换新 key 它立刻接着烧。
> 真正的修复是关掉这个开关。

## 它做什么

双保险（两个都改）：

    image_caption              = false
    image_caption_provider_id  = ""

后者清空是为了防"以后有人手滑把开关又打开"——两个条件缺一个就不会触发。

⚠️ **改之前必须先停 AstrBot**：它内存里握着这份配置，退出时会**整体回写覆盖**磁盘改动。

## 跑法

    # 默认按仓根找 astrbot/data/cmd_config.json
    python tools\\set_image_caption_off.py --dry-run
    python tools\\set_image_caption_off.py --apply

    # 配置在别处时显式指定
    python tools\\set_image_caption_off.py --config D:\\path\\to\\cmd_config.json --apply

`--apply` 会自动把原文件备份到 `_backup\\<日期>\\`，并**保持原有的 BOM 状态**
（AstrBot 自己写的时候带 BOM，跟着它走最稳）。

## 改完怎么验证（判据性，别只看"没报错"）

往群里发一张图，然后确认：

1. 图**确实进群了**（不然这次验证等于没做）；
2. 日志里 `获取图片描述` / `Insufficient` / `401` **零命中**（改之前是每图必报一次）。

顺带一个定位同类问题的技巧——**别只看日志最后几行，按来源分组数一遍**：

    Select-String -Path logs\\astrbot.log -Pattern '401|Insufficient' |
      ForEach-Object { if ($_.Line -match '\\[([a-z_.]+):\\d+\\]') { $matches[1] } } |
      Group-Object | Sort-Object Count -Descending

本项目第一次跑出来第一名是 `core.event_bus`（事件总线在转发，不是它干的），
**第三名 `astrbot.group_chat_context` 才是真凶**。
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

#: 仓根（本脚本在 `<repo>/tools/` 下）。
REPO = Path(__file__).resolve().parent.parent
#: 默认的 AstrBot 配置路径（可用 --config 覆盖）。
DEFAULT_CFG = REPO / "astrbot" / "data" / "cmd_config.json"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="关闭 AstrBot 群聊上下文的图片描述（省 LLM 额度）"
    )
    ap.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CFG,
        help=f"AstrBot 的 cmd_config.json 路径（默认 {DEFAULT_CFG}）",
    )
    ap.add_argument("--apply", action="store_true", help="真正写入（缺省只预览）")
    ap.add_argument("--dry-run", action="store_true", help="只预览（默认行为）")
    args = ap.parse_args()

    cfg_path: Path = args.config
    if not cfg_path.is_file():
        print(f"[x] 找不到配置文件：{cfg_path}")
        print("    用 --config 指定它的位置。")
        return 1

    # AstrBot 写的是 utf-8-sig（带 BOM），读的时候两种都要能认。
    raw = cfg_path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    cfg = json.loads(raw.decode("utf-8-sig"))

    ltm = cfg.get("provider_ltm_settings")
    if not isinstance(ltm, dict):
        print("[x] 配置里没有 provider_ltm_settings 段 —— 确认一下 AstrBot 版本/结构")
        return 1

    before = {
        "image_caption": ltm.get("image_caption"),
        "image_caption_provider_id": ltm.get("image_caption_provider_id"),
    }
    print("改动前：")
    print(f"  image_caption              = {before['image_caption']}")
    print(f"  image_caption_provider_id  = {before['image_caption_provider_id']!r}")

    if before["image_caption"] is False and not before["image_caption_provider_id"]:
        print("\n[=] 已经是关闭状态，无需改动。")
        return 0

    ltm["image_caption"] = False
    ltm["image_caption_provider_id"] = ""

    print("\n改动后：")
    print(f"  image_caption              = {ltm['image_caption']}")
    print(f"  image_caption_provider_id  = {ltm['image_caption_provider_id']!r}")

    if not args.apply:
        print("\n[i] 这是预览。确认无误后加 --apply 真正写入。")
        print("[!] 写入前请先停掉 AstrBot —— 它退出时会把内存里的配置整体回写，覆盖你的改动。")
        return 0

    backup_dir = REPO / "_backup" / datetime.now().strftime("%Y%m%d")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = backup_dir / f"cmd_config.json.bak-before-image-caption-off-{stamp}"
    shutil.copy2(cfg_path, bak)
    print(f"\n[+] 已备份：{bak}")

    out = json.dumps(cfg, ensure_ascii=False, indent=2)
    cfg_path.write_bytes((("\ufeff" if has_bom else "") + out).encode("utf-8"))
    print(
        f"[+] 已写入：{cfg_path}（BOM={'有' if has_bom else '无'}，"
        f"{len(out.encode('utf-8'))} 字节）"
    )
    print("\n[i] 接下来：启动 AstrBot → 往群里发一张图 → 确认日志里")
    print("    `获取图片描述` / `Insufficient` / `401` 零命中。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
