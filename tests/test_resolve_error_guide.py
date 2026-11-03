from __future__ import annotations

import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from app.services import resolve_error_guide as guide
from app.ui.resolve_error_dialog import EditingErrorDetailDialog, InlineErrorStatusBox
from PySide6.QtWidgets import QLabel


_RAW_CODE_RE = re.compile(r'\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b')


class ResolveErrorGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_export_range_foreign_clip_translates_to_chinese_with_video_info(self):
        with patch.object(guide, 'lookup_video_names', return_value=('「Anna / Maria · 视频 #03」', 'Anna / Maria · 视频 #03（内部编号 19）')):
            disp, info = guide.format_inline_editing_text(
                'EXPORT_RANGE_FOREIGN_CLIP: video=19',
                batch_status='EXPORT_ERROR',
            )
        self.assertIsNotNone(info)
        self.assertEqual(info.code, 'EXPORT_RANGE_FOREIGN_CLIP')
        self.assertIn('Anna / Maria · 视频 #03', disp)
        self.assertNotIn('EXPORT_RANGE_FOREIGN_CLIP', disp)
        self.assertNotIn('video=19', disp)
        self.assertGreaterEqual(len(info.solutions), 3)
        self.assertEqual(info.location_items[0][0], '涉及视频')
        self.assertIn('内部编号 19', info.location_items[0][1])

    def test_cut_not_confirmed_converts_frame_to_timecode(self):
        with patch.object(guide, '_current_fps', return_value=25):
            disp, info = guide.format_inline_editing_text(
                "...s/Utility/FlowStudioAuto/Autoediting_V1.7_FlowStudio.lua:2223: CUT_NOT_CONFIRMED: frame=100447 切刀未确认（素材个数未增加）；保留现场，不会重复发送快捷键",
                batch_status='CUTTING_ERROR',
            )
        self.assertIsNotNone(info)
        self.assertEqual(info.code, 'CUT_NOT_CONFIRMED')
        self.assertIn('01:06:57:22', disp)
        self.assertNotIn('CUT_NOT_CONFIRMED', disp)
        self.assertNotIn('.lua', disp)
        self.assertTrue(any('Cmd+B' in s for s in info.solutions))

    def test_reexport_compound_message_preserves_summary_and_translates_tail(self):
        with patch.object(guide, 'lookup_video_names', return_value=('「宿主A · 视频 #05」', '宿主A · 视频 #05（内部编号 19）')):
            disp, info = guide.format_inline_editing_text(
                '重新导出完成：成功 0 个，失败 1 个 · ...FlowStudio_Finish_Batch.lua:1041: EXPORT_RANGE_FOREIGN_CLIP: video=19'
            )
        self.assertIsNotNone(info)
        self.assertIn('重新导出完成：成功 0 个，失败 1 个', disp)
        self.assertNotIn('EXPORT_RANGE_FOREIGN_CLIP', disp)
        self.assertNotIn('video=19', disp)

    def test_all_historical_bridge_errors_produce_chinese_without_raw_codes(self):
        samples = [
            "...lity/FlowStudioAuto/FlowStudio_Resolve_Bridge_v0.5.0.lua:114: SET_TIMELINE_FAILED",
            "...lity/FlowStudioAuto/FlowStudio_Resolve_Bridge_v0.5.0.lua:248: INVALID_REQUEST_ID",
            "...lity/FlowStudioAuto/FlowStudio_Resolve_Bridge_v0.5.0.lua:25: RESOLVE_NOT_READY: 无法取得 Resolve 项目管理器，请等待达芬奇初始化后重新唤醒",
            "...FlowStudio_Finish_Batch.lua:1050: BATCH_RENDER_INCOMPLETE: 13 个未确认；视频 1394 Cancelled；成功成品已保存，可重试未完成导出",
            "...FlowStudio_Finish_Batch.lua:616: OUTPUT_ALREADY_EXISTS: 未确认文件不会覆盖",
            "...FlowStudio_Finish_Batch.lua:420: VIDEO_MARKER_MISSING: video=293；COMPLETE Marker数量=0；完整视频范围=01:38:13:10 - 01:38:33:10",
            "...FlowStudio_Finish_Batch.lua:647: attempt to call method 'GetRenderJobStatus' (a nil value)",
            "...FlowStudio_Finish_Batch.lua:81: FINISH_CANCELLED: 已取消，未清理、未启动导出",
            "...FlowStudio_Import_Batch.lua:102: PIPELINE_LOCKED: 当前批次尚未结束",
            "...FlowStudio_Import_Batch.lua:140: IMPORT_UNCERTAIN: 当前批次上次导入未完成，请先确认现场，避免重复追加",
            "...FlowStudio_Import_Batch.lua:146: TRANSFORM_TIMELINE_SIZE_MISMATCH: 40994",
            "...FlowStudio_Import_Batch.lua:40: INVALID_INTEGER: actual start (Resolve returned nil)",
            "...Autoediting_V1.7_FlowStudio.lua:1267: TASK_ID_MISMATCH",
            "...Autoediting_V1.7_FlowStudio.lua:1269: PAYLOAD_PATH_MISMATCH",
            "...Autoediting_V1.7_FlowStudio.lua:1391: TIMELINE_UNAVAILABLE",
            "...Autoediting_V1.7_FlowStudio.lua:1602: WAV_OUTPUT_ALREADY_EXISTS: /tmp/timeline.wav；请从 Studio 创建新的分析任务",
            "...Autoediting_V1.7_FlowStudio.lua:1830: ALIGNMENT_SIZE_LIMIT",
            "...Autoediting_V1.7_FlowStudio.lua:2662: SUBCLIP_APPEND_GROUP_FAILED: 9",
            "...Autoediting_V1.7_FlowStudio.lua:2461: RESUME_BATCH_SCOPE_CHANGED",
            "...Autoediting_V1.7_FlowStudio.lua:1676: CLOSE_BEFORE_SUBCLIP_SYNC_FAILED",
            "...Autoediting_V1.7_FlowStudio.lua:1620: FPS_MISMATCH",
            "...Autoediting_V1.7_FlowStudio.lua:1748: SUBCLIP_DB_SYNC_FAILED: SUBCLIPS_NOOP",
            "...Autoediting_V1.7_FlowStudio.lua:2575: attempt to concatenate local 'clipIndex' (a function value)",
            "BRAND_NEW_UNSEEN_RESOLVE_CODE: detail=something unexpected",
        ]
        err_dir = Path.home() / 'Documents/FlowStudioResolveBridge/v0_5_0/error'
        if err_dir.is_dir():
            for p in sorted(err_dir.glob('*.txt'))[:60]:
                txt = p.read_text(encoding='utf-8', errors='ignore').strip()
                if txt:
                    samples.append(txt.splitlines()[-1].strip())

        for raw in samples:
            disp, info = guide.format_inline_editing_text(raw, batch_status='ERROR')
            self.assertIsNotNone(info, f'Expected error info for: {raw}')
            self.assertIsNone(_RAW_CODE_RE.search(disp), f'Leaked uppercase code in inline_text={disp!r} for raw={raw!r}')
            self.assertIsNone(_RAW_CODE_RE.search(info.title), f'Leaked uppercase code in title={info.title!r} for raw={raw!r}')
            self.assertNotIn('attempt to ', disp.lower())
            self.assertGreaterEqual(len(info.solutions), 1)

    def test_benign_live_progress_and_ready_states_are_not_errors(self):
        benign_cases = [
            ('✓ 素材已导入，可以开始自动剪辑', 'IMPORTED', 'READY'),
            ('等待可剪辑素材', '', ''),
            ('达芬奇已就绪（MAIN-2026-11-03）', '', 'READY'),
            ('仅清理 V1 主轨的红色自动范围 + 蓝色人工指定片段；V2 及以上完全忽略并保护；中断后不会重复删除', 'CLEANING', 'CLEANING'),
            ('开始后台极速子片段切分（共 18 处切点，无需占用鼠标键盘焦点；已跳过 1 个识别失败视频）', 'CUTTING', 'CUTTING'),
            ('自动剪辑完成；识别失败已跳过 0 个，橙色 Marker 请手动剪辑', 'WAITING_USER_REVIEW', 'WAITING_USER_REVIEW'),
            ('重新导出完成：成功 4 个', '', ''),
        ]
        for text, b_stat, stg in benign_cases:
            disp, info = guide.format_inline_editing_text(text, batch_status=b_stat, stage=stg)
            self.assertIsNone(info, f'Benign text misclassified as error: {text!r}')
            self.assertNotIn('Marker', disp)

    def test_inline_status_box_toggles_detail_button_and_opens_dialog(self):
        lbl = QLabel('等待可剪辑素材')
        box = InlineErrorStatusBox(lbl)
        box.resize(700, 28)
        box.set_raw_status('等待可剪辑素材')
        self.assertTrue(box.detail_btn.isHidden())
        self.assertEqual(lbl.property('isError'), 'false')

        box.set_raw_status('EXPORT_RANGE_FOREIGN_CLIP: video=19', batch_status='EXPORT_ERROR')
        self.assertFalse(box.detail_btn.isHidden())
        self.assertEqual(lbl.property('isError'), 'true')
        self.assertNotIn('EXPORT_RANGE_FOREIGN_CLIP', lbl.text())

        dlg = EditingErrorDetailDialog(box.error_info)
        dlg.resize(630, 500)
        self.assertEqual(dlg.windowTitle(), '剪辑异常详情与解决建议')
        dlg.close()


if __name__ == '__main__':
    unittest.main()
