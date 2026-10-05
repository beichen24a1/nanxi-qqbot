# -*- coding: utf-8 -*-
"""列出/检查 data_v4.db 里的 conversations（只读）。

用法：
  python tools\\inspect_conversations.py            # 列出所有会话行
  python tools\\inspect_conversations.py <cid>      # 展开某个会话的消息
"""
import json
import sqlite3
import sys

DB = r"D:\dsh\QQbot\astrbot\data\data_v4.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

print("=== 所有会话行 ===")
rows = list(cur.execute(
    "SELECT inner_conversation_id AS cid, conversation_id, platform_id, user_id, "
    "persona_id, title, LENGTH(content) AS n, updated_at "
    "FROM conversations ORDER BY updated_at DESC"
))
for r in rows:
    print(f"cid={r['cid']}  conv_id={r['conversation_id']}")
    print(f"   platform={r['platform_id']}  user={r['user_id']}  persona={r['persona_id']}")
    print(f"   title={r['title']}  len={r['n']}  updated={r['updated_at']}")

if len(sys.argv) > 1:
    cid = int(sys.argv[1])
    r = cur.execute(
        "SELECT * FROM conversations WHERE inner_conversation_id=?", (cid,)
    ).fetchone()
    try:
        msgs = json.loads(r["content"])
    except Exception as e:  # noqa: BLE001
        print("JSON parse failed:", e)
        print((r["content"] or "")[:2000])
        sys.exit(0)
    print()
    print(f"=== cid={cid} 共 {len(msgs)} 条消息 ===")
    for i, m in enumerate(msgs):
        role = m.get("role")
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(str(x.get("text", x)) for x in c)
        c = (c or "").replace("\n", "\\n")
        print(f"[{i}] {role} ({len(c)}): {c[:400]}")

con.close()
