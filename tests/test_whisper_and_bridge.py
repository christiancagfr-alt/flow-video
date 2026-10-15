import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.services import resolve_daily as daily
from app.services.whisper_cpp import discover, extract_zip


class WhisperDiscoveryTests(unittest.TestCase):
    def test_finds_whisper_cpp_and_skips_openai_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cli = root / "bin" / "whisper-cli.exe"
            cli.parent.mkdir()
            cli.write_bytes(b"MZ")
            wrong = root / "Scripts" / "whisper.exe"
            wrong.parent.mkdir()
            wrong.write_bytes(b"MZ")
            model = root / "models" / "ggml-base.bin"
            model.parent.mkdir()
            model.write_bytes(b"ggml" + b"\0" * 8)
            (root / "models" / "ggml-bad.bin").write_bytes(b"not-a-model")
            found = discover(str(wrong), "", roots=[root], include_defaults=False)
            self.assertEqual(found["cli"], str(cli.resolve()))
            self.assertEqual(found["model"], str(model.resolve()))

    def test_zip_slip_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../outside.txt", b"no")
            with self.assertRaises(ValueError):
                extract_zip(archive, root / "out")
            self.assertFalse((root / "outside.txt").exists())


class BridgeHeartbeatTests(unittest.TestCase):
    def test_copy_command_targets_installed_bridge_and_uses_lua_long_brackets(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "FlowStudio_Resolve_Bridge_v1.1.13.lua"
            command = daily.bridge_dofile_command(script)
            self.assertEqual(command, 'dofile([[' + script.resolve().as_posix() + ']])')

    def test_prepare_copy_command_installs_missing_bridge_first(self):
        with tempfile.TemporaryDirectory() as folder:
            script_folder = Path(folder)
            script = script_folder / daily.SCRIPT

            def install():
                script_folder.mkdir(parents=True, exist_ok=True)
                script.write_text('-- bridge', encoding='utf-8')

            with patch.object(daily, 'script_dir', return_value=script_folder), \
                    patch.object(daily, 'install_bridge', side_effect=install) as installer:
                command = daily.prepare_bridge_dofile_command()
            installer.assert_called_once()
            self.assertIn(script.resolve().as_posix(), command)

    def test_sandbox_failure_is_explained_in_chinese(self):
        message = daily.menu_failure_text(
            "BRIDGE_RUNTIME_UNAVAILABLE: [platform.windows=true, io=nil/missing, ffi=nil, loadfile=nil, dofile=nil, platform_adapter=false]"
        )
        self.assertIn("Allow all", message)
        self.assertIn("控制台", message)
        self.assertIn("手动启动 Bridge", message)
        self.assertIn("菜单启动暂不兼容", message)
        self.assertIn("platform_adapter=false", message)

    @unittest.skipUnless(__import__("os").name == "nt", "Windows Resolve log path")
    def test_recent_resolve_sandbox_error_overrides_generic_wake_timeout(self):
        import os

        with tempfile.TemporaryDirectory() as folder:
            appdata = Path(folder)
            log = appdata / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "logs" / "ResolveDebug.txt"
            log.parent.mkdir(parents=True)
            log.write_text(
                "Resolve previous-run: SANDBOX old error\n",
                encoding="utf-8",
            )
            cursor = log.stat().st_size
            root = appdata / "Documents" / "FlowStudioResolveBridge"
            with patch.dict(os.environ, {"APPDATA": str(appdata)}), patch.object(daily, "bridge_root", return_value=root):
                self.assertEqual(daily._recent_resolve_sandbox_error(after_offset=cursor), "")
                with log.open("a", encoding="utf-8") as stream:
                    stream.write("FlowStudio_Resolve_Bridge_v1.1.13.lua:291: BRIDGE_RUNTIME_UNAVAILABLE io-missing ffi=nil [platform.windows=true, io=nil/missing, ffi=nil, loadfile=nil, dofile=nil, platform_adapter=false]\n")
                fresh_error = daily._recent_resolve_sandbox_error(after_offset=cursor)
                reason = daily.bridge_wait_reason(root)
            self.assertIn("不能补回", fresh_error)
            self.assertIn("Allow all", reason)
            self.assertIn("不能补回", reason)
            self.assertIn("控制台", reason)
            self.assertIn("platform_adapter=false", reason)

    @unittest.skipUnless(__import__("os").name == "nt", "Windows Resolve log path")
    def test_wake_stops_promptly_on_a_new_bridge_runtime_error(self):
        import os
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as folder:
            appdata = Path(folder) / "AppData"
            log = appdata / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "logs" / "ResolveDebug.txt"
            log.parent.mkdir(parents=True)
            log.write_text("previous run had a sandbox warning\n", encoding="utf-8")
            root = Path(folder) / "Documents" / "FlowStudioResolveBridge"
            with patch.dict(os.environ, {"APPDATA": str(appdata)}), \
                    patch.object(daily, "bridge_root", return_value=root), \
                    patch.object(daily, "ensure_bridge_dirs"), \
                    patch.object(daily, "install_bridge", return_value=False), \
                    patch.object(daily, "snapshot", return_value={"alive": False, "version": daily.VERSION, "stage": "OFFLINE"}), \
                    patch("app.services.davinci_workflow.launch_resolve"), \
                    patch.object(daily, "clear_mac_wake_traces"), \
                    patch.object(daily, "grant_foreground"), \
                    patch.object(daily, "menu_attempt_due", side_effect=[True, False]), \
                    patch.object(daily.time, "sleep"), \
                    patch.object(daily.DailyWake, "progress"):
                wake = daily.DailyWake("25", root=root)

                def invoke_menu():
                    with log.open("a", encoding="utf-8") as stream:
                        stream.write("FlowStudio_Resolve_Bridge.lua: BRIDGE_RUNTIME_UNAVAILABLE io-missing\n")
                    return True, "脚本已发送"

                with patch.object(wake, "_invoke_bridge_menu", side_effect=invoke_menu):
                    with self.assertRaisesRegex(RuntimeError, "不能补回"):
                        wake._run()

    def test_short_gap_stays_connected_and_long_gap_can_mark_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / "bridge_state.ini"

            def write(age, stage):
                state.write_text(f"version=0.5.0\nstage={stage}\nupdated_at={time.time() - age}\n", encoding="utf-8")

            with patch.object(daily, "bridge_root", return_value=root):
                write(10, "IMPORTING")
                self.assertTrue(daily.snapshot()["alive"])
                write(40, "IMPORTING")
                current = daily.snapshot()
                self.assertFalse(current["alive"])
                self.assertLess(daily.heartbeat_age(current), daily.IMPORT_DISCONNECT_SECONDS)
                write(50, "IMPORTING")
                current = daily.snapshot()
                self.assertGreater(daily.heartbeat_age(current), daily.IMPORT_DISCONNECT_SECONDS)
                write(1, "OFFLINE")
                self.assertFalse(daily.snapshot()["alive"])

    @unittest.skipUnless(__import__("sys").platform in ("win32", "darwin"), "Resolve automation platform")
    def test_bridge_connect_only_does_not_enqueue_daily_project_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "FlowStudioResolveBridge"
            online = {"alive": True, "version": daily.VERSION, "stage": "IDLE", "root": str(root)}
            with patch.object(daily, "ensure_bridge_dirs"), \
                    patch.object(daily, "install_bridge", return_value=False) as install, \
                    patch.object(daily, "snapshot", return_value=online), \
                    patch("app.services.davinci_workflow.launch_resolve") as launch, \
                    patch.object(daily.DailyWake, "progress"):
                wake = daily.DailyWake("25", root=root, day="2026-10-15")
                result = wake.connect()
            self.assertTrue(result["alive"])
            self.assertIn("尚未创建当天项目", wake.detail)
            self.assertEqual(list((root / "v0_5_0" / "commands").glob("*.job")), [])
            launch.assert_not_called()
            install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
