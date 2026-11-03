from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from app.services.flow_error_guide import diagnose_flow_error, translate_common_exception_cn
from app.ui.task_error_view import error_view, needs_prompt, upload_skipped


class FlowErrorGuideTests(unittest.TestCase):
    def test_all_known_flow_error_codes_translate_to_pure_chinese(self):
        codes = [
            "PUBLIC_ERROR_UNUSUAL_ACTIVITY",
            "PUBLIC_ERROR_UNUSUAL_ACTIVITY_TOO_MUCH_TRAFFIC",
            "PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED",
            "PUBLIC_ERROR_VIDEO_GENERATION_TIMED_OUT",
            "PUBLIC_ERROR_UNSAFE",
            "SAFETY_FILTER",
            "CONTENT_POLICY",
            "PROMPT_REJECTED",
            "QUOTA_EXCEEDED",
            "RESOURCE_EXHAUSTED (429)",
            "SERVER_UNAUTHORIZED (401)",
            "PERMISSION_DENIED (403)",
            "INTERNAL (500)",
            "IMAGE_NOT_UPLOADED:host_portrait.jpg",
            "REFERENCE_STATE_NOT_DETECTED:host_portrait.jpg",
            "FIRST_FRAME_NOT_CONFIRMED:host_portrait.jpg",
            "EYE_IMAGE_MODEL_NOT_CONFIRMED:host_portrait.jpg",
            "FLOW_GENERATE_BUTTON_NOT_READY",
            "FLOW_SUBMISSION_NOT_STARTED",
            "SUBMISSION_NOT_CONFIRMED",
            "MAIN_ENGINE_TIMEOUT",
            "ENGINE_BUSY",
            "BRIDGE_TIMEOUT:FS_DOWNLOAD_RESERVE",
            "AUX_IMAGE_MISSING",
            "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/missing.png'",
            "FAILED",
            "Flow 视频生成失败",
            "图片上传失败已达3次，已跳过该任务：IMAGE_NOT_UPLOADED:avatar.jpg",
            "用户放弃任务；原错误：PUBLIC_ERROR_UNUSUAL_ACTIVITY",
            "同一视频（神父 第 03 号）已被放弃，整条视频作废；原错误：未提供",
            "ConnectionResetError: [Errno 54] Connection reset by peer",
            "sqlite3.OperationalError: database is locked",
        ]
        for raw in codes:
            info = diagnose_flow_error(
                raw,
                status="失败",
                channel_key="CH1",
                host_name="测试主播",
                seg_code="01-01",
                retry_count=1,
            )
            self.assertTrue(info.title, f"Empty title for {raw}")
            self.assertTrue(info.inline_text, f"Empty inline_text for {raw}")
            self.assertTrue(info.cause, f"Empty cause for {raw}")
            self.assertGreaterEqual(len(info.solutions), 1, f"No solutions for {raw}")
            # Ensure inline_text does not leak raw uppercase snake_case codes
            self.assertNotIn("PUBLIC_ERROR", info.inline_text)
            self.assertNotIn("IMAGE_NOT_UPLOADED", info.inline_text)
            self.assertNotIn("REFERENCE_STATE", info.inline_text)
            self.assertNotIn("FIRST_FRAME", info.inline_text)
            self.assertNotIn("BRIDGE_TIMEOUT", info.inline_text)

    def test_error_view_compatibility_and_chinese_output(self):
        task = {
            "flow_status": "失败",
            "flow_error": "PUBLIC_ERROR_UNUSUAL_ACTIVITY",
            "flow_channel_key": "CH1",
            "host_name": "汽修工续图",
            "video_seq": 28,
            "seg_seq": 1,
            "flow_retry_count": 1,
        }
        label, history, reason, detail = error_view(task, {"failures": 2})
        self.assertEqual(label, "失败")
        self.assertEqual(history, 2)
        self.assertIn("风控", reason)
        self.assertNotIn("PUBLIC_ERROR_UNUSUAL_ACTIVITY", reason)
        self.assertIn("PUBLIC_ERROR_UNUSUAL_ACTIVITY", detail)

        # Prominent people filter should be recognized as needing prompt/image review
        task_people = {
            "flow_status": "失败",
            "flow_error": "PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED",
        }
        self.assertTrue(needs_prompt(task_people))

        # Upload skipped detection
        task_skip = {
            "flow_status": "失败",
            "flow_error": "图片上传失败已达3次，已跳过该任务：IMAGE_NOT_UPLOADED:a.jpg",
        }
        self.assertTrue(upload_skipped(task_skip))

    def test_translate_common_exception_cn(self):
        msg = translate_common_exception_cn("HTTPSConnectionPool(host='api.openai.com', port=443): Read timed out.")
        self.assertIn("超时", msg)


if __name__ == "__main__":
    unittest.main()
