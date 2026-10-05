"""把 AstrBot 合并转发卡片上的发送者名字从 "AstrBot" 改成 "南汐"。

为什么需要这个脚本
------------------
AstrBot 把长回复包成合并转发时，那条 Node 的发送者名字是**上游硬编码**的：

    astrbot/core/pipeline/result_decorate/stage.py
        node = Node(uin=event.get_self_id(), name="AstrBot", content=[...])

插件侧改不到它 —— `@filter.on_decorating_result()` 那个钩子在
`result_decorate/stage.py` 里是**先跑**的（约 158 行），而 Node 是**后包**的（约 415 行），
钩子执行时 Node 还不存在。

而 `astrbot/` 整个目录被 .gitignore 排除（上游 clone），所以这个改动无法靠 git 保存：
AstrBot 升级 / 重装后会丢，重新跑一次本脚本即可。

用法（幂等，可反复执行）
------------------------
    C:\\Python310\\python.exe D:\\dsh\\QQbot\\patch_astrbot_forward_name.py

改完**必须重启 AstrBot** 才生效。
"""

import sys
from pathlib import Path

TARGET = Path(r"D:\dsh\QQbot\astrbot\astrbot\core\pipeline\result_decorate\stage.py")
OLD = 'name="AstrBot",'
NEW = 'name="南汐",'
ALREADY = 'name="南汐"'


def main() -> int:
    if not TARGET.is_file():
        print(f"[FAIL] 找不到目标文件：{TARGET}")
        return 1

    text = TARGET.read_text(encoding="utf-8")

    if ALREADY in text:
        print("[OK] 已经是「南汐」，无需改动（幂等）")
        return 0

    if OLD not in text:
        print("[FAIL] 没找到预期的那一行，AstrBot 可能已升级或改版，请人工确认。")
        print(f"       期望包含：{OLD}")
        return 2

    TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"[DONE] 已改：{TARGET}")
    print("       重启 AstrBot 后生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
