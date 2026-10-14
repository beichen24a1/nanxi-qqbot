"""AstrBot 离线配置写入：检查监听、保留 BOM、备份并原子替换。"""
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / "astrbot" / "data" / "cmd_config.json"


def listening_ports(ports=(6185, 3002)):
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            errors="replace", timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("无法检查 AstrBot 监听状态；拒绝写入配置。") from exc
    if result.returncode:
        raise RuntimeError("无法检查 AstrBot 监听状态；拒绝写入配置。")
    busy = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0] == "TCP" and fields[3] == "LISTENING":
            port = fields[1].rsplit(":", 1)[-1]
            if port.isdigit() and int(port) in ports:
                busy.add(int(port))
    return sorted(busy)


def load_config(config_path):
    raw = Path(config_path).read_bytes()
    config = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("配置根节点必须是 JSON 对象。")
    return raw, config


def write_config(config_path, original, config, label):
    """实际有改动时调用；运行状态未知或读后配置变化都拒绝写入。"""
    busy = listening_ports()
    if busy:
        raise RuntimeError(
            f"AstrBot 仍在监听 {busy}；先运行 启动/stop_astrbot.bat，再修改配置。"
        )
    config_path = Path(config_path)
    if config_path.read_bytes() != original:
        raise RuntimeError("配置在预览后被其他进程修改；请重新运行。")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir = REPO / "_backup" / datetime.now().strftime("%Y%m%d")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{config_path.name}.bak-before-{label}-{stamp}"
    backup.write_bytes(original)
    prefix = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
    output = prefix + (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=config_path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write(output)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_path, config_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    if load_config(config_path)[1] != config:
        raise RuntimeError(f"配置写回验证失败；原文件备份在 {backup}")
    return backup
