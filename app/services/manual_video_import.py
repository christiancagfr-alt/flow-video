"""Manual external video import service for Flow segments, whole videos, and whole hosts.

Allows the user to import externally generated MP4/MOV/M4V/WEBM video files directly
into Flow Studio at three granularities:
1. Single Segment (``import_single_segment_video``)
2. Whole Video by sequence order (``plan_video_files_match`` / ``execute_manual_imports``)
3. Whole Host by sequence order or filename code ``02-05`` (``plan_host_files_match`` / ``execute_manual_imports``)

Safely cancels any in-flight browser generation command for the replaced segment,
copies the external video into the managed local output directory so external source
files are never modified or lost, updates ``flow_segments`` and ``flow_outputs``,
and triggers ``workflow.reconcile_video_qc`` so downstream QC and DaVinci Auto-Edit
pick up the imported clips immediately.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from app.core import repository as repo
from app.core import work_dates
from app.core.database import connect
from app.core.work_dates import read_connection
from app.services import runtime_log, workflow

VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm")

# Matches explicit "02-05" or "02_05" or "V02-S05" at start or boundary of filename stem
_EXPLICIT_V_S_RE = re.compile(r"(?:^|[^0-9])0*(\d{1,3})\s*[-_]\s*0*(\d{1,3})(?:$|[^0-9])")
_TRAILING_NUM_RE = re.compile(r"(\d+)")


def is_video_file(path: str | Path) -> bool:
    try:
        p = Path(path).expanduser()
        return p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS and p.stat().st_size > 0
    except OSError:
        return False


def natural_sort_key(path: str | Path) -> tuple:
    """Sort file paths in human natural order (e.g. 1.mp4, 2.mp4, 10.mp4)."""
    name = Path(path).name.lower()
    parts = re.split(r"(\d+)", name)
    return tuple(int(p) if p.isdigit() else p for p in parts)


def collect_video_files_from_folder(folder: str | Path) -> list[str]:
    """Collect all valid video files from ``folder`` (including 1 level of subfolders if needed), sorted naturally."""
    root = Path(folder).expanduser()
    if not root.is_dir():
        return []
    found: list[Path] = []
    for item in root.iterdir():
        if item.name.startswith("."):
            continue
        if item.is_file() and is_video_file(item):
            found.append(item)
        elif item.is_dir():
            for sub in item.iterdir():
                if not sub.name.startswith(".") and sub.is_file() and is_video_file(sub):
                    found.append(sub)
    found.sort(key=lambda p: (natural_sort_key(p.parent.name) if p.parent != root else (), natural_sort_key(p.name)))
    return [str(p) for p in found]


def _safe_name(value: str) -> str:
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(value or "").strip()).strip(". ")
    return text[:80] or "未命名"


def list_host_segments(host_id: int, *, work_date: str | None = None) -> list[dict]:
    """Return all active segments (both completed and pending) for ``host_id`` in ``(video_seq, seg_seq)`` order."""
    day = work_date or work_dates.active()
    sql = """
        SELECT
            fs.id AS segment_id,
            fs.seg_seq,
            fs.foreign_text,
            COALESCE(fs.flow_status, '待生成') AS flow_status,
            COALESCE(fs.flow_output_path, '') AS flow_output_path,
            COALESCE(fs.qc_status, '待质检') AS qc_status,
            COALESCE(fs.generation_command, '') AS generation_command,
            COALESCE(fs.flow_channel_key, '') AS flow_channel_key,
            v.id AS video_id,
            v.seq AS video_seq,
            h.id AS host_id,
            COALESCE(h.name, '') AS host_name,
            r.id AS recipient_id,
            COALESCE(r.name, '') AS recipient_name,
            r.work_date AS work_date
        FROM flow_segments fs
        JOIN videos v ON v.id = fs.video_id
        JOIN hosts h ON h.id = v.host_id
        JOIN recipients r ON r.id = h.recipient_id
        WHERE h.id = ?
          AND COALESCE(fs.status, '') NOT IN ('已撤销', '已作废')
          AND NOT (fs.seg_seq >= 1000 AND COALESCE(fs.foreign_text, '') LIKE '[LEGACY_AUX]%')
        ORDER BY v.seq ASC, fs.seg_seq ASC, fs.id ASC
    """
    with read_connection(day) as con:
        rows = [dict(r) for r in con.execute(sql, (int(host_id),)).fetchall()]
    for r in rows:
        r["code"] = f"{int(r['video_seq']):02d}-{int(r['seg_seq']):02d}"
    return rows


def list_video_segments(video_id: int, *, work_date: str | None = None) -> list[dict]:
    """Return all active segments (both completed and pending) for ``video_id`` in ``seg_seq`` order."""
    day = work_date or work_dates.active()
    sql = """
        SELECT
            fs.id AS segment_id,
            fs.seg_seq,
            fs.foreign_text,
            COALESCE(fs.flow_status, '待生成') AS flow_status,
            COALESCE(fs.flow_output_path, '') AS flow_output_path,
            COALESCE(fs.qc_status, '待质检') AS qc_status,
            COALESCE(fs.generation_command, '') AS generation_command,
            COALESCE(fs.flow_channel_key, '') AS flow_channel_key,
            v.id AS video_id,
            v.seq AS video_seq,
            h.id AS host_id,
            COALESCE(h.name, '') AS host_name,
            r.id AS recipient_id,
            COALESCE(r.name, '') AS recipient_name,
            r.work_date AS work_date
        FROM flow_segments fs
        JOIN videos v ON v.id = fs.video_id
        JOIN hosts h ON h.id = v.host_id
        JOIN recipients r ON r.id = h.recipient_id
        WHERE v.id = ?
          AND COALESCE(fs.status, '') NOT IN ('已撤销', '已作废')
          AND NOT (fs.seg_seq >= 1000 AND COALESCE(fs.foreign_text, '') LIKE '[LEGACY_AUX]%')
        ORDER BY fs.seg_seq ASC, fs.id ASC
    """
    with read_connection(day) as con:
        rows = [dict(r) for r in con.execute(sql, (int(video_id),)).fetchall()]
    for r in rows:
        r["code"] = f"{int(r['video_seq']):02d}-{int(r['seg_seq']):02d}"
    return rows


def plan_video_files_match(video_id: int, file_paths: list[str], *, work_date: str | None = None) -> dict:
    """Match external video files to segments of ``video_id`` by sequence number or natural order.

    Returns ``{"segments": segs, "pairs": [(seg_dict, file_path), ...], "unmatched_files": [...], "unmatched_segments": [...]}``.
    """
    segs = list_video_segments(video_id, work_date=work_date)
    valid_files = [str(Path(p).expanduser()) for p in (file_paths or []) if is_video_file(p)]
    valid_files.sort(key=natural_sort_key)
    if not segs or not valid_files:
        return {
            "segments": segs,
            "pairs": [],
            "unmatched_files": valid_files,
            "unmatched_segments": segs,
        }

    v_seq = int(segs[0]["video_seq"])
    by_seg_seq = {int(s["seg_seq"]): s for s in segs}

    # First check if filenames carry explicit V-S codes (e.g. 02-01.mp4) matching this video
    explicit_hits: dict[int, str] = {}
    remaining_files: list[str] = []
    for fp in valid_files:
        stem = Path(fp).stem
        m = _EXPLICIT_V_S_RE.search(stem)
        if m and int(m.group(1)) == v_seq and int(m.group(2)) in by_seg_seq and int(m.group(2)) not in explicit_hits:
            explicit_hits[int(m.group(2))] = fp
        else:
            remaining_files.append(fp)

    pairs: list[tuple[dict, str]] = []
    used_sids: set[int] = set()

    if len(explicit_hits) == len(valid_files):
        # All files matched explicit codes
        for seq_no in sorted(explicit_hits):
            seg = by_seg_seq[seq_no]
            pairs.append((seg, explicit_hits[seq_no]))
            used_sids.add(int(seg["segment_id"]))
        unmatched_files = []
    else:
        # Pure sequential mapping in natural sort order (1st file -> seg 01, 2nd file -> seg 02, ...)
        for seg, fp in zip(segs, valid_files):
            pairs.append((seg, fp))
            used_sids.add(int(seg["segment_id"]))
        unmatched_files = valid_files[len(pairs) :]

    unmatched_segments = [s for s in segs if int(s["segment_id"]) not in used_sids]
    return {
        "segments": segs,
        "pairs": pairs,
        "unmatched_files": unmatched_files,
        "unmatched_segments": unmatched_segments,
    }


def plan_host_files_match(
    host_id: int,
    file_paths: list[str],
    *,
    only_incomplete: bool = False,
    work_date: str | None = None,
) -> dict:
    """Match external video files to segments of ``host_id``.

    Strategy:
    1. Any file whose name contains an explicit ``VV-SS`` code (e.g. ``01-02``, ``28-01``)
       that exists under this host is matched directly to that exact segment.
    2. Remaining files are matched in natural sort order to the remaining target segments
       in ``(video_seq, seg_seq)`` order.
    """
    all_segs = list_host_segments(host_id, work_date=work_date)
    if only_incomplete:
        target_segs = [
            s
            for s in all_segs
            if str(s.get("flow_status") or "") != "已完成"
            or not is_video_file(str(s.get("flow_output_path") or ""))
        ]
    else:
        target_segs = list(all_segs)

    valid_files = [str(Path(p).expanduser()) for p in (file_paths or []) if is_video_file(p)]
    valid_files.sort(key=natural_sort_key)
    if not target_segs or not valid_files:
        return {
            "segments": target_segs,
            "pairs": [],
            "unmatched_files": valid_files,
            "unmatched_segments": target_segs,
        }

    by_vs: dict[tuple[int, int], dict] = {
        (int(s["video_seq"]), int(s["seg_seq"])): s for s in all_segs
    }
    target_by_vs: dict[tuple[int, int], dict] = {
        (int(s["video_seq"]), int(s["seg_seq"])): s for s in target_segs
    }

    matched_by_sid: dict[int, tuple[dict, str]] = {}
    remaining_files: list[str] = []

    for fp in valid_files:
        stem = Path(fp).stem
        m = _EXPLICIT_V_S_RE.search(stem)
        if m:
            key = (int(m.group(1)), int(m.group(2)))
            seg = target_by_vs.get(key) or by_vs.get(key)
            if seg and int(seg["segment_id"]) not in matched_by_sid:
                matched_by_sid[int(seg["segment_id"])] = (seg, fp)
                continue
        remaining_files.append(fp)

    remaining_segs = [s for s in target_segs if int(s["segment_id"]) not in matched_by_sid]
    for seg, fp in zip(remaining_segs, remaining_files):
        matched_by_sid[int(seg["segment_id"])] = (seg, fp)

    # Order pairs by (video_seq, seg_seq)
    pairs = sorted(
        matched_by_sid.values(),
        key=lambda item: (int(item[0]["video_seq"]), int(item[0]["seg_seq"]), int(item[0]["segment_id"])),
    )
    used_files = {fp for _, fp in pairs}
    used_sids = {int(s["segment_id"]) for s, _ in pairs}
    unmatched_files = [fp for fp in valid_files if fp not in used_files]
    unmatched_segments = [s for s in target_segs if int(s["segment_id"]) not in used_sids]

    return {
        "segments": target_segs,
        "pairs": pairs,
        "unmatched_files": unmatched_files,
        "unmatched_segments": unmatched_segments,
    }


def _resolve_import_destination(seg_row: dict, src_path: Path) -> Path:
    """Determine the managed local file path where an imported video should be stored."""
    ext = src_path.suffix.lower() if src_path.suffix.lower() in VIDEO_EXTENSIONS else ".mp4"
    sid = int(seg_row["segment_id"])
    v_seq = int(seg_row.get("video_seq") or 0)
    s_seq = int(seg_row.get("seg_seq") or 0)
    h_name = _safe_name(seg_row.get("host_name") or "主播")

    cur_out = str(seg_row.get("flow_output_path") or "").strip()
    if cur_out:
        cp = Path(cur_out).expanduser()
        if cp.parent.exists():
            return cp.with_suffix(ext)

    ch_key = _safe_name(seg_row.get("flow_channel_key") or "LOCAL")
    custom_root = repo.get_setting("flow_channel_download_root", "").strip()
    base_root = Path(custom_root).expanduser() if custom_root else (Path.home() / "Downloads" / "FlowStudio_Channels")
    folder = base_root / ch_key
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{v_seq:02d}-{s_seq:02d}-{h_name}-S{sid:06d}{ext}"
    return folder / filename


def execute_manual_imports(
    pairs: list[tuple[int | dict, str]],
    *,
    bridge=None,
    auto_pass_qc: bool = False,
) -> dict:
    """Import external video files into the specified segments.

    ``pairs`` can be ``[(segment_id, file_path), ...]`` or ``[(seg_dict, file_path), ...]``.
    Returns ``{"imported": count, "segment_ids": [...], "video_ids": [...], "errors": [...]}``.
    """
    normalized: list[tuple[int, Path]] = []
    errors: list[str] = []
    seen_sids: set[int] = set()

    for seg_or_id, raw_fp in pairs or []:
        sid = int(seg_or_id["segment_id"]) if isinstance(seg_or_id, dict) else int(seg_or_id)
        if sid in seen_sids:
            continue
        seen_sids.add(sid)
        p = Path(str(raw_fp or "")).expanduser()
        if not is_video_file(p):
            errors.append(f"S{sid:06d}: 视频文件不存在或为空 ({p.name})")
            continue
        normalized.append((sid, p))

    if not normalized:
        return {"imported": 0, "segment_ids": [], "video_ids": [], "errors": errors}

    sids = [sid for sid, _ in normalized]
    marks = ",".join("?" * len(sids))
    with connect() as con:
        db_rows = {
            int(r["segment_id"]): dict(r)
            for r in con.execute(
                f"""
                SELECT
                    fs.id AS segment_id,
                    fs.seg_seq,
                    fs.video_id,
                    COALESCE(fs.flow_status, '') AS flow_status,
                    COALESCE(fs.flow_output_path, '') AS flow_output_path,
                    COALESCE(fs.generation_command, '') AS generation_command,
                    COALESCE(fs.flow_channel_key, '') AS flow_channel_key,
                    COALESCE(fs.qc_status, '待质检') AS qc_status,
                    v.seq AS video_seq,
                    COALESCE(h.name, '') AS host_name,
                    COALESCE(r.name, '') AS recipient_name,
                    r.work_date AS work_date
                FROM flow_segments fs
                JOIN videos v ON v.id = fs.video_id
                JOIN hosts h ON h.id = v.host_id
                JOIN recipients r ON r.id = h.recipient_id
                WHERE fs.id IN ({marks})
                """,
                sids,
            ).fetchall()
        }

        # Check active commands that might need bridge cancellation
        cmds_to_check = {
            str(r["generation_command"] or "")
            for r in db_rows.values()
            if str(r.get("generation_command") or "")
            and str(r.get("flow_status") or "") not in ("已完成", "失败", "下载失败", "已放弃")
        }
        cmd_has_outside_active: dict[str, bool] = {}
        target_sid_set = set(sids)
        for cmd in cmds_to_check:
            rem = con.execute(
                "SELECT id FROM flow_segments WHERE generation_command=? AND flow_status NOT IN ('已完成','失败','下载失败','已放弃')",
                (cmd,),
            ).fetchall()
            cmd_has_outside_active[cmd] = any(int(x[0]) not in target_sid_set for x in rem)

    # Cancel or detach in-flight browser commands before writing
    if bridge is not None and cmds_to_check:
        full_cancel = [cmd for cmd, has_other in cmd_has_outside_active.items() if not has_other]
        if full_cancel:
            try:
                bridge.cancel_host_commands(full_cancel)
            except Exception:
                pass
        for sid, _ in normalized:
            r = db_rows.get(sid)
            if not r:
                continue
            cmd = str(r.get("generation_command") or "")
            if cmd and cmd_has_outside_active.get(cmd):
                try:
                    bridge.remove_task_from_command(cmd, sid)
                except Exception:
                    pass

    prepared_copies: list[tuple[int, dict, Path]] = []
    for sid, src_path in normalized:
        row = db_rows.get(sid)
        if not row:
            errors.append(f"S{sid:06d}: 数据库中未找到该片段")
            continue
        dst_path = _resolve_import_destination(row, src_path)
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.resolve() != dst_path.resolve():
                tmp_dst = dst_path.with_name(f".import_tmp_{sid}_{int(time.time() * 1000)}{dst_path.suffix}")
                shutil.copy2(str(src_path), str(tmp_dst))
                os.replace(str(tmp_dst), str(dst_path))
            prepared_copies.append((sid, row, dst_path))
        except Exception as exc:
            errors.append(f"{row['video_seq']:02d}-{row['seg_seq']:02d}: 复制视频文件失败 ({exc})")

    if not prepared_copies:
        return {"imported": 0, "segment_ids": [], "video_ids": [], "errors": errors}

    imported_sids: list[int] = []
    affected_vids: set[int] = set()
    now_ms = int(time.time() * 1000)

    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        for sid, row, dst_path in prepared_copies:
            old_cmd = str(row.get("generation_command") or "").strip()
            old_ch = str(row.get("flow_channel_key") or "").strip()

            # Preserve existing cloud command_id & media_id if this segment was already completed via Flow,
            # or bind a clean manual import command if it was never generated or was still running/failed.
            was_completed = str(row.get("flow_status") or "") == "已完成"
            if old_cmd and not was_completed:
                con.execute(
                    "INSERT OR IGNORE INTO flow_obsolete_segments(segment_id, command_id) VALUES(?, ?)",
                    (sid, old_cmd),
                )
                con.execute(
                    "UPDATE flow_dispatches SET status='cancelled', stage='CANCELLED', error='已被手动导入外部视频接管' WHERE segment_id=? AND command_id=?",
                    (sid, old_cmd),
                )
                if old_ch and not cmd_has_outside_active.get(old_cmd):
                    con.execute(
                        "UPDATE flow_channel_pool SET task_command_id='', upload_state='idle' WHERE channel_key=? AND task_command_id=?",
                        (old_ch, old_cmd),
                    )

            eff_cmd = old_cmd if (was_completed and old_cmd) else f"local-import-{sid}-{now_ms}"
            eff_media = f"local:manual:{dst_path.name}"
            cur_qc = str(row.get("qc_status") or "待质检")
            target_qc = "通过" if auto_pass_qc else ("通过" if cur_qc == "通过" else "待质检")

            # Ensure segment is marked submitted so it appears in all downstream views
            con.execute(
                """
                UPDATE flow_segments
                SET prompt_review_status = CASE WHEN COALESCE(prompt_review_status, '') IN ('', '待检查') THEN '已提交' ELSE prompt_review_status END,
                    prompt = CASE WHEN TRIM(COALESCE(prompt, '')) = '' THEN COALESCE(NULLIF(TRIM(foreign_text), ''), '[手动导入视频]') ELSE prompt END,
                    generation_command = ?,
                    flow_status = '已完成',
                    flow_output_path = ?,
                    flow_output_url = '',
                    flow_error = '',
                    qc_status = ?,
                    flow_completed_at = COALESCE(NULLIF(flow_completed_at, ''), CURRENT_TIMESTAMP)
                WHERE id = ?
                """,
                (eff_cmd, str(dst_path), target_qc, sid),
            )

            # Upsert flow_outputs so QC and _current_edit_segments see the exact output_path & qc_status
            existing_out = con.execute(
                "SELECT id FROM flow_outputs WHERE segment_id=? AND command_id=? ORDER BY id DESC LIMIT 1",
                (sid, eff_cmd),
            ).fetchone()
            if existing_out:
                con.execute(
                    "UPDATE flow_outputs SET output_path=?, qc_status=? WHERE id=?",
                    (str(dst_path), target_qc, int(existing_out[0])),
                )
            else:
                con.execute(
                    "INSERT INTO flow_outputs(segment_id, command_id, media_id, output_path, qc_status) VALUES(?, ?, ?, ?, ?)",
                    (sid, eff_cmd, eff_media, str(dst_path), target_qc),
                )

            con.execute("DELETE FROM flow_redo WHERE segment_id=?", (sid,))
            con.execute("DELETE FROM flow_recovery WHERE segment_id=?", (sid,))
            imported_sids.append(sid)
            affected_vids.add(int(row["video_id"]))

        if imported_sids and con.execute("SELECT 1 FROM sqlite_master WHERE name='flow_pending_downloads'").fetchone():
            imp_set = set(imported_sids)
            for p_row in con.execute("SELECT event_id, payload FROM flow_pending_downloads").fetchall():
                try:
                    payload = json.loads(p_row["payload"] or "{}")
                    if int(payload.get("segment_id") or 0) in imp_set:
                        con.execute("DELETE FROM flow_pending_downloads WHERE event_id=?", (p_row["event_id"],))
                except Exception:
                    continue

        for vid in sorted(affected_vids):
            workflow.reconcile_video_qc(vid, con)

    runtime_log.log(
        "manual_video_imported",
        count=len(imported_sids),
        segment_ids=imported_sids,
        video_ids=sorted(affected_vids),
        auto_pass_qc=auto_pass_qc,
    )
    return {
        "imported": len(imported_sids),
        "segment_ids": imported_sids,
        "video_ids": sorted(affected_vids),
        "errors": errors,
    }
