"""把 AstrBot 内置 `stop` 命令的两条英文回执改成中文（南汐的口吻）。

为什么需要这个脚本
-----------------
`@南汐 stop` 走的是 AstrBot **内置**命令，不是我们的插件：

    astrbot/builtin_stars/builtin_commands/commands/conversation.py
        stop() -> active_event_registry.request_agent_stop_all(...)
        if stopped_count > 0:
            MessageEventResult().message(f"✅ Requested to stop {n} running tasks.")
        else:
            MessageEventResult().message("✅ No running tasks in the current session.")

这两句**一定**会回（哪怕一条任务都没在跑），而我们的插件
（`astrbot_plugin_nanxi_dsh`）在停止回调里也会让 LLM 用人设补一句 ——
2026-10-04 实测群里因此出现**两条**：

    ✅ Requested to stop 1 running tasks.
    （已经叫停了）

插件的 `_say` 已经删掉（那条是我们自己的，删得掉）；剩下这条英文是**上游硬编码**的，
插件钩子够不着，只能改上游源码。而 `astrbot/` 整个目录被 .gitignore 排除（上游 clone），
所以这个改动无法靠 git 保存：AstrBot 升级 / 重装后会丢，重新跑一次本脚本即可。

用法（幂等，可反复执行）
------------------------
    C:\\Python310\\python.exe D:\\dsh\\QQbot\\patch_astrbot_stop_reply.py
    C:\\Python310\\python.exe D:\\dsh\\QQbot\\patch_astrbot_stop_reply.py --dry-run
    C:\\Python310\\python.exe D:\\dsh\\QQbot\\patch_astrbot_stop_reply.py --revert

改完**必须重启 AstrBot** 才生效。
"""

import sys
from pathlib import Path

TARGET = Path(
    r"D:\dsh\QQbot\astrbot\astrbot\builtin_stars\builtin_commands\commands\conversation.py"
)

# (上游英文版, 中文版)
PAIRS = [
    (
        'f"✅ Requested to stop {stopped_count} running tasks."',
        'f"（已经叫停了 {stopped_count} 项任务）"',
    ),
    (
        '"✅ No running tasks in the current session."',
        '"（这边没有正在跑的任务）"',
    ),
]


def main() -> int:
    args = [a for a in sys.argv[1:]]
    revert = "--revert" in args
    dry_run = "--dry-run" in args
    for a in args:
        if a not in ("--revert", "--dry-run"):
            print(f"[FAIL] 未知参数：{a}（只认 --revert / --dry-run）")
            return 2

    if not TARGET.is_file():
        print(f"[FAIL] 找不到目标文件：{TARGET}")
        return 1

    text = TARGET.read_text(encoding="utf-8")
    original = text

    # revert: 中文 -> 英文；apply: 英文 -> 中文
    todo = [(zh, en) if revert else (en, zh) for en, zh in PAIRS]
    label = "还原成上游英文" if revert else "改成中文"

    changed, missing, skipped = [], [], []
    for src, dst in todo:
        if src in text:
            if text.count(src) != 1:
                print(f"[FAIL] 预期只出现一次，实际 {text.count(src)} 次：{src}")
                return 3
            text = text.replace(src, dst, 1)
            changed.append(dst)
        elif dst in text:
            skipped.append(dst)  # 已经是目标状态（幂等）
        else:
            missing.append(src)

    if missing:
        print("[FAIL] 没找到预期的那一行，AstrBot 可能已升级或改版，请人工确认。")
        for m in missing:
            print(f"       期望包含：{m}")
        return 4

    if not changed:
        print(f"[OK] 两处都已经是目标状态（{label}），无需改动（幂等）")
        for s in skipped:
            print(f"     · {s}")
        return 0

    if dry_run:
        print(f"[DRY-RUN] 会{label}（未写入）：")
        for s in skipped:
            print(f"     · 已是：{s}")
        for c in changed:
            print(f"     · 将改为：{c}")
        return 0

    if text == original:
        print("[OK] 内容无变化（幂等）")
        return 0

    TARGET.write_text(text, encoding="utf-8")
    print(f"[DONE] 已{label}：{TARGET}")
    for c in changed:
        print(f"     · {c}")
    print("       重启 AstrBot 后生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
