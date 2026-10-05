# -*- coding: utf-8 -*-
"""把 browser.py 里 `click()` 内联的那段 JS 抠出来做语法检查（node --check）。

为什么值得单独写：那段 JS 是**用 Python 字符串拼出来的**，Python 本身语法正确
不代表拼出来的 JS 正确（少个括号、引号错位都会等到运行时才发现，而运行时要重启
AstrBot + 发一条 QQ 消息才试得到）。这里直接把拼装结果落到临时文件让 node 检。
"""
import json
import pathlib
import re
import subprocess
import sys

SRC = pathlib.Path(r"D:\dsh\QQbot\astrbot_plugin_nanxi_dsh\browser.py")
OUT = pathlib.Path(r"D:\dsh\QQbot\tools\_click_inline.js")

text = SRC.read_text(encoding="utf-8")

# 定位 `js = (` ... `) % json.dumps(target)` 这一段
TAIL = ") % json.dumps(target)"
start = text.index("        js = (\n")
end = text.index(TAIL, start) + len(TAIL)
block = text[start:end]
# 去掉 "js = (" 前缀，留下括号里的表达式
expr = block.split("=", 1)[1].strip()

target = "nx_dsh"
js = eval(expr, {"json": json, "target": target})  # noqa: S307 - 只为本机自检

OUT.write_text(js, encoding="utf-8")
print(f"抠出 {len(js)} 字符 -> {OUT}")

r = subprocess.run(
    ["node", "--check", str(OUT)], capture_output=True, text=True, shell=False
)
print("node --check 退出码:", r.returncode)
if r.stdout.strip():
    print(r.stdout)
if r.stderr.strip():
    print(r.stderr)
sys.exit(r.returncode)
