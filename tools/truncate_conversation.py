# -*- coding: utf-8 -*-
"""把某个 AstrBot 会话裁到指定长度（默认干跑，--apply 才写）。

为什么需要它：AstrBot 的对话历史里一旦出现过「我的工具不见了」，
模型之后就会**继续照着演**（AGENTS.md 坑 3），哪怕工具早就修好了。
最干净的解法是把被污染的那几条尾巴切掉，而不是把整段群聊记忆清空。

用法：
  python tools\\truncate_conversation.py 1 496            # 干跑，只报告
  python tools\\truncate_conversation.py 1 496 --apply    # 真写（自动备份）
"""
import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path

DB = Path(r"D:\dsh\QQbot\astrbot\data\data_v4.db")


def brief(m):
    c = m.get("content")
    if isinstance(c, list):
        c = " ".join(str(x.get("text", x)) for x in c)
    c = (c or "").replace("\n", "\\n")
    return f"{m.get('role')}: {c[:140]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cid", type=int)
    ap.add_argument("keep", type=int, help="保留前 N 条消息")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    row = cur.execute(
        "SELECT content FROM conversations WHERE inner_conversation_id=?",
        (args.cid,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"没有 inner_conversation_id={args.cid} 的会话")

    msgs = json.loads(row["content"])
    print(f"cid={args.cid} 现有 {len(msgs)} 条，保留前 {args.keep} 条")
    if not (0 < args.keep <= len(msgs)):
        raise SystemExit("keep 超出范围")

    print("--- 将被删除的消息 ---")
    for i in range(args.keep, len(msgs)):
        print(f"  [{i}] {brief(msgs[i])}")
    print("--- 截断后的最后一条 ---")
    print(f"  [{args.keep - 1}] {brief(msgs[args.keep - 1])}")

    if not args.apply:
        print("\n（干跑，未写入。加 --apply 才真写。）")
        return

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = DB.with_name(DB.name + f".bak-before-truncate{args.cid}-{stamp}")
    shutil.copy2(DB, bak)
    print(f"\n已备份 -> {bak}")

    new_content = json.dumps(msgs[: args.keep], ensure_ascii=False)
    cur.execute(
        "UPDATE conversations SET content=? WHERE inner_conversation_id=?",
        (new_content, args.cid),
    )
    con.commit()
    n = cur.execute(
        "SELECT LENGTH(content) FROM conversations WHERE inner_conversation_id=?",
        (args.cid,),
    ).fetchone()[0]
    print(f"已写入：新长度 {len(new_content)} 字符（DB 里报 {n}）")
    con.close()


main()
