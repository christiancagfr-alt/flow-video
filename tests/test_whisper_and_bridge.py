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


if __name__ == "__main__":
    unittest.main()
