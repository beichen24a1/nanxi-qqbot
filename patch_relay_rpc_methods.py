# -*- coding: utf-8 -*-
"""给星驿（dsh-astrbot-relay）补一条 RPC 描述符：``workspace/unarchiveSession``。

背景
----
DSH 的 workspace 控制器**确实有** ``unarchiveSession``（``@Remote('unarchiveSession')``，
见 ``@deepseek-ai/dsh-api-workspace-controller/lib/typert.host.js`` 的描述符，请求体是
``WorkspaceUnarchiveSessionRequest { sessionId }``）。但星驿的 ``lib/rpc-methods.js``
—— 由**已不再随包发布**的 ``data/p5_rpc_descriptors.json``（84 条）自动生成的产物 ——
只收录了 ``workspace/archiveSession``，**漏了** ``unarchiveSession``。

而星驿对 ``Config.allowedRpcMethods`` 有硬校验（``lib/index.js`` 约 2955 行）：

    allowedRpcMethods 里的 ${endpoint} 不在描述符表里  → 直接抛错、插件起不来

于是「撤回刚刚的归档」这条能力被卡在**描述符**这一层：DSH 有、星驿不认。
本脚本把这一条补回去（``RPC_WIRE_KEYS`` 加一项、``RPC_METHOD_COUNT`` 84 → 85）。

⚠️ 改的是 ``node_modules`` 里的**上游产物**，升级 ``dsh-astrbot-relay`` 会丢 ——
   升级后重跑本脚本即可（这正是它被写成脚本、而不是手工编辑的原因）。

用法
----
    python patch_relay_rpc_methods.py                 # 打补丁（默认 nanxi 实例 3081）
    python patch_relay_rpc_methods.py --revert        # 还原
    python patch_relay_rpc_methods.py --path <目录>   # 指定某个 dsh-astrbot-relay 目录
    python patch_relay_rpc_methods.py --all           # nanxi + 主实例都打

改完必须**重启对应的 DSH 实例**（nanxi 是双击 ``启动\\start-nanxi-dsh.bat``）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

#: 默认目标：南汐的独立实例（AstrBot 两个插件都指向 3081）。
DEFAULT_RELAY_DIRS = [
    Path(r"D:\dsh\nanxi-dsh\profiles\nanxi\node_modules\dsh-astrbot-relay"),
]
#: --all 时追加主实例（3080）。
MAIN_RELAY_DIR = Path(
    r"C:\Users\Administrator\.dsh\profiles\web\node_modules\dsh-astrbot-relay"
)

ANCHOR = "  'workspace/archiveSession': ['request'],"
INSERT = "  'workspace/unarchiveSession': ['request'],"
COUNT_OLD = "export const RPC_METHOD_COUNT = 84"
COUNT_NEW = "export const RPC_METHOD_COUNT = 85"


def patch_one(relay_dir: Path, *, revert: bool, dry_run: bool = False) -> int:
    target = relay_dir / "lib" / "rpc-methods.js"
    if not target.is_file():
        print(f"  [跳过] 找不到 {target}")
        return 0

    text = target.read_text(encoding="utf-8")
    has_insert = INSERT in text

    if revert:
        if not has_insert:
            print(f"  [已是原样] {target}")
            return 0
        new = text.replace(INSERT + "\n", "", 1).replace(COUNT_NEW, COUNT_OLD)
        if dry_run:
            print(f"  [预览] 将还原 {target}")
            return 1
        target.write_text(new, encoding="utf-8")
        print(f"  [已还原] {target}")
        return 1

    if has_insert:
        print(f"  [已打过] {target}（幂等跳过）")
        return 0

    if ANCHOR not in text:
        print(f"  [失败] {target} 里找不到锚点行，未改动 —— 上游结构可能变了，需人工看一眼")
        return 2

    new = text.replace(ANCHOR, ANCHOR + "\n" + INSERT, 1)
    if COUNT_OLD in new:
        new = new.replace(COUNT_OLD, COUNT_NEW, 1)
    else:
        print("  [警告] 没找到 RPC_METHOD_COUNT = 84，只插入了描述符（条数元数据留旧值）")

    if dry_run:
        print(f"  [预览] 将给 {target} 插入 workspace/unarchiveSession")
        return 1

    target.write_text(new, encoding="utf-8")
    print(f"  [已打补丁] {target}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="给星驿补 workspace/unarchiveSession 描述符")
    ap.add_argument("--path", help="指定单个 dsh-astrbot-relay 目录")
    ap.add_argument("--all", action="store_true", help="nanxi + 主实例都处理")
    ap.add_argument("--revert", action="store_true", help="还原改动")
    ap.add_argument("--dry-run", action="store_true", help="只看会做什么")
    args = ap.parse_args()

    dirs = [Path(args.path)] if args.path else list(DEFAULT_RELAY_DIRS)
    if args.all:
        dirs.append(MAIN_RELAY_DIR)

    print(("还原" if args.revert else "打补丁") + "：")
    changed = 0
    for d in dirs:
        changed += patch_one(d, revert=args.revert, dry_run=args.dry_run)

    if not args.dry_run:
        print()
        if changed:
            print("完成 —— 别忘了重启对应 DSH 实例才生效：")
            print("  nanxi：双击  启动\\start-nanxi-dsh.bat")
        else:
            print("无需改动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
