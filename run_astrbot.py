"""AstrBot 启动器：为 pywin32 设置路径后运行 main.py。

背景：AstrBot 的 mcp 依赖在 Windows 上 import pywintypes，需要
- win32\lib 在 sys.path（pywintypes.py loader）
- pywin32_system32 注册为 DLL 目录（加载 pywintypes313.dll）
由于我们以 --target 安装到 data/site-packages，.pth 不生效，故在此手动设置。
"""
import os
import sys
import runpy

ASP = r"D:\dsh\QQbot\astrbot"
SP = os.path.join(ASP, "data", "site-packages")

# 1) 把 site-packages 及其 win32 相关子目录加入 sys.path
for p in [SP, os.path.join(SP, "win32"), os.path.join(SP, "win32", "lib")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# 2) 注册 DLL 目录（Python 3.8+）
if hasattr(os, "add_dll_directory"):
    for dll_dir in [os.path.join(SP, "pywin32_system32")]:
        try:
            os.add_dll_directory(dll_dir)
        except Exception as e:  # noqa: BLE001
            print("[run_astrbot] add_dll_directory failed:", e)

# 3) 确保运行目录正确
os.chdir(ASP)
sys.path.insert(0, ASP)

print("[run_astrbot] launching main.py")
runpy.run_path(os.path.join(ASP, "main.py"), run_name="__main__")
