"""Unit tests for manual external video import (single segment, whole video, whole host)."""
from __future__ import annotations
from scripts.test_runtime import DatabaseTemporaryDirectory

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import database, repository as repo, work_dates
from app.services import flow_redownload, manual_video_import as mvi


class TestManualVideoImport(unittest.TestCase):
    def setUp(self):
        self._tmp = DatabaseTemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self._db_patch = patch.object(database, "DB_PATH", self.tmp_dir / "test_import.db")
        self._db_patch.start()
        database.init_db()
        work_dates.select("2099-05-01")

        self.recipient_id = repo.find_or_create_recipient("测试接收人", "ZB", "t", "20990501")
        self.host_id = repo.find_or_create_host(self.recipient_id, "测试主播A")

        # Video 1: 3 segments (2 completed, 1 failed)
        self.video1_id = repo.add_video_to_host(self.host_id, original_script="Line 1\nLine 2\nLine 3")
        repo.sync_flow_segments(self.video1_id, ["Line 1", "Line 2", "Line 3"])
        v1_rows = mvi.list_video_segments(self.video1_id, work_date="2099-05-01")
        self.v1_sids = [int(r["segment_id"]) for r in v1_rows]

        # Video 2: 2 segments (both pending)
        self.video2_id = repo.add_video_to_host(self.host_id, original_script="V2 Line 1\nV2 Line 2")
        repo.sync_flow_segments(self.video2_id, ["V2 Line 1", "V2 Line 2"])
        v2_rows = mvi.list_video_segments(self.video2_id, work_date="2099-05-01")
        self.v2_sids = [int(r["segment_id"]) for r in v2_rows]

        with database.connect() as con:
            for sid, st in zip(self.v1_sids, ("已完成", "已完成", "失败")):
                con.execute(
                    "UPDATE flow_segments SET prompt='P', prompt_review_status='已提交', flow_status=?, qc_status='待质检' WHERE id=?",
                    (st, sid),
                )
            for sid in self.v2_sids:
                con.execute(
                    "UPDATE flow_segments SET prompt='P2', prompt_review_status='已提交', flow_status='待生成', qc_status='待质检' WHERE id=?",
                    (sid,),
                )
        repo.set_setting("flow_channel_download_root", str(self.tmp_dir / "channels_out"))

    def tearDown(self):
        self._db_patch.stop()
        self._tmp.cleanup()

    def _make_fake_mp4(self, name: str, content: bytes = b"FAKE_MP4_DATA_123456") -> str:
        p = self.tmp_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return str(p)

    def test_single_segment_manual_import_and_snapshot_visibility(self):
        # Before import, snapshot_for_date should already include v1_sids[2] (failed) as uncompleted
        snap_before = flow_redownload.snapshot_for_date("2099-05-01")
        hosts = snap_before["recipients"][0]["hosts"]
        self.assertEqual(len(hosts), 1)
        v1_segs = hosts[0]["videos"][0]["segments"]
        self.assertEqual(len(v1_segs), 3)
        self.assertEqual(v1_segs[2]["file_state"], "uncompleted")

        # Import external clip into the failed 3rd segment of video 1
        ext_mp4 = self._make_fake_mp4("single_fix.mp4", b"NEW_CLIP_CONTENT_999")
        res = mvi.execute_manual_imports([(self.v1_sids[2], ext_mp4)], auto_pass_qc=True)
        self.assertEqual(res["imported"], 1)
        self.assertEqual(res["errors"], [])

        snap_after = flow_redownload.snapshot_for_date("2099-05-01")
        v1_segs_after = snap_after["recipients"][0]["hosts"][0]["videos"][0]["segments"]
        self.assertEqual(v1_segs_after[2]["file_state"], "ok")
        self.assertEqual(v1_segs_after[2]["qc_status"], "通过")
        self.assertTrue(Path(v1_segs_after[2]["output_path"]).is_file())

    def test_whole_video_sequential_import_transitions_video_to_ready_for_edit(self):
        f1 = self._make_fake_mp4("batch_v2/1.mp4", b"CLIP_V2_1")
        f2 = self._make_fake_mp4("batch_v2/2.mp4", b"CLIP_V2_2")
        plan = mvi.plan_video_files_match(self.video2_id, [f2, f1], work_date="2099-05-01")
        self.assertEqual(len(plan["pairs"]), 2)
        # Natural sort ensures 1.mp4 -> seg 1 and 2.mp4 -> seg 2
        self.assertEqual(plan["pairs"][0][0]["segment_id"], self.v2_sids[0])
        self.assertTrue(plan["pairs"][0][1].endswith("1.mp4"))
        self.assertEqual(plan["pairs"][1][0]["segment_id"], self.v2_sids[1])
        self.assertTrue(plan["pairs"][1][1].endswith("2.mp4"))

        res = mvi.execute_manual_imports(plan["pairs"], auto_pass_qc=True)
        self.assertEqual(res["imported"], 2)

        with database.connect() as con:
            v_row = con.execute(
                "SELECT status, edit_status FROM videos WHERE id=?",
                (self.video2_id,),
            ).fetchone()
            self.assertEqual(v_row["edit_status"], "待剪辑")

    def test_whole_host_import_supports_explicit_codes_and_only_incomplete(self):
        # Provide an explicit code file 02-02.mp4 and a generic 1.mp4 for only_incomplete mode
        f_explicit = self._make_fake_mp4("host_imp/02-02-custom.mp4", b"EXPLICIT_02_02")
        f_seq = self._make_fake_mp4("host_imp/1.mp4", b"SEQ_FIRST_INCOMPLETE")

        plan = mvi.plan_host_files_match(
            self.host_id,
            [f_explicit, f_seq],
            only_incomplete=True,
            work_date="2099-05-01",
        )
        by_sid = {int(s["segment_id"]): fp for s, fp in plan["pairs"]}
        # 02-02 should match v2_sids[1]
        self.assertIn(self.v2_sids[1], by_sid)
        self.assertTrue(by_sid[self.v2_sids[1]].endswith("02-02-custom.mp4"))
        # 1.mp4 should match the first incomplete segment (v1_sids[0] has no local file yet)
        self.assertIn(self.v1_sids[0], by_sid)
        self.assertTrue(by_sid[self.v1_sids[0]].endswith("1.mp4"))


if __name__ == "__main__":
    unittest.main()
