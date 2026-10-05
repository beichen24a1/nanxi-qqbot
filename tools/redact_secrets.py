# -*- coding: utf-8 -*-
"""把仓库里**已被跟踪**的文件中泄漏的真实凭据替换成占位符。

为什么需要：本仓准备推到公开 GitHub 分享时，扫描发现**真凭据**（不是占位符）散落在
已跟踪的文件里 —— 尤其是 `_scripts_archive/`（它有 67 个文件早在库里，
`.gitignore` 里虽写了它，但**对已跟踪文件无效**）。

⚠️ **本脚本刻意不内置任何凭据明文** —— 待替换的串必须由调用方传进来。
   理由：第一版我把两个密码写进了 `REPLACEMENTS` 字典，那等于"脱敏工具自己就是泄漏源"，
   一旦提交进仓，扫描就白做了。**凭据只能从命令行或仓外文件进来。**

编码：`.md`/`.py` 是 UTF-8，`启动/*.ps1` 是 **UTF-8 带 BOM**（PowerShell 5.1 需要），
     写回时保持原有 BOM 状态，否则脚本文本会变乱码。

用法：
    # 干跑（只报告命中）：
    python tools\\redact_secrets.py --secret "真密码=<REDACTED-X>"
    # 真改：
    python tools\\redact_secrets.py --secret "真密码=<REDACTED-X>" --apply
    # 多个凭据可以给多次 --secret，或用仓外的清单文件（每行 明文=占位符）：
    python tools\\redact_secrets.py --secrets-file D:\\tmp\\secrets.txt --apply
"""
import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(r"D:\dsh\QQbot")

#: 当文本文件处理的后缀（其余按二进制跳过，避免误伤 png/zip/db）。
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".js", ".mjs", ".cjs",
    ".ps1", ".bat", ".cmd", ".sh", ".html", ".css", ".toml", ".cfg", ".ini",
    ".ts", ".tsx", ".vue",
}


def tracked_files() -> list[pathlib.Path]:
    """列出 git 跟踪的文件（不是工作区全部文件 —— 只看会被推上去的那些）。"""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, shell=False
    ).stdout.decode("utf-8", "replace")
    return [ROOT / p for p in out.split("\0") if p]


def load_secrets(args: argparse.Namespace) -> dict[str, str]:
    """把 --secret / --secrets-file 收成一个 {明文: 占位符} 字典。"""
    items: list[str] = list(args.secret or [])
    if args.secrets_file:
        text = pathlib.Path(args.secrets_file).read_text(encoding="utf-8")
        items += [ln.strip() for ln in text.splitlines() if ln.strip() and "=" in ln]
    if not items:
        raise SystemExit(
            "没有给任何待替换的凭据。用 --secret \"明文=占位符\"（可多次），"
            "或 --secrets-file <文件>。\n"
            "⚠️ 本脚本刻意不内置明文 —— 别把凭据写进代码。"
        )
    out: dict[str, str] = {}
    for it in items:
        if "=" not in it:
            raise SystemExit(f"--secret 要写成 明文=占位符，收到：{it}")
        k, v = it.split("=", 1)
        if not k:
            raise SystemExit("明文不能为空")
        out[k] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secret", action="append", default=[],
                    help="明文=占位符，可重复")
    ap.add_argument("--secrets-file", default="",
                    help="每行 明文=占位符 的清单文件（放仓外）")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    replacements = load_secrets(args)

    hits: list[tuple[pathlib.Path, str, int]] = []
    for path in tracked_files():
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".gitignore":
            continue
        text = path.read_bytes().decode("utf-8", "replace")
        for secret in replacements:
            n = text.count(secret)
            if n:
                hits.append((path, secret, n))

    if not hits:
        print("✓ 已跟踪的文本文件里没有发现这些凭据。")
        return 0

    print(f"发现 {len(hits)} 处：")
    for path, secret, n in hits:
        # 只回显前 4 个字符，避免把凭据又打到日志/终端记录里
        print(f"  {path.relative_to(ROOT)}  ×{n}  （{secret[:4]}…）")

    if not args.apply:
        print("\n（干跑，未写入。加 --apply 才真改。）")
        return 0

    changed = 0
    for path, _secret, _n in hits:
        raw = path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig" if has_bom else "utf-8")
        before = text
        for secret, placeholder in replacements.items():
            text = text.replace(secret, placeholder)
        if text == before:
            continue
        out = text.encode("utf-8")
        if has_bom:
            out = b"\xef\xbb\xbf" + out
        path.write_bytes(out)  # 保持原 BOM 状态
        changed += 1
        print(f"  已改 {path.relative_to(ROOT)}（BOM={'有' if has_bom else '无'}）")

    print(f"\n共改写 {changed} 个文件。")
    print(
        "⚠️ 提醒：**git 历史里仍带着原文**（本脚本不动历史）。\n"
        "   推公开仓时用「干净单提交」导出（原仓历史原地保留），别直接 push master ——\n"
        "   否则别人 `git log -p` 一样能看到。"
    )
    return 0


raise SystemExit(main())
