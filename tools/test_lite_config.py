"""配置写入边界回归：运行中拒写、BOM/备份、幂等、点歌保留和通知目标。"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import astrbot_config_guard as guard
import shutdown_nanxi_ai as shutdown
import set_image_caption_off as caption

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("mas_notify_setup", ROOT / "游戏通知/apply_mas_webhook.py")
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "cmd_config.json"
        self.original_config = {
            "provider_settings": {"enable": True, "web_search": True, "default_provider_id": "example"},
            "provider_ltm_settings": {"image_caption": True, "image_caption_provider_id": "example-vision"},
            "plugin_set": ["*"],
            "provider": [{"api_key": "test-value-kept-local"}],
            "platform_settings": {"example": True},
        }

    def write(self, bom=False):
        raw = json.dumps(self.original_config, ensure_ascii=False).encode("utf-8")
        self.config.write_bytes((b"\xef\xbb\xbf" if bom else b"") + raw)
        return self.config.read_bytes()

    def run_shutdown(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return shutdown.main(["--config", str(self.config), *args])

    def test_preview_keeps_bytes_even_when_running(self):
        original = self.write()
        with patch.object(guard, "listening_ports", return_value=[6185]) as check:
            self.assertEqual(self.run_shutdown("--dry-run"), 0)
            check.assert_not_called()
        self.assertEqual(self.config.read_bytes(), original)

    def test_apply_refuses_running_bot_without_backup(self):
        original = self.write()
        with patch.object(guard, "REPO", self.root), patch.object(guard, "listening_ports", return_value=[3002]):
            self.assertEqual(self.run_shutdown("--apply"), 2)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertFalse((self.root / "_backup").exists())

    def test_apply_keeps_bom_credentials_and_music(self):
        for bom in (False, True):
            with self.subTest(bom=bom):
                original = self.write(bom)
                with patch.object(guard, "REPO", self.root), patch.object(guard, "listening_ports", return_value=[]):
                    self.assertEqual(self.run_shutdown("--apply"), 0)
                    result = guard.load_config(self.config)[1]
                    self.assertEqual(result["plugin_set"], shutdown.LITE_PLUGINS)
                    self.assertFalse(result["provider_settings"]["enable"])
                    self.assertFalse(result["provider_settings"]["web_search"])
                    self.assertFalse(result["provider_ltm_settings"]["image_caption"])
                    self.assertEqual(result["provider_ltm_settings"]["image_caption_provider_id"], "")
                    self.assertEqual(result["provider"], self.original_config["provider"])
                    self.assertEqual(result["platform_settings"], self.original_config["platform_settings"])
                    self.assertEqual(self.config.read_bytes().startswith(b"\xef\xbb\xbf"), bom)
                    backups = list((self.root / "_backup").rglob("*.bak-*"))
                    self.assertTrue(any(b.read_bytes() == original for b in backups))
                    count = len(backups)
                    current = self.config.read_bytes()
                    self.assertEqual(self.run_shutdown("--apply"), 0)
                    self.assertEqual(self.config.read_bytes(), current)
                    self.assertEqual(len(list((self.root / "_backup").rglob("*.bak-*"))), count)

    def test_missing_sections_refuse_apply(self):
        self.config.write_text('{"provider_settings":{}}', encoding="utf-8")
        original = self.config.read_bytes()
        self.assertEqual(self.run_shutdown("--apply"), 2)
        self.assertEqual(self.config.read_bytes(), original)

    def test_caption_tool_refuses_running_bot(self):
        original = self.write(True)
        with patch.object(guard, "listening_ports", return_value=[6185]), patch.object(sys, "argv", ["caption", "--config", str(self.config), "--apply"]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(caption.main(), 2)
        self.assertEqual(self.config.read_bytes(), original)

    def test_changed_config_is_never_overwritten(self):
        original = self.write()
        self.config.write_text('{"changed":true}', encoding="utf-8")
        with patch.object(guard, "listening_ports", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "其他进程"):
                guard.write_config(self.config, original, {}, "test")
        self.assertEqual(self.config.read_text(), '{"changed":true}')

    def test_ipv6_and_exact_port_detection(self):
        result = type("Result", (), {"returncode": 0, "stdout": "TCP [::]:6185 [::]:0 LISTENING 5\nTCP 127.0.0.1:13002 0.0.0.0:0 LISTENING 6\nTCP 127.0.0.1:3002 127.0.0.1:8 ESTABLISHED 7"})()
        with patch.object(guard.subprocess, "run", return_value=result):
            self.assertEqual(guard.listening_ports(), [6185])

    def test_unknown_port_status_refuses_write(self):
        self.write()
        result = type("Result", (), {"returncode": 1, "stdout": ""})()
        with patch.object(guard.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError):
                guard.write_config(self.config, self.config.read_bytes(), {}, "test")

    def test_notify_uses_local_target(self):
        p = self.root / "notify.json"
        p.write_text(json.dumps({"group_id": "123456", "im_platform": "example-platform", "im_api_key": "test-value"}), encoding="utf-8-sig")
        with patch.object(notify, "NANXI_CONFIG", str(p)), patch.object(notify, "GROUP_ID", ""), patch.object(notify, "IM_PLATFORM", "example-platform"):
            self.assertEqual(notify.load_im_key(), "test-value")
            self.assertEqual(json.loads(notify.build_template("{title}"))["umo"], "example-platform:GroupMessage:123456")

    def test_notify_refuses_placeholder_target(self):
        p = self.root / "notify.json"
        p.write_text(json.dumps({"group_id": "<TEST_GROUP_ID>", "im_api_key": "test-value"}), encoding="utf-8")
        with patch.object(notify, "NANXI_CONFIG", str(p)), patch.object(notify, "GROUP_ID", ""), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                notify.load_im_key()

    def test_notify_propagates_failed_delivery_test(self):
        with patch.object(sys, "argv", ["notify", "--apply", "--test"]), patch.object(notify, "load_im_key", return_value="test-value"), patch.object(notify, "find_api_port", return_value=1234), patch.object(notify, "api_apply_global", return_value=True), patch.object(notify, "api_test", return_value=False), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                notify.main()
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
