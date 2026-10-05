# -*- coding: utf-8 -*-
"""只看 cmd_config.json 里跟"要不要聊天/要不要回话"有关的几个段（只读）。

用法：C:\\Python310\\python.exe tools\\dump_astrbot_cfg.py
"""
import json
import pathlib
import sys

P = pathlib.Path(r"D:\dsh\QQbot\astrbot\data\cmd_config.json")
# ⚠️ AstrBot 写这份配置时带 BOM，必须用 utf-8-sig 读，否则 json.loads 会炸。
raw = P.read_text(encoding="utf-8-sig")
cfg = json.loads(raw)
print("顶层键：")
for k in cfg:
    print("   ", k)

for seg in ("provider_settings", "provider", "platform_settings", "persona_settings"):
    if seg not in cfg:
        continue
    print(f"\n=== {seg} ===")
    v = cfg[seg]
    print(json.dumps(v, ensure_ascii=False, indent=2)[:4000])

# provider 清单单独看：有没有 enable 开关、谁是默认
prov = cfg.get("provider") or []
print(f"\n=== provider 列表（共 {len(prov)} 条）===")
for i, p in enumerate(prov):
    if not isinstance(p, dict):
        continue
    keys = {
        k: p.get(k)
        for k in ("id", "type", "provider", "model", "enable", "enabled", "api_base")
        if k in p
    }
    print(f"  [{i}] {json.dumps(keys, ensure_ascii=False)}")
sys.exit(0)
