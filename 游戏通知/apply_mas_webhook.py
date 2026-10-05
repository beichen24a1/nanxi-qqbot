# -*- coding: utf-8 -*-
"""把「南汐通知」Webhook 配到 mas(AUTO-MAS) 的**全局**通知渠道，并（可选）测通。

背景（依据 mas 官方文档 https://doc.auto-mas.top/docs/advanced-features/notification.html）：
  * **全局通知**在「设置 → 通知设置」里配，管所有任务。文档原话："一般配这一个就够了"。
  * **用户通知**在「用户配置 → 通知设置」里配，是"额外多发一份"、**不会覆盖全局**。
  ⇒ 所以只配全局一处即可；全局与用户级同开会导致同一次通知发两条。

两种写入方式：
  * **API 模式（默认，推荐）** —— 调 mas 自己的 HTTP API（默认 127.0.0.1:36163，
    受监督运行时会换成注入端口）。mas 运行中即可写入、由 mas 自己持久化、界面立刻可见，
    **不需要关闭 mas**、也不会被 mas 回写覆盖。
  * **file 模式（`--file`，备用）** —— 直接改 mas 的配置文件，**必须完全退出 mas**，
    否则会被 mas 覆盖。

用法：
    python apply_mas_webhook.py                 # 预览（不改动）
    python apply_mas_webhook.py --apply         # 通过 mas API 写入
    python apply_mas_webhook.py --apply --test  # 写入后再调 mas 官方测试接口验证
    python apply_mas_webhook.py --apply --file  # 回退：直接改配置文件（需先退出 mas）
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
NANXI_CONFIG = os.path.join(BASE, "config.json")

MAS_ROOT = r"D:\jiao_ben\AUTO-MAS-Full-v5.3.1-x64"
GLOBAL_CONFIG = os.path.join(MAS_ROOT, "config", "Config.json")
SCRIPT_CONFIG = os.path.join(MAS_ROOT, "config", "ScriptConfig.json")

# mas 后端 HTTP API：默认端口 + 开发端口（受监督时由环境注入别的高位端口）
MAS_API_PORTS = (36163, 36164)

ASTROBOT_SEND_URL = "http://127.0.0.1:6185/api/v1/im/messages"
# 当前方案：mas 的 Webhook 【直连】AstrBot，正文末尾会带上 mas 自动附加的「AUTO-MAS 敬上」，
# 与群里其它机器人转发出来的 mas 通知完全一致（主人确认保留该签名，不再多跑一个中继进程）。
#
# 可选（备用）：若将来想把那行签名去掉，可启用本机中继 mas_notify_server.py（监听 8765），
# 把下面这行改成 RELAY_URL 即可（中继会剥掉签名再转发 AstrBot）。
RELAY_URL = "http://127.0.0.1:8765/mas-notify"
MAS_WEBHOOK_URL = ASTROBOT_SEND_URL
GROUP_ID = "<TEST_GROUP_ID>"
IM_PLATFORM = "onebot-qq"

# 全局渠道显示名（脚本靠它识别"这条是我们配的"，用于幂等更新）
GLOBAL_NAME = "南汐通知-游戏日常"
# 全局只有一条模板，对所有游戏生效 ⇒ 采用 mas 的**标准报告格式**，
# 与其它 QQ 机器人转发出来的通知完全一致：
#     {title}            ← 如「09-26 | MAA的自动代理任务报告」
#     （空行）
#     {content}          ← 正文，末尾自带 "AUTO-MAS 敬上"（NotifyPayload.signed_text）
GLOBAL_TEXT = "{title}\n\n{content}"


def load_im_key() -> str:
    with open(NANXI_CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    key = cfg.get("im_api_key")
    if not key:
        print("[错误] 游戏通知/config.json 里没有 im_api_key")
        sys.exit(1)
    return key


def build_template(text: str) -> str:
    """把句式包成 AstrBot im/messages 需要的 JSON 模板（可含 {title} 等 mas 变量）。"""
    return json.dumps(
        {
            "umo": f"{IM_PLATFORM}:GroupMessage:{GROUP_ID}",
            "message": [{"type": "plain", "text": text}],
        },
        ensure_ascii=False,
    )


def build_headers(im_key: str) -> str:
    return json.dumps(
        {"Content-Type": "application/json", "Authorization": f"Bearer {im_key}"},
        ensure_ascii=False,
    )


# ────────────────────────────── API 模式 ──────────────────────────────

def api_call(port: int, path: str, payload: dict, timeout: int = 25):
    """调 mas 的 HTTP API，返回 (status|None, dict)。"""
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return None, {"err": f"{type(e).__name__}: {e}"}


def find_api_port():
    """探测 mas 的 HTTP API 端口；找不到返回 None。"""
    for port in MAS_API_PORTS:
        st, res = api_call(port, "/api/setting/webhook/get", {"webhookId": None})
        if st == 200 and res.get("status") == "success":
            return port
    return None


def api_apply_global(port: int, im_key: str, *, apply_flag: bool) -> bool:
    """通过 API 幂等写入全局 Webhook。返回是否成功。"""
    st, cur = api_call(port, "/api/setting/webhook/get", {"webhookId": None})
    if st != 200:
        print(f"[错误] 读取 mas webhook 配置失败：{cur}")
        return False

    index = cur.get("index") or []
    data = cur.get("data") or {}
    # 按显示名找我们之前配的那条（幂等）
    existing = next(
        (
            it.get("uid")
            for it in index
            if (data.get(it.get("uid"), {}).get("Info") or {}).get("Name") == GLOBAL_NAME
        ),
        None,
    )

    payload = {
        "Info": {"Name": GLOBAL_NAME, "Enabled": True},
        "Data": {
            "Url": MAS_WEBHOOK_URL,
            "Method": "POST",
            "Headers": build_headers(im_key),
            "Template": build_template(GLOBAL_TEXT),
        },
    }

    print(f"[当前] mas 全局自定义 Webhook 共 {len(index)} 条"
          + (f"，其中已有「{GLOBAL_NAME}」（将更新）" if existing else "（将新建一条）"))

    if not apply_flag:
        print("       将写入：")
        print(f"         名称     = {GLOBAL_NAME}")
        print(f"         Url      = {MAS_WEBHOOK_URL}   （本地中继 → 再去掉「AUTO-MAS 敬上」→ AstrBot）")
        print(f"         Method   = POST")
        print(f"         Template = {GLOBAL_TEXT}")
        return True

    if existing:
        st, res = api_call(port, "/api/setting/webhook/update",
                           {"webhookId": existing, "data": payload})
        action = "更新"
    else:
        st, res = api_call(port, "/api/setting/webhook/add", {})
        if st != 200 or not res.get("webhookId"):
            print(f"[错误] 新建 webhook 失败：{res}")
            return False
        st, res = api_call(port, "/api/setting/webhook/update",
                           {"webhookId": res["webhookId"], "data": payload})
        action = "新建"

    if st != 200 or res.get("status") != "success":
        print(f"[错误] {action} webhook 失败：{res}")
        return False
    print(f"[完成] 已{action}全局 Webhook「{GLOBAL_NAME}」（由 mas 自己保存，界面刷新即可见）。")
    return True


def api_test(port: int, im_key: str) -> bool:
    """调 mas 官方测试接口，立即验证链路。"""
    st, res = api_call(port, "/api/setting/webhook/test", {
        "data": {
            "Info": {"Name": GLOBAL_NAME, "Enabled": True},
            "Data": {
                "Url": MAS_WEBHOOK_URL,
                "Method": "POST",
                "Headers": build_headers(im_key),
                "Template": build_template(GLOBAL_TEXT),
            },
        },
    })
    ok = st == 200 and isinstance(res, dict) and res.get("status") == "success"
    print("[测试] mas 官方测试接口 -> " + ("成功，群里应已收到一条测试消息 ✓" if ok else f"失败：{res}"))
    return ok


# ────────────────────────────── file 模式（备用） ──────────────────────────────

def mas_running():
    """True=在运行；False=未运行；None=无法确认。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "if (Get-Process -Name 'AUTO-MAS' -ErrorAction SilentlyContinue) { 'YES' } else { 'NO' }"],
            capture_output=True, timeout=25,
        )
        blob = (r.stdout or b"").upper()
        if b"YES" in blob:
            return True
        if b"NO" in blob:
            return False
    except Exception:
        pass
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq AUTO-MAS.exe"],
                           capture_output=True, timeout=15)
        blob = (r.stdout or b"") + (r.stderr or b"")
        if b"AUTO-MAS" in blob:
            return True
        if b"Access denied" in blob or b"ACCESS DENIED" in blob or r.returncode != 0:
            return None
        return False
    except Exception:
        return None


def file_apply_global(im_key: str, *, apply_flag: bool) -> bool:
    """直接改 mas 配置文件（需 mas 已退出）。"""
    if not os.path.exists(GLOBAL_CONFIG):
        print(f"[错误] 找不到 {GLOBAL_CONFIG}")
        return False

    import uuid as _uuid

    with open(GLOBAL_CONFIG, "r", encoding="utf-8") as f:
        gdata = json.load(f)
    notify = gdata.setdefault("Notify", {})
    hooks = notify.get("CustomWebhooks")
    if not isinstance(hooks, dict):
        hooks = {}
        notify["CustomWebhooks"] = hooks

    uid = str(_uuid.uuid5(_uuid.NAMESPACE_URL, "nanxi-notify-global"))
    instances = hooks.get("instances")
    if not isinstance(instances, list):
        instances = []
    instances = [i for i in instances if not (isinstance(i, dict) and str(i.get("uid")) == uid)]
    instances.append({"uid": uid, "type": "Webhook"})
    hooks["instances"] = instances
    hooks[uid] = {
        "Info": {"Enabled": True, "Name": GLOBAL_NAME},
        "Data": {
            "Url": MAS_WEBHOOK_URL,
            "Method": "POST",
            "Headers": build_headers(im_key),
            "Template": build_template(GLOBAL_TEXT),
        },
    }

    print(f"[file 模式] 目标：{GLOBAL_CONFIG}")
    print(f"           将写入全局 Webhook「{GLOBAL_NAME}」")
    print(f"           Template = {GLOBAL_TEXT}")
    print("           注意：mas 的 MultipleConfig 必须带 instances 索引，脚本已同步维护。")

    if not apply_flag:
        return True

    state = mas_running()
    if state is True:
        print("\n[中止] mas 正在运行，改配置文件会被它覆盖。请先完全退出 mas，或用默认的 API 模式。")
        return False
    if state is None:
        print("\n[注意] 无法确认 mas 是否在运行；若它开着，本次写入可能被覆盖。")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{GLOBAL_CONFIG}.bak-{stamp}"
    shutil.copy2(GLOBAL_CONFIG, bak)
    print(f"[备份] {os.path.basename(bak)}")

    with open(GLOBAL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(gdata, f, ensure_ascii=False, indent=4)
    print("[完成] 已写入全局 Webhook。")
    return True


def main() -> None:
    apply_flag = "--apply" in sys.argv
    use_file = "--file" in sys.argv
    do_test = "--test" in sys.argv

    im_key = load_im_key()
    print("=" * 72)
    print(f"AstrBot 发送接口：{ASTROBOT_SEND_URL}")
    print(f"目标群：{GROUP_ID}（umo = {IM_PLATFORM}:GroupMessage:{GROUP_ID}）")
    print("=" * 72)

    if use_file:
        ok = file_apply_global(im_key, apply_flag=apply_flag)
    else:
        port = find_api_port()
        if port is None:
            print("[错误] 没找到 mas 的 HTTP API（试过 " + "、".join(map(str, MAS_API_PORTS)) + "）。")
            print("       请确认 mas 正在运行；或用 --file 模式（需先完全退出 mas）。")
            sys.exit(1)
        print(f"[API] 使用 mas 后端 127.0.0.1:{port}")
        ok = api_apply_global(port, im_key, apply_flag=apply_flag)
        if ok and apply_flag and do_test:
            api_test(port, im_key)

    if not apply_flag:
        print("\n[预览模式] 未做任何改动。确认后加 --apply 真正写入。")
        return
    if not ok:
        sys.exit(2)
    print("\n下一步：到 mas「设置 → 通知设置」应能看到「自定义渠道 → 自定义 Webhook」里有 1 条；")
    print("       也可在界面点「发送测试通知」验证。")


if __name__ == "__main__":
    main()
