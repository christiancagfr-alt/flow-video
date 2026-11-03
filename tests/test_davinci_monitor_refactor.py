"""Tests for the refactored DaVinci Auto-Editing Center progress monitor (cards + inline drawer + table toggle)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication

from app.core import database, repository as repo, work_dates
from app.ui import styles, davinci_monitor_cards
from app.ui.downstream_pages import DaVinciPage


class TestDaVinciMonitorRefactor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.db_path = self.tmp_path / "test_dv_refactor.sqlite3"
        self._db_patcher = patch.object(database, "DB_PATH", self.db_path)
        self._db_patcher.start()
        database.init_db()
        self.day = "2026-11-02"
        self._date_patcher = patch.object(work_dates, "active", return_value=self.day)
        self._date_patcher.start()

        # Create dummy reference portrait images & exported mp4 files
        self.img_a = self.tmp_path / "host_a.png"
        img1 = QImage(360, 640, QImage.Format_ARGB32)
        img1.fill(QColor("#3B82F6"))
        img1.save(str(self.img_a), "PNG")

        self.img_b = self.tmp_path / "host_b.png"
        img2 = QImage(640, 360, QImage.Format_ARGB32)
        img2.fill(QColor("#8B5CF6"))
        img2.save(str(self.img_b), "PNG")

        self.export_dir = self.tmp_path / "Exports" / self.day
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.mp4_1 = self.export_dir / "Alice_HostA_01.mp4"
        self.mp4_1.write_bytes(b"mp4data")
        self.mp4_done_1 = self.export_dir / "DoneRec_HostD_01.mp4"
        self.mp4_done_1.write_bytes(b"mp4data")
        self.mp4_done_2 = self.export_dir / "DoneRec_HostD_02.mp4"
        self.mp4_done_2.write_bytes(b"mp4data")

    def tearDown(self):
        self._date_patcher.stop()
        self._db_patcher.stop()
        self.tmp.cleanup()

    def _seed_queue_data(self):
        with database.connect() as con:
            con.execute("INSERT INTO recipients(id, name, work_date) VALUES (1, 'Anna工作室', ?)", (self.day,))
            con.execute("INSERT INTO recipients(id, name, work_date) VALUES (2, 'Ben团队', ?)", (self.day,))
            con.execute("INSERT INTO hosts(id, recipient_id, name) VALUES (11, 1, 'Grace牧师')")
            con.execute("INSERT INTO hosts(id, recipient_id, name) VALUES (12, 1, 'Daniel讲员')")
            con.execute("INSERT INTO hosts(id, recipient_id, name) VALUES (13, 1, 'Esther见证')")
            con.execute("INSERT INTO hosts(id, recipient_id, name) VALUES (21, 2, 'Paul专栏')")

            # Host 11 (Grace): 1 exported, 2 waiting user review on timeline, 1 ready
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (101, 11, 1, ?, '已导出', ?)",
                (str(self.img_a), str(self.mp4_1)),
            )
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (102, 11, 2, ?, '待人工检查', '')",
                (str(self.img_a),),
            )
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (103, 11, 3, ?, '待人工检查', '')",
                (str(self.img_a),),
            )
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (104, 11, 4, ?, '待剪辑', '')",
                (str(self.img_a),),
            )

            # Host 12 (Daniel 16:9): 2 ready to edit
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (105, 12, 1, ?, '待剪辑', '')",
                (str(self.img_b),),
            )
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (106, 12, 2, ?, '待剪辑', '')",
                (str(self.img_b),),
            )

            # Host 13 (Esther): 2 waiting material (with segments in pipeline)
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (107, 13, 1, ?, '等待片段', '')",
                (str(self.img_a),),
            )
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (108, 13, 2, ?, '等待片段', '')",
                (str(self.img_a),),
            )

            # Recipient 2 / Host 21 (Paul): 100% exported (2/2) -> should auto-collapse & sort to bottom
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (201, 21, 1, ?, '已导出', ?)",
                (str(self.img_b), str(self.mp4_done_1)),
            )
            con.execute(
                "INSERT INTO videos(id, host_id, seq, image_path, edit_status, edit_output_path) VALUES (202, 21, 2, ?, '已导出', ?)",
                (str(self.img_b), str(self.mp4_done_2)),
            )

            # Add flow_segments + flow_outputs so segment_count / qc_passed / entered_pipeline are realistic
            seg_id = 100
            for vid in (101, 102, 103, 104, 105, 106, 201, 202):
                seg_p = self.tmp_path / f"seg_{vid}.mp4"
                seg_p.write_bytes(b"seg")
                for s in (1, 2, 3):
                    seg_id += 1
                    con.execute(
                        """INSERT INTO flow_segments(id, video_id, seg_seq, prompt_review_status, generation_command, flow_status, flow_output_path, qc_status)
                           VALUES (?, ?, ?, '已提交', 'cmd1', '已完成', ?, '通过')""",
                        (seg_id, vid, s, str(seg_p)),
                    )
                    con.execute(
                        """INSERT INTO flow_outputs(segment_id, command_id, media_id, output_path, qc_status)
                           VALUES (?, 'cmd1', ?, ?, '通过')""",
                        (seg_id, f"m_{seg_id}", str(seg_p)),
                    )
            for vid in (107, 108):
                seg_p = self.tmp_path / f"seg_{vid}_ok.mp4"
                seg_p.write_bytes(b"seg")
                for s in (1, 2, 3):
                    seg_id += 1
                    if s == 1:
                        con.execute(
                            """INSERT INTO flow_segments(id, video_id, seg_seq, prompt_review_status, generation_command, flow_status, flow_output_path, qc_status)
                               VALUES (?, ?, ?, '已提交', 'cmd1', '已完成', ?, '通过')""",
                            (seg_id, vid, s, str(seg_p)),
                        )
                        con.execute(
                            """INSERT INTO flow_outputs(segment_id, command_id, media_id, output_path, qc_status)
                               VALUES (?, 'cmd1', ?, ?, '通过')""",
                            (seg_id, f"m_{seg_id}", str(seg_p)),
                        )
                    else:
                        con.execute(
                            """INSERT INTO flow_segments(id, video_id, seg_seq, prompt_review_status, generation_command, flow_status, flow_output_path, qc_status)
                               VALUES (?, ?, ?, '已提交', 'cmd1', '生成中', '', '待质检')""",
                            (seg_id, vid, s),
                        )
        repo.set_host_aspect_ratio(12, "16:9")

    def test_aspect_ratio_and_cards_pooling_and_interactions(self):
        self._seed_queue_data()
        rows = repo.list_edit_queue(work_date=self.day)
        self.assertEqual(len(rows), 10)
        ratios = {int(r["host_id"]): r["aspect_ratio"] for r in rows}
        self.assertEqual(ratios[12], "16:9")
        self.assertEqual(ratios[11], "9:16")

        self.app.setStyleSheet(styles.DARK)
        with patch.object(DaVinciPage, "refresh_resolve_bridge", lambda _s: None):
            page = DaVinciPage()
        page.resolve_poll_timer.stop()
        page.queue_poll_timer.stop()
        page.resize(1420, 920)
        page.show()
        self.app.processEvents()

        # Simulate watermark cache on Host 11 & 12
        page._host_wm_cache = {
            11: {"bound_name": "牧师频道A"},
            12: {"bound_name": "Daniel横屏"},
        }
        page._dv_cards_sig = None
        page._dv_table_sig = None
        page._render_dv_video_table()
        self.app.processEvents()

        # Default view is cards (index 0)
        self.assertEqual(page.dv_queue_stack.currentIndex(), 0)
        self.assertEqual(page.dv_list_title.text(), "📋 今日剪辑进度")

        # Recipient 1 (active/review) should sort before Recipient 2 (100% done & auto-collapsed)
        rec_widgets = [page.dv_cards_layout.itemAt(i).widget() for i in range(page.dv_cards_layout.count())]
        self.assertEqual(len(rec_widgets), 2)
        rec1 = page._dv_monitor_recipients[1]
        rec2 = page._dv_monitor_recipients[2]
        self.assertIs(rec_widgets[0], rec1["card"])
        self.assertIs(rec_widgets[1], rec2["card"])
        self.assertFalse(rec1["collapsed"])
        self.assertTrue(rec2["collapsed"])

        # Host 12 shows 16:9 badge and watermark pill; Host 11 shows open folder button
        h11 = rec1["hosts"][11]
        h12 = rec1["hosts"][12]
        self.assertTrue(h11["open_btn"].isVisible())
        self.assertTrue(h11["wm_pill"].isVisible())
        self.assertFalse(h11["ratio_pill"].isVisible())
        self.assertTrue(h12["ratio_pill"].isVisible())
        self.assertTrue(h12["wm_pill"].isVisible())
        self.assertFalse(h12["open_btn"].isVisible())

        # Widget pooling check: repeated refresh must reuse exact QFrame instances
        card_ref_before = h11["card"]
        page._dv_cards_sig = None
        davinci_monitor_cards.refresh_edit_monitor(page)
        self.assertIs(rec1["hosts"][11]["card"], card_ref_before)

        # Inline #01~#N drawer expand & variable card height
        self.assertFalse(h11["drawer"].isVisible())
        base_h = h11["card"].height()
        davinci_monitor_cards.toggle_host_expand(page, (1, 11))
        self.app.processEvents()
        self.assertTrue(h11["drawer"].isVisible())
        self.assertGreater(h11["card"].height(), base_h + 80)
        self.assertEqual(len(h11["video_rows"]), 4)
        self.assertFalse(h11["video_rows"][101]["open_btn"].isHidden())
        self.assertTrue(h11["video_rows"][102]["open_btn"].isHidden())
        # Neighboring collapsed card in the same row keeps compact height!
        self.assertEqual(h12["card"].height(), base_h)

        # Search auto-expand on sequence "#02" for unexpanded Host 12
        davinci_monitor_cards.toggle_host_expand(page, (1, 11))
        self.assertFalse(h12["drawer"].isVisible())
        page.dv_search_input.setText("#02")
        self.app.processEvents()
        self.assertTrue(h12["drawer"].isVisible())
        self.assertEqual(page.dv_list_title.text(), "📋 今日剪辑进度 (4)")
        page.dv_search_input.setText("")
        self.app.processEvents()
        self.assertFalse(h12["drawer"].isVisible())

        # Context menu builders
        menu_h, acts_h = davinci_monitor_cards.build_host_context_menu(page, (1, 11), h11["rows_snapshot"])
        self.assertIn("open_dir", acts_h)
        self.assertIn("abandon_all", acts_h)

        h13 = rec1["hosts"][13]
        menu_v, acts_v = davinci_monitor_cards.build_video_context_menu(page, h13["rows_snapshot"][0], h13["rows_snapshot"])
        self.assertIn("abandon_one", acts_v)
        self.assertIn("abandon_host_wait", acts_v)

        # Switch to table view and back
        page.set_dv_view_mode("table")
        self.app.processEvents()
        self.assertEqual(page.dv_queue_stack.currentIndex(), 1)
        self.assertEqual(page.dv_video_table.rowCount(), 10)
        page.set_dv_view_mode("cards")
        self.app.processEvents()
        self.assertEqual(page.dv_queue_stack.currentIndex(), 0)

        # Double-click on Host 11 opens exported folder
        with patch.object(page, "open_exported_path") as mock_open:
            davinci_monitor_cards._on_host_double_clicked(page, (1, 11), h11["rows_snapshot"])
            mock_open.assert_called_once_with(str(self.mp4_1))

        page.close()


if __name__ == "__main__":
    unittest.main()
