"""堵上「审批没被星驿接管」——给它补 session 兜底 + 诊断日志。

## 问题

星驿的审批 waterfall 只按 ``agent.id`` 反查网桥：

    const bridge = bridgeByAgent(request?.agent?.id)
    if (!bridge || !config.approvalEnabled) return next()   // ← 没认出来就交回 DSH

``bridgeByAgent`` 是遍历 ``bridges`` 比对 ``bridge.agent?.id``。一旦那个 agent **换了实例**
（会话重 attach、子 agent、或 bridge 尚未 attach），比对就失败 ⇒ ``next()`` ⇒ 落到 **DSH 自带的
审批框**（GUI 里那个「等待审批 / 允许一次」）⇒ **IM 侧完全收不到、主人不会被通知**，
而且它**不受星驿的 120 秒超时**约束，会一直挂着。

2026-10-04 实测踩到：主人在 GUI 里看到一个挂了 4 分多钟的审批，群里一个字都没有。

## 改法

1. **补 session 兜底**：星驿里本来就有 ``bridgeBySession(session)``（按 **session 对象身份**
   反查，注释明说"不比 id，避免同名会话误伤"），这里把它接上：
       bridgeByAgent(agent.id) ?? bridgeBySession(agent.session)
2. **加诊断日志**：两个都认不出来时 ``log.warn`` 把 ``agent.id`` 记下来 ——
   这样下次再出现，日志直接说明是谁没匹配上，不用再从现象倒推。

## 用法

    python patch_relay_approval_bridge.py --dry-run
    python patch_relay_approval_bridge.py --all
    python patch_relay_approval_bridge.py --revert --all

⚠️ **改完必须重启对应的 DSH 实例**（HMR 只热重载配置，不会重新 import ``lib/*.js``）。
⚠️ 升级 ``dsh-astrbot-relay`` 后补丁会丢，要重跑。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

MARK = "nanxi:approval-bridge"

ORIGINAL = """    host.on('approval/request', (request, next) => {
      const bridge = bridgeByAgent(request?.agent?.id)
      // 不接管就让框架按默认策略处理（next 的返回值必须原样透出）。
      if (!bridge || !config.approvalEnabled) return next()
      return askApproval(bridge, request)
    })"""

PATCHED = f"""    host.on('approval/request', (request, next) => {{
      /* {MARK} — 原来只按 agent.id 反查网桥；会话重 attach / 子 agent / 尚未 attach 时
         会比对失败 ⇒ next() ⇒ 落到 DSH 自带审批框，IM 侧收不到、主人也不会被通知，
         而且不受本插件的 120 秒超时约束（2026-10-04 实测：一个挂着 4 分多钟没人知道）。
         这里补上 session 对象身份兜底，并在两者都认不出时留下诊断日志。 */
      const bridge =
        bridgeByAgent(request?.agent?.id) ?? bridgeBySession(request?.agent?.session)
      if (!bridge) {{
        log?.warn?.(
          `${{tag}} 审批没认领到网桥（agent.id=${{request?.agent?.id ?? '-'}}）—— `
            + '它会落到 DSH 自带审批框、IM 侧收不到；请查 bridges 里的 agent 是否已换实例'
        )
      }}
      // 不接管就让框架按默认策略处理（next 的返回值必须原样透出）。
      if (!bridge || !config.approvalEnabled) return next()
      return askApproval(bridge, request)
    }})"""

DEFAULT_PATHS = (
    Path(r"D:\dsh\nanxi-dsh\profiles\nanxi\node_modules\dsh-astrbot-relay"),
    Path(r"C:\Users\Administrator\.dsh\profiles\web\node_modules\dsh-astrbot-relay"),
)


def build_patch(src: str) -> str:
    """把审批 waterfall 换成「agent.id → session」两级反查并加诊断日志。

    Args:
        src: ``lib/index.js`` 的完整文本。

    Returns:
        str: 打好补丁的文本。

    Raises:
        SystemExit: 已经打过补丁，或者锚点不是恰好一处。
    """
    if MARK in src:
        raise SystemExit("已经打过这个补丁了（幂等，不做二次修改）。")
    if src.count(ORIGINAL) != 1:
        raise SystemExit(
            f"锚点出现 {src.count(ORIGINAL)} 次（期望 1 次）—— 上游可能改过这段，请人工确认。"
        )
    return src.replace(ORIGINAL, PATCHED)


def strip_patch(src: str) -> str:
    """撤销补丁。

    Args:
        src: 打过补丁的 ``lib/index.js`` 文本。

    Returns:
        str: 还原后的文本。

    Raises:
        SystemExit: 没有找到补丁标记。
    """
    if MARK not in src:
        raise SystemExit("没有找到本补丁的标记，无法撤销。")
    if src.count(PATCHED) != 1:
        raise SystemExit(f"补丁段落出现 {src.count(PATCHED)} 次，无法安全撤销。")
    return src.replace(PATCHED, ORIGINAL)


def main() -> int:
    ap = argparse.ArgumentParser(description="给星驿的审批 waterfall 补 session 兜底")
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
        if args.dry_run:
            print(f"{target}: 会改动（{len(out) - len(src):+d} 字节）")
            continue
        shutil.copyfile(target, target.with_suffix(".js.bak-approval"))
        target.write_text(out, encoding="utf-8")
        print(f"{target}: 已{'撤销' if args.revert else '打好'}补丁（备份 *.js.bak-approval）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
