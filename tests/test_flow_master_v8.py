import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import flow_master_v8 as v8


def _selection(**overrides):
    raw = {
        "posture": "standing",
        "hand_state": "both_occupied",
        "object_interaction": True,
        "praying_pose": False,
        "mic_visible": True,
        "device_visible": False,
        "voice_age_band": "adult",
        "confidence": 0.9,
        "selected_action_ids": ["v8_free_hand", "v8_walk"],
    }
    raw.update(overrides)
    return raw


def _parsed(rows, **selection):
    return {"motion_selection": _selection(**selection), "results": rows}


class FlowMasterV8Tests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        missing = Path(self._dir.name) / "missing.md"
        self._patch = patch.object(v8, "instruction_path", return_value=missing)
        self._patch.start()
        v8._FILE_CACHE.update(path="", mtime=None, sections=None)

    def tearDown(self):
        self._patch.stop()
        v8._FILE_CACHE.update(path="", mtime=None, sections=None)
        self._dir.cleanup()

    def test_configure_drops_persona_and_uses_v8_catalogs(self):
        group = {"host_id": 0, "host_rule": "人物设置里的旧动作和镜头", "template_snapshot": "基础模板"}
        text = v8.configure_group(group)
        self.assertEqual(group["instruction_source"], v8.SOURCE)
        self.assertEqual(group["host_rule"], "")
        self.assertEqual(group["template_snapshot"], "")
        self.assertEqual([item["id"] for item in group["action_presets"]], ["v8_keep", "v8_free_hand", "v8_walk"])
        self.assertIn("不使用人物设置", text)
        self.assertNotIn("人物设置里的旧动作", text)

    def test_occupied_hands_do_not_match_a_free_gesture(self):
        built = v8.complete_batch(
            _parsed([
                {"id": "1", "prompt": "语气恳切，他挥手指向前方。\n文案： hello", "camera_id": "v8_push"},
                {"id": "2", "prompt": "继续恳切。文案： amen", "camera_id": "v8_arc"},
            ]),
            {"host_id": 0, "locked_voice": "声音始终是同一个人：成年音色，同一口音，不换声。"},
            [
                {"segment_id": 1, "foreign_text": "hello", "performance_mode": "TALKING"},
                {"segment_id": 2, "foreign_text": "amen", "performance_mode": "PRAYING"},
            ],
        )
        first = built["prompts"]["1"]
        second = built["prompts"]["2"]
        self.assertEqual(built["motion_selection"]["selected_action_ids"], ["v8_keep"])
        self.assertNotIn("挥手", first)
        self.assertNotIn("手机", first)
        self.assertNotIn("人物固定硬约束", first)
        self.assertNotIn("基础模板", first)
        self.assertNotIn("五官肤色", first)
        self.assertIn("拿麦的手一直握着麦", first)
        self.assertIn("拿麦的手一直握着麦", second)
        self.assertIn("文案： hello", first)
        self.assertIn("文案： amen", second)
        self.assertIn("眼睛自然睁开", first)
        self.assertIn("眼睛闭合", second)
        self.assertIn("大约偏离正脸四十度", second)
        self.assertIn("镜头先停稳", first)
        self.assertIn("已经停稳的同一人物状态", second)
        self.assertEqual(first.count("声音始终是同一个人"), 1)
        self.assertIn(built["motion_selection"]["preset_rule"][:8], first)

    def test_same_camera_reuses_direction_and_strips_phone(self):
        built = v8.complete_batch(
            _parsed(
                [
                    {"id": "1", "prompt": "举起手机，然后微笑", "camera_id": "not-a-camera"},
                    {"id": "2", "prompt": "仍然微笑", "camera_id": "v8_hold"},
                ],
                hand_state="free",
                object_interaction=False,
                mic_visible=False,
                selected_action_ids=["v8_keep"],
                posture="seated",
            ),
            {"host_id": 0, "locked_voice": v8.voice_sentence("adult")},
            [
                {"segment_id": 1, "foreign_text": "one", "performance_mode": "TALKING"},
                {"segment_id": 2, "foreign_text": "two", "performance_mode": "TALKING"},
            ],
        )
        self.assertNotIn("手机", built["prompts"]["1"])
        self.assertIn("微笑", built["prompts"]["1"])
        self.assertIn("不离开座位", built["prompts"]["1"])
        self.assertIn("镜头沿同一方向继续", built["prompts"]["2"])
        self.assertNotIn("回到参考图的初始位置", built["prompts"]["1"])

    def test_locked_voice_is_not_rewritten(self):
        locked = v8.voice_sentence("toddler")
        with patch("app.services.flow_master_v8.repo.set_setting") as save:
            built = v8.complete_batch(
                _parsed(
                    [{"id": "1", "prompt": "开心。文案： hi", "camera_id": "v8_hold"}],
                    voice_age_band="senior",
                    hand_state="free",
                    object_interaction=False,
                    mic_visible=False,
                    selected_action_ids=["v8_keep"],
                ),
                {"host_id": 9, "locked_voice": locked},
                [{"segment_id": 1, "foreign_text": "hi", "performance_mode": "TALKING"}],
            )
        save.assert_not_called()
        self.assertIn(locked, built["prompts"]["1"])
        self.assertNotIn("年长", built["prompts"]["1"])

    def test_dynamic_request_does_not_include_persona_rules(self):
        text = v8.dynamic_text(
            {"image_rule": "", "locked_voice": ""},
            [{"segment_id": 3, "foreign_text": "line", "performance_mode": "TALKING"}],
        )
        self.assertIn("v8_keep", text)
        self.assertIn("v8_hold", text)
        self.assertNotIn("人物动作选择模式", text)
        self.assertNotIn("基础模板", text)

    def test_instruction_file_replaces_one_sentence_and_keeps_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "flow_master_v8.md"
            path.write_text(
                "## 手-mic\n测试握麦不换手\n"
                "## 动作-v8_keep 保持原接触\n测试动作句子。\n"
                "## 动作-other 不要用\n这条不能进目录\n"
                "## 给GPT的说明\n\n",
                encoding="utf-8",
            )
            with patch.object(v8, "instruction_path", return_value=path):
                v8._FILE_CACHE.update(path="", mtime=None, sections=None)
                self.assertIn("不使用人物设置", v8.developer_instructions())
                built = v8.complete_batch(
                    _parsed([
                        {"id": "1", "prompt": "语气恳切。文案： hello", "camera_id": "v8_hold"},
                    ]),
                    {"host_id": 0, "locked_voice": "声音始终是同一个人：成年音色，同一口音，不换声。"},
                    [{"segment_id": 1, "foreign_text": "hello", "performance_mode": "TALKING"}],
                )
                prompt = built["prompts"]["1"]
                self.assertIn("测试握麦不换手", prompt)
                self.assertIn("测试动作句子", prompt)
                self.assertNotIn("这条不能进目录", prompt)
                self.assertEqual([item["id"] for item in v8.action_catalog()], ["v8_keep", "v8_free_hand", "v8_walk"])
                self.assertIn("拿麦的手一直握着麦", v8.section("手-missing", v8._HANDS["mic"]))

    def test_edited_file_is_not_replaced_and_bad_seam_stays_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "flow_master_v8.md"
            with patch.object(v8, "instruction_path", return_value=path):
                v8._FILE_CACHE.update(path="", mtime=None, sections=None)
                made = v8.ensure_instruction_file()
                self.assertEqual(made, path)
                self.assertIn("## 手-mic", path.read_text(encoding="utf-8"))
                path.write_text("## 接缝-开场\n开头{missing}\n## 手-mic\n用户改过的句子\n", encoding="utf-8")
                v8._FILE_CACHE.update(path="", mtime=None, sections=None)
                v8.ensure_instruction_file()
                self.assertIn("用户改过的句子", path.read_text(encoding="utf-8"))
                self.assertEqual(v8.section("手-mic", "默认"), "用户改过的句子")
                text = v8.seam_block(0, 1, "身体", "眼睛", "v8_hold", ["v8_hold"])
                self.assertIn("开头{missing}", text)


if __name__ == "__main__":
    unittest.main()
