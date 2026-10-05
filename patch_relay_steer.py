"""给星驿的 ``/message`` 加「插队」（steer）支持。

## 为什么要它

DSH 的 agent handle 有**两种**投递语义（`dsh-agent/lib/types/runtime-types.d.ts:192-200`）：

    followup(message)   // 排队：等当前 turn 跑完才轮到你
    steer(message)      // 插队：投到当前 turn **最近的 step 边界**，不等它跑完

星驿只用了 ``followup``，所以「会话正忙时补一句话」只能干等（或者被背压 409/429 挡回来）。
本补丁让 ``POST /message`` 的请求体多认一个 ``mode`` 字段：

    {"conversation": …, "text": …, "mode": "steer"}   → 走 agent.steer（插队）
    （不写 mode，或写别的值）                          → 照旧 agent.followup（排队）

## 改哪里

``lib/index.js`` 里那一处

    bridge.agent.followup(createUserMessage({ … }))

换成先建消息、再按 ``body.mode`` 二选一。**只改这一处**（脚本会校验它唯一），
中间那段 ``createUserMessage({...})`` 原样保留 —— 图片/文本顺序等契约不受影响。

## 用法

    python patch_relay_steer.py --dry-run      # 只看会改什么
    python patch_relay_steer.py --all          # 两个 profile 都打（nanxi + web）
    python patch_relay_steer.py --revert --all # 撤掉

⚠️ **改完必须重启对应的 DSH 实例才会生效** —— HMR 只热重载配置，不会重新 import ``lib/*.js``
（本项目 2026-10-04 实测过这条）。⚠️ 升级 ``dsh-astrbot-relay`` 后补丁会丢，要重跑。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

MARK = "nanxi:steer"

#: 目标锚点：**星驿投递用户消息的那一处**。
#: ⚠️ `bridge.agent.followup(createUserMessage({` 在文件里出现**两次** —— 另一处（约 1354 行）
#: 是**自主心跳**（`source: { kind: 'plugin', … }`），语义完全不同、绝不能一起改。
#: 所以锚点带上 `/message` 那处独有的注释（v0.9.5 的图在前文在后），保证唯一。
ANCHOR = """bridge.agent.followup(createUserMessage({
          // v0.9.5：图在**前**、文在**后**（契约 §3.1）"""

COMMENT = (
    f"/* {MARK} — body.mode === 'steer' 时改走 agent.steer（插队：投到当前 turn 最近的\n"
    "           step 边界，不等它跑完）；本机补丁，升级 dsh-astrbot-relay 后会丢，\n"
    "           重跑仓库根的 patch_relay_steer.py 即可。 */"
)

DEFAULT_PATHS = (
    Path(r"D:\dsh\nanxi-dsh\profiles\nanxi\node_modules\dsh-astrbot-relay"),
    Path(r"C:\Users\Administrator\.dsh\profiles\web\node_modules\dsh-astrbot-relay"),
)


def build_patch(src: str) -> str:
    """把 ``followup(createUserMessage({...}))`` 换成带 mode 分支的版本。

    Args:
        src: ``lib/index.js`` 的完整文本。

    Returns:
        str: 打好补丁的文本。

    Raises:
        SystemExit: 锚点数量不是 1（找不到，或者上游改了、出现多处）。
    """
    if MARK in src:
        raise SystemExit("已经打过这个补丁了（幂等，不做二次修改）。")
    if src.count(ANCHOR) != 1:
        raise SystemExit(
            f"锚点出现 {src.count(ANCHOR)} 次（期望 1 次）—— 上游可能改过这段，请人工确认。"
        )

    start = src.index(ANCHOR)
    end = src.index("}))", start) + 3
    block = src[start:end]
    # 剥掉 "bridge.agent.followup(" 和最后一个 ")"，留下 createUserMessage({...})
    inner = block[len("bridge.agent.followup(") : -1]
    replacement = (
        f"{COMMENT}\n"
        "        const nanxiUserMessage =\n"
        f"          {inner}\n"
        "        if (body.mode === 'steer' && typeof bridge.agent.steer === 'function') {\n"
        "          bridge.agent.steer(nanxiUserMessage)\n"
        "        } else {\n"
        "          bridge.agent.followup(nanxiUserMessage)\n"
        "        }"
    )
    return src[:start] + replacement + src[end:]


def strip_patch(src: str) -> str:
    """把补丁撤掉，还原成单一 ``followup(createUserMessage({...}))``。

    Args:
        src: 打过补丁的 ``lib/index.js`` 文本。

    Returns:
        str: 还原后的文本。

    Raises:
        SystemExit: 文本里没有本补丁的标记。
    """
    if MARK not in src:
        raise SystemExit("没有找到本补丁的标记，无法撤销。")
    start = src.index(f"/* {MARK}")
    end = src.index("        }", src.index("bridge.agent.followup(nanxiUserMessage)", start)) + len("        }")
    block = src[start:end]
    head = block.index("const nanxiUserMessage =")
    tail = block.index("\n", head)
    inner = block[head + len("const nanxiUserMessage =") : tail].strip()
    return src[:start] + f"        bridge.agent.followup({inner})" + src[end:]


def main() -> int:
    ap = argparse.ArgumentParser(description="给星驿的 /message 加 steer（插队）支持")
    ap.add_argument("--path", action="append", default=[], help="relay 安装目录（可多次）")
    ap.add_argument("--all", action="store_true", help="两个已知 profile 都打")
    ap.add_argument("--revert", action="store_true", help="撤掉补丁")
    ap.add_argument("--dry-run", action="store_true", help="只显示会改什么，不写盘")
    args = ap.parse_args()

    targets: list[Path] = [Path(p) for p in args.path]
    if args.all or not targets:
        targets.extend(DEFAULT_PATHS)

    for root in targets:
        target = root / "lib" / "index.js"
        if not target.is_file():
            print(f"跳过（没有这个文件）：{target}")
            continue
        src = target.read_text(encoding="utf-8")
        try:
            out = strip_patch(src) if args.revert else build_patch(src)
        except SystemExit as exc:
            print(f"{target}: {exc}")
            continue
        if out == src:
            print(f"{target}: 无需改动")
            continue
        if args.dry_run:
            print(f"{target}: 会改动（{len(out) - len(src):+d} 字节）")
            continue
        shutil.copyfile(target, target.with_suffix(".js.bak-steer"))
        target.write_text(out, encoding="utf-8")
        print(f"{target}: 已{'撤销' if args.revert else '打好'}补丁（备份 *.js.bak-steer）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
