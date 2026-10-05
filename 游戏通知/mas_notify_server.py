# -*- coding: utf-8 -*-
"""mas 通知中继服务 —— 去掉 mas 自动附加的「AUTO-MAS 敬上」再转发到群。

为什么需要它：
    mas 会在 webhook 正文**末尾自动附加**「AUTO-MAS 敬上」——那是源码里的常量
    （`app/core/notify.py` 的 `SIGNATURE`，由 `NotifyPayload.signed_text` 拼上去），
    **模板层面去不掉**（模板只能替换 `{title}`/`{content}` 这类变量，没有截断能力）。
    所以中间加一层：收 mas 的 Webhook → 去掉那行签名 → 转发给 AstrBot。

链路：
    mas（全局自定义 Webhook）
        │ POST（body 就是 AstrBot 的 im/messages 形状）
        ▼
    本服务  http://127.0.0.1:8765/mas-notify     ← 在这里去掉「AUTO-MAS 敬上」
        │ POST（原样转发，Headers 里的 Authorization 一并透传）
        ▼
    AstrBot http://127.0.0.1:6185/api/v1/im/messages
        ▼
    QQ 群 <TEST_GROUP_ID>

用法：
    python mas_notify_server.py            前台运行（Ctrl+C 退出）
    推荐：双击 启动\\mas通知中继.bat          以最小化窗口常驻
"""

import json
import os
import sys
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
NANXI_CONFIG = os.path.join(BASE, "config.json")

HOST = "127.0.0.1"
PORT = 8765
PATH = "/mas-notify"
ASTROBOT_URL = "http://127.0.0.1:6185/api/v1/im/messages"

# mas 自动附加在正文末尾的签名（源码常量，去不掉只能在这里剥）
SIGNATURE = "AUTO-MAS 敬上"


def log(msg: str) -> None:
    """带时间的标准输出日志（中继以窗口/重定向方式常驻，日志即排查依据）。"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def strip_signature(text: str) -> str:
    """去掉正文末尾的「AUTO-MAS 敬上」（含它前面的空行）。

    Args:
        text: mas 渲染后的正文。

    Returns:
        去掉签名后的正文；没有签名则原样返回。
    """
    t = (text or "").rstrip()
    if t.endswith(SIGNATURE):
        return t[: -len(SIGNATURE)].rstrip()
    return t


def load_key_from_config() -> str:
    """兜底：从 游戏通知/config.json 读 im_api_key。"""
    try:
        with open(NANXI_CONFIG, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("im_api_key", "") or ""
    except Exception:
        return ""


def forward(payload: dict, auth_header: str) -> tuple[int, str]:
    """把处理后的 payload 转发给 AstrBot。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(ASTROBOT_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if auth_header:
        req.add_header("Authorization", auth_header)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, r.read().decode("utf-8", "replace")


class Handler(BaseHTTPRequestHandler):
    server_version = "MasNotifyRelay/1.0"

    def _reply(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802  （健康检查：浏览器打开能确认服务活着）
        self._reply(200, {
            "status": "ok",
            "service": "mas 通知中继",
            "listen": f"http://{HOST}:{PORT}{PATH}",
            "forward_to": ASTROBOT_URL,
            "strips": SIGNATURE,
        })

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != PATH:
            self._reply(404, {"status": "error", "message": f"unknown path {self.path}"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            log(f"[!] 收到的不是合法 JSON：{e}")
            self._reply(400, {"status": "error", "message": f"invalid json: {e}"})
            return

        # mas 的模板渲染结果就是 AstrBot 的 im/messages 形状：
        #   {"umo": "...", "message": [{"type": "plain", "text": "..."}]}
        # 也可能（若模板写成纯文本）message 直接是字符串。
        stripped = False
        msgs = payload.get("message")
        if isinstance(msgs, list):
            for seg in msgs:
                if isinstance(seg, dict) and seg.get("type") == "plain":
                    old = seg.get("text") or ""
                    new = strip_signature(old)
                    if new != old:
                        stripped = True
                    seg["text"] = new
        elif isinstance(msgs, str):
            new = strip_signature(msgs)
            stripped = new != msgs
            payload["message"] = new

        auth = self.headers.get("Authorization", "").strip()
        if not auth:
            key = load_key_from_config()
            if key:
                auth = "Bearer " + key

        preview = ""
        if isinstance(payload.get("message"), list) and payload["message"]:
            preview = str(payload["message"][0].get("text", "")).split("\n")[0][:40]
        elif isinstance(payload.get("message"), str):
            preview = payload["message"].split("\n")[0][:40]

        try:
            status, body = forward(payload, auth)
        except Exception as e:  # noqa: BLE001
            log(f"[!] 转发 AstrBot 失败：{type(e).__name__}: {e}（首行：{preview}）")
            # 对 mas 仍返回非 2xx，让 mas 侧记一条失败，便于发现 AstrBot 没起
            self._reply(502, {"status": "error", "message": f"forward failed: {e}"})
            return

        ok = 200 <= status < 300
        log(f"[+] {preview} | 去签名={'是' if stripped else '无'} | AstrBot={status}"
            + ("" if ok else f" {body[:120]}"))
        if ok:
            self._reply(200, {"status": "ok", "forwarded": status, "stripped": stripped})
        else:
            self._reply(502, {"status": "error", "forwarded": status, "body": body[:200]})

    def log_message(self, fmt, *args):  # 静音默认的每请求一行访问日志
        return


def main() -> None:
    if not load_key_from_config():
        log("[!] 提示：游戏通知/config.json 里没有 im_api_key，将只能依赖 mas 传来的 Authorization 头")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log(f"mas 通知中继已启动：http://{HOST}:{PORT}{PATH}")
    log(f"  转发目标：{ASTROBOT_URL}")
    log(f"  会剥掉正文末尾的：{SIGNATURE}")
    log("  mas 侧把「自定义 Webhook」的 Url 指向本服务即可；Ctrl+C 退出。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("收到中断，退出。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
