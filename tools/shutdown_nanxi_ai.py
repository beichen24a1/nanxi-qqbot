# -*- coding: utf-8 -*-
"""切到精简模式：关闭聊天、联网搜索与图片描述，保留摸头、点歌和通知。

默认只预览。--apply 只在 AstrBot 已停止时写入，自动备份并保留原有 BOM。
插件文件、模型凭据、人格、白名单均保留。配置在别处用 --config 指定。

    python tools/shutdown_nanxi_ai.py --dry-run
    python tools/shutdown_nanxi_ai.py --apply

主动通知使用 AstrBot im-scope API key，不经过聊天模型。plugin_set 只筛选
消息 handler，不阻止插件加载。图片描述独立于 provider_settings.enable，
必须另外关闭；恢复聊天时也不需要重新打开图片描述。
"""
import argparse
import sys
from pathlib import Path

from astrbot_config_guard import DEFAULT_CONFIG, load_config, write_config

LITE_PLUGINS = ["astrbot_plugin_petpet", "astrbot_plugin_netease_pick"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="关闭 AI，保留摸头、点歌和主动通知")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="AstrBot 停止后备份并写入")
    mode.add_argument("--dry-run", action="store_true", help="只预览（默认）")
    args = parser.parse_args(argv)
    try:
        original, config = load_config(args.config)
        provider = config.get("provider_settings")
        ltm = config.get("provider_ltm_settings")
        if not isinstance(provider, dict) or not isinstance(ltm, dict):
            raise ValueError("配置缺少 provider_settings / provider_ltm_settings 对象。")
        changes = []
        for section, key, value, name in [
            (provider, "enable", False, "provider_settings.enable"),
            (provider, "web_search", False, "provider_settings.web_search"),
            (ltm, "image_caption", False, "provider_ltm_settings.image_caption"),
            (ltm, "image_caption_provider_id", "", "provider_ltm_settings.image_caption_provider_id"),
            (config, "plugin_set", LITE_PLUGINS, "plugin_set"),
        ]:
            if section.get(key) != value or (value is False and section.get(key) is not False):
                changes.append(name)
                section[key] = value
        if not changes:
            print("[=] 已是精简模式；摸头、点歌与通知保留，无需改动。")
            return 0
        print("将修改：" + "、".join(changes))
        print("保留 handler：" + "、".join(LITE_PLUGINS))
        if not args.apply:
            print("[i] 预览，未写入。先停 AstrBot，再加 --apply。")
            return 0
        backup = write_config(args.config, original, config, "ai-off")
        print(f"[+] 已写入精简配置；备份：{backup}")
        print("接下来启动 AstrBot，验证摸头、点歌和通知，并检查日志没有模型调用。")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[x] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
