# -*- coding: utf-8 -*-
"""查看 / 修改 AstrBot 的 `plugin_set`（官方"插件集"配置）。

背景：`plugin_set` 的语义是**「哪些插件注册的消息 handler 会被激活」**
（`core/pipeline/waking_check/stage.py:158-170` 把它传给
`get_handlers_by_event_type(..., plugins_name=…)`；`["*"]` = 全部启用）。
⚠️ 它**不阻止插件加载** —— 启动日志里插件照旧加载、工具照旧注册，只是不响应消息。

⚠️ 改之前**必须先停 AstrBot**：它内存里握着配置，退出时会覆盖你的改动。
   本脚本会检查 6185/3002，还在监听就拒绝执行。

用法：
    python tools\\plugin_set.py --list
    python tools\\plugin_set.py --add astrbot_plugin_probe_reply
    python tools\\plugin_set.py --remove astrbot_plugin_probe_reply
    python tools\\plugin_set.py --set astrbot_plugin_petpet,astrbot_plugin_x
    python tools\\plugin_set.py --all                     # 恢复成 ["*"]（全部启用）
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

CFG = pathlib.Path(r"D:\dsh\QQbot\astrbot\data\cmd_config.json")
BACKUP_DIR = pathlib.Path(r"D:\dsh\QQbot\_backup")


def port_busy(port: int) -> bool:
    """6185/3002 上有没有人在听（有就说明 AstrBot 还在跑）。"""
    out = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, shell=False
    ).stdout
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            return True
    return False


def load() -> dict:
    return json.loads(CFG.read_text(encoding="utf-8-sig"))


def save(cfg: dict) -> None:
    """保持 utf-8-sig（带 BOM）写回 —— AstrBot 自己写这份配置时就是带 BOM 的。"""
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--add", action="append", default=[])
    ap.add_argument("--remove", action="append", default=[])
    ap.add_argument("--set", default="")
    ap.add_argument("--all", action="store_true", help='恢复成 ["*"]')
    ap.add_argument("--apply", action="store_true", help="真写；缺省只预览")
    args = ap.parse_args()

    cfg = load()
    cur = cfg.get("plugin_set", ["*"])
    print(f"当前 plugin_set = {cur}")
    if args.list or not (args.add or args.remove or args.set or args.all):
        busy = [p for p in (6185, 3002) if port_busy(p)]
        print(f"  AstrBot 在跑吗: {'是（端口 ' + str(busy) + ' 在监听）' if busy else '否'}")
        return 0

    # 目标值
    if args.all:
        want = ["*"]
    else:
        base = [] if "*" in cur else list(cur)
        if args.set:
            base = [x.strip() for x in args.set.split(",") if x.strip()]
        for name in args.add:
            if name not in base:
                base.append(name)
        for name in args.remove:
            base = [x for x in base if x != name]
        want = base

    if want == cur:
        print("  目标值与当前一致，无需改动。")
        return 0

    print(f"将改成 plugin_set = {want}")
    if not args.apply:
        print("\n（预览模式，未写入。确认无误后加 --apply。）")
        return 0

    busy = [p for p in (6185, 3002) if port_busy(p)]
    if busy:
        print(f"\n✗ 端口 {busy} 还在监听 —— AstrBot 没停。")
        print("  它内存里握着配置，退出时会覆盖你的改动。先停再改。")
        return 2

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = BACKUP_DIR / f"cmd_config.json.bak-before-pluginset-{stamp}"
    bak.write_bytes(CFG.read_bytes())
    print(f"\n已备份 -> {bak}")

    cfg["plugin_set"] = want
    save(cfg)
    back = load()["plugin_set"]
    print(f"已写入：plugin_set = {back}")
    print("⚠️ 要重启 AstrBot 才生效（`启动\\restart-astrbot.ps1`）。")
    return 0


raise SystemExit(main())
