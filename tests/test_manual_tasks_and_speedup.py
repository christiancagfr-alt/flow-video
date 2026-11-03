import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.core import database as studio_db
from app.core import repository as studio_repo
from app.core import work_dates
from app.services import eye_states, manual_task_intake as mti, pre_gpt_pipeline as intake
from app.ui import workspace_intake
from app.ui.manual_task_dialog import (
    COL_ASPECT,
    COL_CHINESE,
    COL_FOREIGN,
    COL_HOST,
    COL_IMAGE,
    COL_PERF_MODE,
    COL_RECIPIENT,
    COLUMN_HEADERS,
    COLUMN_PLACEHOLDERS,
    ManualTaskDialog,
    ROLE_RED_SPANS,
)

BASE = Path(__file__).resolve().parents[1]
FUSCRIPT = Path("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fuscript")


class ManualTaskAndSpeedupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def test_dialog_starts_completely_empty_with_no_qc_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            test_studio = tmp_root / "studio.db"
            with patch.object(studio_db, "DB_PATH", test_studio):
                studio_db.init_db()
                dlg = ManualTaskDialog(work_date="2026-11-02")
                try:
                    rows = dlg.table.export_rows()
                    self.assertEqual(len(rows), 8)
                    for r in rows:
                        for key in ("recipient", "host", "perf_mode", "foreign_text", "chinese_text", "image_path", "aspect_ratio", "material_source"):
                            self.assertEqual(r[key], "", f"Expected {key} to start empty")
                        self.assertEqual(r["red_spans"], [])

                    # Verify Chinese description mentions Prompt Center only, never QC page ("质检")
                    all_ui_strings = " ".join(COLUMN_HEADERS) + " " + " ".join(COLUMN_PLACEHOLDERS.values()) + " " + dlg.stats_label.text()
                    self.assertNotIn("质检", all_ui_strings)
                    self.assertIn("提示词中心核对", COLUMN_PLACEHOLDERS[COL_CHINESE])

                    # Offscreen paint smoke check (renders gray placeholders cleanly)
                    dlg.show()
                    self.qapp.processEvents()
                    pix = dlg.grab()
                    self.assertFalse(pix.isNull())
                finally:
                    dlg.close()

    def test_google_sheets_bulk_paste_multiline_html_colors_fill_down_and_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            test_studio = tmp_root / "studio.db"
            with patch.object(studio_db, "DB_PATH", test_studio):
                studio_db.init_db()
                dlg = ManualTaskDialog(work_date="2026-11-02")
                try:
                    t = dlg.table
                    # 1. Paste 10 rows (exceeds initial 8 rows -> auto-expands) with quoted multi-line cell + HTML red/black color spans
                    tsv_rows = []
                    html_trs = []
                    for i in range(10):
                        fx = f"Habari rafiki {i}.\nOmba nami sasa."
                        tsv_rows.append(f'客户A\t主播{i}\t\t"{fx}"\t中文核对{i}')
                        html_trs.append(
                            f"<tr><td>客户A</td><td>主播{i}</td><td></td>"
                            f'<td><span style="color:#ff0000">Habari rafiki {i}.</span><br>'
                            f'<span style="color:#000000">Omba nami sasa.</span></td>'
                            f"<td>中文核对{i}</td></tr>"
                        )
                    tsv = "\n".join(tsv_rows)
                    html = "<table>" + "".join(html_trs) + "</table>"
                    t.setCurrentCell(0, COL_RECIPIENT)
                    t.paste_grid_data(tsv, html)

                    self.assertEqual(t.rowCount(), 10)
                    exported = t.export_rows()
                    self.assertEqual(exported[0]["recipient"], "客户A")
                    self.assertEqual(exported[9]["host"], "主播9")
                    self.assertEqual(exported[0]["foreign_text"], "Habari rafiki 0.\nOmba nami sasa.")
                    self.assertEqual(exported[0]["red_spans"], [(0, len("Habari rafiki 0."))])
                    self.assertEqual(exported[0]["perf_mode"], "红睁黑闭混合")

                    # 2. Undo restores 8 completely empty rows; Redo brings back all 10 pasted rows
                    t.undo()
                    self.assertEqual(t.rowCount(), 8)
                    self.assertEqual(t.export_rows()[0]["recipient"], "")
                    t.redo()
                    self.assertEqual(t.rowCount(), 10)
                    self.assertEqual(t.export_rows()[9]["host"], "主播9")

                    # 3. Fill-down (Cmd+D) copies row 0 COL_IMAGE down into rows 1..3
                    img_path = tmp_root / "landscape.png"
                    img = QImage(1280, 720, QImage.Format_RGB32)
                    img.fill(QColor("#336699"))
                    img.save(str(img_path))
                    t._ensure_item(0, COL_IMAGE).setText(str(img_path))
                    t.clearSelection()
                    for r in range(4):
                        idx = t.model().index(r, COL_IMAGE)
                        t.selectionModel().select(idx, QItemSelectionModel.Select)
                    t.fill_down_selection()
                    for r in range(4):
                        self.assertEqual(t.item(r, COL_IMAGE).text(), str(img_path))
                finally:
                    dlg.close()

    def test_import_manual_tasks_end_to_end_and_sheet_sync_coexistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            test_studio = tmp_root / "studio.db"
            test_intake = tmp_root / "pre_gpt_pipeline.sqlite3"
            asset_root = tmp_root / "TaskAssets"
            src_dir = tmp_root / "user_source_photos"
            src_dir.mkdir(parents=True)

            # Create a 16:9 image for row 1, and leave row 2 image_path empty so it shares host image!
            img_16x9 = src_dir / "host_wide.png"
            qim = QImage(1280, 720, QImage.Format_RGB32)
            qim.fill(QColor("#225588"))
            qim.save(str(img_16x9))

            with (
                patch.object(studio_db, "DB_PATH", test_studio),
                patch.object(intake, "DB_FILE", test_intake),
                patch.object(intake, "SETTINGS_FILE", tmp_root / "intake_settings.json"),
                patch.object(work_dates, "active", return_value="2026-11-02"),
            ):
                studio_db.init_db()
                studio_repo.set_setting("task_asset_root", str(asset_root))
                studio_repo.set_default_creator("测试员")

                fx_mixed = "Bwana asifiwe sana leo. Tuombe kwa imani sasa."
                red_len = len("Bwana asifiwe sana leo.")
                res = mti.import_manual_tasks(
                    [
                        {
                            "recipient": "手动客户",
                            "host": "测试主播A",
                            "perf_mode": "",
                            "foreign_text": fx_mixed,
                            "chinese_text": "今天赞美主。现在凭信心祷告。",
                            "image_path": str(img_16x9),
                            "aspect_ratio": "",
                            "material_source": "",
                            "red_spans": [(0, red_len)],
                        },
                        {
                            "recipient": "手动客户",
                            "host": "测试主播A",
                            "perf_mode": "睁眼说话",
                            "foreign_text": "Mungu akubariki kila siku.",
                            "chinese_text": "",
                            "image_path": "",  # Shares host's image_path automatically!
                            "aspect_ratio": "",
                            "material_source": "",
                            "red_spans": [],
                        },
                        {
                            # Blank row at bottom is ignored cleanly
                            "recipient": "",
                            "host": "",
                            "foreign_text": "",
                        },
                    ],
                    work_date="2026-11-02",
                )

                self.assertEqual(res["created_tasks"], 2)
                self.assertEqual(res["promoted_created"], 2)

                groups, tasks, _ = workspace_intake.snapshot("2026-11-02")
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]["recipient"], "手动客户")
                self.assertEqual(groups[0]["anchor_name"], "测试主播A")
                self.assertEqual(groups[0]["status"], "READY_FOR_GPT")
                self.assertEqual(len(tasks), 2)

                # Verify host aspect_ratio == 16:9 and mixed eye_states were persisted to studio.db
                hid = int(groups[0]["host_id"])
                self.assertEqual(studio_repo.get_host_aspect_ratio(hid), "16:9")

                vid1 = int(tasks[0]["video_id"])
                with studio_db.connect() as con:
                    segs = con.execute(
                        "SELECT id, foreign_text FROM flow_segments WHERE video_id=? ORDER BY seg_seq",
                        (vid1,),
                    ).fetchall()
                from app.services.sheet_style import load_video
                saved_style = load_video(vid1)
                blocks = eye_states.blocks(saved_style["外文内容"], fallback="PRAYING")
                self.assertEqual([m for _, m in blocks], ["TALKING", "PRAYING"])
                self.assertGreaterEqual(len(segs), 2)

                # Simulate a subsequent Google Sheet sync for a different spreadsheet_id:
                # manual tasks MUST remain active (sheet_row > 0) and untouched!
                parsed_sheet = {
                    "tasks": [
                        {
                            "表格行号": 5,
                            "需求人员": "云端客户",
                            "主播名称": "云端主播B",
                            "中文内容": "你好",
                            "外文内容": "Jambo sana.",
                            "需求说明": "睁眼",
                            "模式": "TALKING",
                            "主播图片链接": "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrSt",
                            "素材来源": "",
                        }
                    ]
                }
                intake.import_tasks(parsed_sheet, "sheet_xyz", "0")
                con_i = sqlite3.connect(test_intake)
                try:
                    manual_active = con_i.execute(
                        "SELECT COUNT(*) FROM tasks WHERE spreadsheet_id='manual' AND sheet_row>0"
                    ).fetchone()[0]
                    self.assertEqual(manual_active, 2)
                finally:
                    con_i.close()

    @unittest.skipUnless(FUSCRIPT.is_file(), "DaVinci fuscript not installed")
    def test_lua_wakeup_and_export_only_fast_paths(self):
        lua_code = r'''
local bridgeDir = assert(os.getenv("FS_TEST_BRIDGE_DIR"))

-- 1. Test prepareDaily skips SaveProject & CloseProject when already on target project + timeline
FLOWSTUDIO_DAILY_TEST = true
local prepareDaily = assert(loadfile(bridgeDir .. "/FlowStudio_Resolve_Bridge_v0.5.0.lua"))()
FLOWSTUDIO_DAILY_TEST = false
_G.__FLOWSTUDIO_WAV16_VERIFIED = true

local saveCalls, closeCalls = 0, 0
local tlSettings = {useCustomSettings='1', timelineResolutionWidth='720', timelineResolutionHeight='1280', timelineFrameRate='25'}
local projSettings = {timelineResolutionWidth='720', timelineResolutionHeight='1280', timelineFrameRate='25'}
local tlObj = {
    GetName = function() return "MAIN-2026-11-02" end,
    GetSetting = function(_, k) return tlSettings[k] end,
    SetSetting = function(_, k, v) tlSettings[k] = v; return true end,
}
local projObj = {
    GetName = function() return "FlowStudio-2026-11-02" end,
    GetSetting = function(_, k) return projSettings[k] end,
    SetSetting = function(_, k, v) projSettings[k] = v; return true end,
    GetTimelineCount = function() return 1 end,
    GetTimelineByIndex = function(_, i) return tlObj end,
    GetCurrentTimeline = function() return tlObj end,
    SetCurrentTimeline = function() return true end,
}
local pmObj = {
    GetCurrentProject = function() return projObj end,
    SaveProject = function() saveCalls = saveCalls + 1; return true end,
    CloseProject = function() closeCalls = closeCalls + 1; return true end,
}
local resolveObj = {
    GetProjectManager = function() return pmObj end,
}
local res = prepareDaily(resolveObj, {work_date="2026-11-02", timeline_name="MAIN-2026-11-02", timeline_fps="25"}, function() end)
assert(res.project == "FlowStudio-2026-11-02")
assert(saveCalls == 0, "Expected 0 SaveProject calls on already-ready project, got " .. tostring(saveCalls))
assert(closeCalls == 0, "Expected 0 CloseProject calls on wakeup, got " .. tostring(closeCalls))

-- 2. Test FlowStudio_Finish_Batch exportOnly fast-path + resolution caching + merged SetRenderSettings
local tmpRoot = os.getenv("FS_TEST_TMP")
assert(tmpRoot and tmpRoot ~= "", "FS_TEST_TMP missing")
local bid = "batch_fast_1"
local att = "deadbeef0123"
local base = tmpRoot .. "/v0_5_0/batches/" .. bid .. "/autoedit/" .. att
local payloadPath = base .. "/autoedit.ini"
os.execute("mkdir -p '" .. base .. "' '" .. tmpRoot .. "/out' '" .. tmpRoot .. "/logs'")

local function writeIni(p, tbl)
    local f = assert(io.open(p, "w"))
    for k, v in pairs(tbl) do f:write(k .. "=" .. tostring(v) .. "\n") end
    f:close()
end

-- Create 20 V1 subclips sharing only 2 MediaPoolItems -> Resolution should be queried only 2 times, File Path 0 times!
local resQueries, pathQueries, saveFinishCalls, renderSettingsCalls = 0, 0, 0, 0
local mp1 = {
    GetUniqueId = function() return "mp-1" end,
    GetClipProperty = function(_, prop)
        if prop == "Resolution" then resQueries = resQueries + 1; return "720x1280" end
        if prop == "File Path" then pathQueries = pathQueries + 1; return "/tmp/seg1.mp4" end
        return ""
    end,
}
local mp2 = {
    GetUniqueId = function() return "mp-2" end,
    GetClipProperty = function(_, prop)
        if prop == "Resolution" then resQueries = resQueries + 1; return "720x1280" end
        if prop == "File Path" then pathQueries = pathQueries + 1; return "/tmp/seg2.mp4" end
        return ""
    end,
}

local v1Clips, fpRows = {}, {}
for i = 1, 20 do
    local s, e = (i - 1) * 50, i * 50
    local cid = "clip-" .. i
    local mpRef = (i <= 10) and mp1 or mp2
    v1Clips[#v1Clips + 1] = {
        GetUniqueId = function() return cid end,
        GetStart = function() return s end,
        GetEnd = function() return e end,
        GetMediaPoolItem = function() return mpRef end,
    }
    fpRows[#fpRows + 1] = "video:1:" .. cid .. ":" .. s .. ":" .. e
end
table.sort(fpRows)
local expectedFp = table.concat(fpRows, ";")

writeIni(payloadPath, {
    batch_id = bid,
    attempt_id = att,
    work_date = "2026-11-02",
    project_name = "FlowStudio-2026-11-02",
    timeline_name = "MAIN-2026-11-02",
    timeline_fps = "25",
    video_count = "2",
    v1_id = "101",
    v1_final_filename = "vid1.mp4",
    v1_output_dir = tmpRoot .. "/out",
    v2_id = "102",
    v2_final_filename = "vid2.mp4",
    v2_output_dir = tmpRoot .. "/out",
})
writeIni(base .. "/state.ini", {timeline_id = "tl-uid-1", stage = "CLEANED_READY"})
writeIni(base .. "/cleaned.ini", {
    batch_id = bid,
    timeline_id = "tl-uid-1",
    video_count = "2",
    v1_start = "0",
    v1_end = "500",
    v1_skip = "false",
    v2_start = "500",
    v2_end = "1000",
    v2_skip = "false",
    snapshot = expectedFp,
})

local jobSeq = 0
local jobOutputs = {}
local finishTl = {
    GetName = function() return "MAIN-2026-11-02" end,
    GetUniqueId = function() return "tl-uid-1" end,
    GetStartFrame = function() return 0 end,
    GetTrackCount = function(_, kind) return kind == "video" and 1 or (kind == "subtitle" and 1 or 0) end,
    GetItemListInTrack = function(_, kind, idx) return kind == "video" and v1Clips or {} end,
    GetSetting = function(_, k) return k == "timelineResolutionWidth" and "720" or "1280" end,
    SetTrackEnable = function() return true end,
}
local finishProj = {
    GetName = function() return "FlowStudio-2026-11-02" end,
    GetCurrentTimeline = function() return finishTl end,
    IsRenderingInProgress = function() return false end,
    LoadRenderPreset = function() return true end,
    SetCurrentRenderFormatAndCodec = function() return true end,
    SetCurrentRenderMode = function() return true end,
    SetRenderSettings = function(_, tbl)
        renderSettingsCalls = renderSettingsCalls + 1
        if tbl.CustomName then
            jobOutputs[jobSeq + 1] = tbl.TargetDir .. "/" .. tbl.CustomName .. ".mp4"
        end
        return true
    end,
    AddRenderJob = function()
        jobSeq = jobSeq + 1
        return "rjob-" .. jobSeq
    end,
    StartRendering = function()
        for _, outPath in pairs(jobOutputs) do
            local f = assert(io.open(outPath, "wb"))
            f:write("mp4data")
            f:close()
        end
        return true
    end,
    GetRenderJobStatus = function(_, rid)
        return {JobStatus = "Complete", CompletionPercentage = 100}
    end,
}
local finishPm = {
    GetCurrentProject = function() return finishProj end,
    SaveProject = function() saveFinishCalls = saveFinishCalls + 1; return true end,
}
local finishApp = {
    GetProjectManager = function() return finishPm end,
}

local finishMod = assert(loadfile(bridgeDir .. "/FlowStudio_Finish_Batch.lua"))()
local outRes = finishMod.run(
    finishApp,
    {batch_id = bid, attempt_id = att, work_date = "2026-11-02", payload_path = payloadPath, finish_mode = "export", subtitle_video_ids = "101"},
    function() end,
    {root = tmpRoot, noSleep = true}
)
assert(saveFinishCalls == 0, "exportOnly fast-path should call SaveProject 0 times, got " .. tostring(saveFinishCalls))
assert(pathQueries == 0, "exportOnly fast-path should call GetClipProperty('File Path') 0 times, got " .. tostring(pathQueries))
assert(resQueries == 2, "Resolution cache should query 2 MediaPoolItems instead of 20 clips, got " .. tostring(resQueries))
assert(renderSettingsCalls == 2, "Merged SetRenderSettings should run 1 call per video (2 total), got " .. tostring(renderSettingsCalls))
print("LUA_FAST_PATH_TESTS_OK")
'''
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, FS_TEST_TMP=tmp, FS_TEST_BRIDGE_DIR=str(BASE / "davinci_autoedit_v0_5_0"))
            proc = subprocess.run([str(FUSCRIPT), "-x", lua_code], capture_output=True, text=True, env=env)
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            self.assertEqual(proc.returncode, 0, combined)
            self.assertIn("LUA_FAST_PATH_TESTS_OK", combined, combined)


if __name__ == "__main__":
    unittest.main()
