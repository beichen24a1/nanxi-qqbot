# -*- coding: utf-8 -*-
"""发送一条 QQ 群消息（走 AstrBot im 接口）。

用途：
  · 验证 dsh-qq-notify 插件的发送链路（等价于工具 notify_owner 干的事）；
  · 需要手动播报时的备用通道。

用法：
    python 发送qq通知.py                      # 发默认测试文案
    python 发送qq通知.py "任务完成：xxx"        # 发自定义文案

⚠️ 密钥不写在本文件里（本文件会被 git 跟踪）：从 `游戏通知\\config.json` 读取，
   该文件已被 .gitignore 排除。缺 key 时直接报错，不会静默失败。
"""
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG = ROOT / "游戏通知" / "config.json"
URL = "http://127.0.0.1:6185/api/v1/im/messages"
DEFAULT_TEXT = "【测试】南汐的任务完成通知通道已就绪：以后 DSH 任务完成会直接发到这个群喵~ (´・ω・`)"


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEXT
    if not CONFIG.exists():
        print("找不到配置文件:", CONFIG)
        return 1
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    key = cfg.get("im_api_key")
    group = cfg.get("group_id")
    platform = cfg.get("im_platform", "onebot-qq")
    if not key or not group:
        print("配置缺少 im_api_key / group_id:", CONFIG)
        return 1
    umo = f"{platform}:GroupMessage:{group}"

    body = json.dumps({"umo": umo, "message": [{"type": "plain", "text": text}]}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        print("HTTP", resp.status, "->", umo, resp.read().decode("utf-8", "ignore")[:200])
        return 0
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8", "ignore")[:300])
        return 1
    except Exception as e:  # noqa: BLE001 - 脚本，直接把原因打出来
        print("ERR", type(e).__name__, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
