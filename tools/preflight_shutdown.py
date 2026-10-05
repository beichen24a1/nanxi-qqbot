# -*- coding: utf-8 -*-
"""关停前的侦查：插件清单、plugin_set、禁用内置命令、摸头插件实现方式（只读）。"""
import json
import pathlib

CFG = pathlib.Path(r"D:\dsh\QQbot\astrbot\data\cmd_config.json")
PLUG = pathlib.Path(r"D:\dsh\QQbot\astrbot\data\plugins")

cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))

print("=== provider_settings.enable ===")
print("   ", cfg["provider_settings"].get("enable"))

print("\n=== plugin_set ===")
print("   ", json.dumps(cfg.get("plugin_set"), ensure_ascii=False))

print("\n=== disable_builtin_commands / disable_metrics ===")
print("    disable_builtin_commands =", cfg.get("disable_builtin_commands"))
print("    disable_metrics          =", cfg.get("disable_metrics"))

print("\n=== dashboard（看通知接口的鉴权来源）===")
dash = cfg.get("dashboard") or {}
print("    keys:", list(dash.keys()))
print("    username:", dash.get("username"))

print("\n=== 已安装插件目录 ===")
for p in sorted(PLUG.iterdir()):
    if p.is_dir():
        meta = p / "metadata.yaml"
        name = ""
        if meta.exists():
            for line in meta.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                    break
        print(f"    {p.name:<34} {name}")

print("\n=== petpet 插件用什么触发（确认它不走 LLM）===")
pp = PLUG / "astrbot_plugin_petpet"
for f in sorted(pp.glob("*.py")):
    txt = f.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(txt.splitlines(), 1):
        s = line.strip()
        if s.startswith("@filter.") or s.startswith("async def") and "(" in s:
            print(f"    {f.name}:{i}: {s[:110]}")
