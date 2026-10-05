# -*- coding: utf-8 -*-
"""把 AstrBot 的 AI 能力关掉（只留「摸头」+ 主动发送通知）。

依据（都读过上游源码了，不是猜的）：
  * `provider_settings.enable` 是**官方总开关** ——
    `core/pipeline/process_stage/stage.py:53` 与 `.../method/agent_request.py:37`
    两处都判它，为 False 时只打一行 debug 日志然后 `return`，**不报错、不刷屏**。
  * 主动发送（`im/messages`，也就是 notify_owner / mas 播报走的那条）是 dashboard 的
    HTTP 接口，鉴权用 dashboard 的 jwt/密码，**完全不经过 pipeline、不看 provider**。
  * 「摸头」插件 `astrbot_plugin_petpet` 用 `@filter.regex(...)` 触发，**纯正则**，
    同样不依赖 LLM。

⚠️ 改之前必须先把 AstrBot 停掉 —— 它内存里握着配置，退出时可能把改动覆盖掉。
   脚本本身会检查端口，发现还在监听就拒绝执行。

用法：
    C:\\Python310\\python.exe tools\\shutdown_nanxi_ai.py --dry-run   # 只看会改什么
    C:\\Python310\\python.exe tools\\shutdown_nanxi_ai.py --apply     # 真改（自动备份）
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

CFG = pathlib.Path(r"D:\dsh\QQbot\astrbot\data\cmd_config.json")
BACKUP_DIR = pathlib.Path(r"D:\dsh\QQbot\_backup\20261005")


def port_busy(port: int) -> bool:
    """6185/3002 上有没有人在听（有就说明 AstrBot 还在跑）。"""
    out = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, shell=False
    ).stdout
    for line in out.splitlines():
        if f":{port} " in line or f":{port}\t" in line:
            if "LISTENING" in line:
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("要么 --dry-run，要么 --apply")

    busy = [p for p in (6185, 3002) if port_busy(p)]
    if busy:
        print(f"✗ 端口 {busy} 还在监听 —— AstrBot 没停。")
        print("  先跑：启动\\stop_astrbot.bat（或按端口 taskkill），再执行本脚本。")
        return 2

    cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
    ps = cfg["provider_settings"]
    print(f"当前 provider_settings.enable = {ps.get('enable')}")
    print(f"当前 default_provider_id      = {ps.get('default_provider_id')}")
    print(f"当前 plugin_set                = {cfg.get('plugin_set')}")

    want_enable = False
    want_plugins = ["astrbot_plugin_petpet"]
    todo = []
    if ps.get("enable") is not False:
        todo.append(f"provider_settings.enable -> False（不做 LLM 回复）")
    if cfg.get("plugin_set") != want_plugins:
        todo.append(f"plugin_set -> {want_plugins}（只留摸头插件的 handler）")
    if not todo:
        print("\n两项都已经到位，不用改。")
        return 0

    print("\n将会做：")
    for t in todo:
        print("   ·", t)
    print(
        "\n⚠️ **不动任何文件** —— 插件目录原封不动，只是配置上说"
        "「只有 astrbot_plugin_petpet 的 handler 生效」。\n"
        "   provider 清单 / 人格 / 白名单 / 工具注册全部保留，把这两项改回去 + 重启就恢复。"
    )

    if args.dry_run:
        print("\n（干跑，未写入）")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = BACKUP_DIR / f"cmd_config.json.bak-before-ai-off-{stamp}"
    bak.write_bytes(CFG.read_bytes())
    print(f"\n已备份 -> {bak}")

    ps["enable"] = want_enable
    cfg["plugin_set"] = want_plugins
    # ⚠️ 保持 utf-8-sig（带 BOM）写回：AstrBot 写这份配置时就是带 BOM 的。
    CFG.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8-sig"
    )
    back = json.loads(CFG.read_text(encoding="utf-8-sig"))
    print(f"已写入：provider_settings.enable = {back['provider_settings']['enable']}")
    print(f"已写入：plugin_set = {back['plugin_set']}")
    print("（default_provider_id / 人格 / 白名单原样保留，改回来 + 重启即恢复）")
    return 0


raise SystemExit(main())
