# -*- coding: utf-8 -*-
"""在指定会话里按关键词检索消息（只读）。"""
import json
import sqlite3
import sys

DB = r"D:\dsh\QQbot\astrbot\data\data_v4.db"
cid = int(sys.argv[1])
kws = sys.argv[2:] or ["找不到", "没有", "没了", "不可用", "工具"]

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
row = con.execute(
    "SELECT content FROM conversations WHERE inner_conversation_id=?", (cid,)
).fetchone()
msgs = json.loads(row["content"])
print(f"共 {len(msgs)} 条消息，检索 {kws}")
for i, m in enumerate(msgs):
    c = m.get("content")
    if isinstance(c, list):
        c = " ".join(str(x.get("text", x)) for x in c)
    c = c or ""
    if any(k in c for k in kws):
        role = m.get("role")
        snip = c.replace("\n", "\\n")[:260]
        print(f"[{i}] {role}: {snip}")
con.close()
