"""Pure re-download service for completed Flow segments.

Re-fetches already-generated videos by their bound Flow ``media_id`` and
``collection_url`` via the browser extension, overwriting/restoring the local
MP4 file in place WITHOUT modifying prompts, resetting QC state, or spending
credits on new generations.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path
from threading import Lock

from app.core import repository as repo
from app.core import work_dates
from app.core.database import connect
from app.core.work_dates import read_connection
from app.services import runtime_log

_LOCK = Lock()
# segment_id -> {request_id, status, message, created_at, updated_at, expected_path, channel_key, collection_url, media_id, command_id}
_ACTIVE: dict[int, dict] = {}
_STALE_TIMEOUT_SEC = 180.0


def _is_cloud_media_id(value: str) -> bool:
    s = str(value or "").strip()
    if not s:
        return False
    low = s.lower()
    if low.startswith(("local:", "plugin:", "manual:", "custom:", "file:")):
        return False
    return True


def _clean_stem(name: str) -> str:
    s = str(name or "").strip()
    if s.lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
        s = Path(s).stem
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s).strip(". ")
    return s[:80]


def _expire_stale_locked(now: float | None = None) -> None:
    t = time.time() if now is None else now
    for sid, st in list(_ACTIVE.items()):
        cur = str(st.get("status") or "")
        age = t - float(st.get("updated_at") or st.get("created_at") or t)
        if cur in ("queued", "downloading") and age > _STALE_TIMEOUT_SEC:
            st["status"] = "failed"
            st["message"] = "等待浏览器插件响应超时（请确认对应通道浏览器已打开并连接 Bridge）"
            st["updated_at"] = t
        elif cur in ("completed", "failed") and age > 1800.0:
            _ACTIVE.pop(sid, None)


def active_states() -> dict[int, dict]:
    with _LOCK:
        _expire_stale_locked()
        return {sid: dict(info) for sid, info in _ACTIVE.items()}


def clear_finished_state(segment_id: int | None = None) -> None:
    with _LOCK:
        if segment_id is not None:
            info = _ACTIVE.get(int(segment_id))
            if info and info.get("status") in ("completed", "failed"):
                _ACTIVE.pop(int(segment_id), None)
            return
        for sid in [k for k, v in _ACTIVE.items() if v.get("status") in ("completed", "failed")]:
            _ACTIVE.pop(sid, None)


def on_bridge_event(event: dict, resolved_path: str = "") -> bool:
    """Update live re-download tracking when the plugin reports progress/completion."""
    if not isinstance(event, dict):
        return False
    req_id = str(event.get("redownload_request_id") or "").strip()
    try:
        sid = int(event.get("segment_id") or 0)
    except (TypeError, ValueError):
        sid = 0
    if not sid:
        return False

    typ = str(event.get("type") or "")
    now = time.time()
    with _LOCK:
        cur = _ACTIVE.get(sid)
        if not cur:
            if not req_id:
                return False
            cur = {
                "request_id": req_id,
                "segment_id": sid,
                "command_id": str(event.get("command_id") or ""),
                "media_id": str(event.get("media_id") or ""),
                "created_at": now,
            }
            _ACTIVE[sid] = cur
        elif req_id and cur.get("request_id") and cur["request_id"] != req_id:
            # Ignore stale events from a superseded re-download click
            return False

        if typ in ("redownload_claimed", "video_download_started"):
            if cur.get("status") != "completed":
                cur["status"] = "downloading"
                cur["message"] = str(event.get("message") or "正在从 Flow 拉取最新直链并下载…")
                cur["updated_at"] = now
            return True
        if typ == "video_download_completed":
            p = str(resolved_path or event.get("output_path") or event.get("local_path") or "").strip()
            cur["status"] = "completed"
            cur["output_path"] = p
            cur["message"] = "✓ 已重新下载"
            cur["updated_at"] = now
            return True
        if typ in ("video_download_failed", "redownload_failed"):
            if bool(event.get("retrying")):
                cur["status"] = "downloading"
                cur["message"] = str(event.get("message") or "下载波动，插件正在刷新直链重试…")
                cur["updated_at"] = now
                return True
            err = str(event.get("error") or event.get("message") or "重新下载失败").strip()
            cur["status"] = "failed"
            cur["message"] = f"重下失败：{err}"
            cur["updated_at"] = now
            return True
    return False


def snapshot_for_date(work_date: str | None = None) -> dict:
    """Read all tasks for ``work_date`` and build the host-grouped downloaded view model."""
    day = work_date or work_dates.active()
    sql = """
        SELECT
            fs.id AS segment_id,
            fs.seg_seq,
            fs.foreign_text,
            COALESCE(fs.status, '') AS seg_lifecycle_status,
            COALESCE(fs.flow_status, '') AS flow_status,
            COALESCE(fs.flow_output_path, '') AS flow_output_path,
            COALESCE(fs.qc_status, '待质检') AS qc_status,
            COALESCE(fs.generation_command, '') AS generation_command,
            COALESCE(fs.flow_channel_key, '') AS flow_channel_key,
            fs.flow_completed_at,
            v.id AS video_id,
            v.seq AS video_seq,
            COALESCE(v.image_path, '') AS image_path,
            h.id AS host_id,
            COALESCE(h.name, '') AS host_name,
            COALESCE(h.image_path, '') AS host_avatar_path,
            r.id AS recipient_id,
            COALESCE(r.name, '') AS recipient_name,
            (
                SELECT fo.media_id
                FROM flow_outputs fo
                WHERE fo.segment_id = fs.id
                  AND (fo.command_id = fs.generation_command OR COALESCE(fs.generation_command, '') = '')
                ORDER BY
                    CASE
                        WHEN fo.media_id LIKE 'local:%' OR fo.media_id LIKE 'plugin:%' THEN 1
                        ELSE 0
                    END ASC,
                    fo.id DESC
                LIMIT 1
            ) AS media_id,
            (
                SELECT fo.output_path
                FROM flow_outputs fo
                WHERE fo.segment_id = fs.id
                  AND (fo.command_id = fs.generation_command OR COALESCE(fs.generation_command, '') = '')
                ORDER BY fo.id DESC
                LIMIT 1
            ) AS fo_output_path,
            (
                SELECT fd.expected_filename
                FROM flow_dispatches fd
                WHERE fd.segment_id = fs.id AND fd.command_id = fs.generation_command
                ORDER BY fd.id DESC
                LIMIT 1
            ) AS expected_filename,
            (
                SELECT fd.channel_key
                FROM flow_dispatches fd
                WHERE fd.segment_id = fs.id AND fd.command_id = fs.generation_command
                ORDER BY fd.id DESC
                LIMIT 1
            ) AS dispatch_channel_key
        FROM flow_segments fs
        JOIN videos v ON v.id = fs.video_id
        JOIN hosts h ON h.id = v.host_id
        JOIN recipients r ON r.id = h.recipient_id
        WHERE TRIM(COALESCE(fs.prompt, '')) <> ''
          AND COALESCE(fs.prompt_review_status, '待检查') = '已提交'
          AND COALESCE(fs.status, '') NOT IN ('已撤销', '已作废')
        ORDER BY r.id DESC, h.id ASC, v.seq ASC, fs.seg_seq ASC
    """
    with read_connection(day) as con:
        all_rows = [dict(r) for r in con.execute(sql).fetchall()]

    rt_states = active_states()

    # Compute per-host & per-video totals (excluding legacy aux pseudo-segments for video metrics)
    recipients_map: dict[int, dict] = {}
    total_downloaded = 0
    total_ok = 0
    total_missing = 0
    total_active_redl = 0

    # Group all rows by recipient -> host -> video first so we know total segments/videos per host
    grouped_all: dict[int, dict] = {}
    for row in all_rows:
        seg_seq = int(row.get("seg_seq") or 0)
        ftxt = str(row.get("foreign_text") or "")
        if seg_seq >= 1000 and "[LEGACY_AUX]" in ftxt:
            continue
        rid = int(row["recipient_id"])
        hid = int(row["host_id"])
        vid = int(row["video_id"])
        rec_g = grouped_all.setdefault(
            rid,
            {
                "recipient_id": rid,
                "recipient_name": str(row.get("recipient_name") or "未命名接收人"),
                "hosts": {},
            },
        )
        host_g = rec_g["hosts"].setdefault(
            hid,
            {
                "host_id": hid,
                "host_name": str(row.get("host_name") or "未命名主播"),
                "image_path": str(row.get("host_avatar_path") or row.get("image_path") or ""),
                "videos_all": {},
            },
        )
        if not host_g["image_path"] and row.get("image_path"):
            host_g["image_path"] = str(row["image_path"])
        host_g["videos_all"].setdefault(vid, []).append(row)

    for rid, rec_g in grouped_all.items():
        hosts_out = []
        rec_dl_segs = 0
        rec_total_segs = 0
        rec_dl_videos = 0
        rec_total_videos = 0
        rec_ok_files = 0
        rec_missing_files = 0
        rec_redl_active = 0

        for hid, host_g in rec_g["hosts"].items():
            videos_all = host_g["videos_all"]
            h_total_videos = len(videos_all)
            h_total_segs = sum(len(v_rows) for v_rows in videos_all.values())
            h_dl_videos = 0
            h_dl_segs = 0
            h_ok_files = 0
            h_missing_files = 0
            h_redl_active = 0
            videos_out = []

            for vid, v_rows in videos_all.items():
                v_total = len(v_rows)
                dl_rows = [r for r in v_rows if str(r.get("flow_status") or "") == "已完成"]
                if len(dl_rows) == v_total and v_total > 0:
                    h_dl_videos += 1

                segs_out = []
                for r in v_rows:
                    sid = int(r["segment_id"])
                    f_status = str(r.get("flow_status") or "待生成")
                    is_completed = f_status == "已完成"
                    out_path = str(r.get("flow_output_path") or r.get("fo_output_path") or "").strip() if is_completed else ""
                    if not is_completed:
                        file_state = "uncompleted"
                        file_size = 0
                    else:
                        file_state = "missing"
                        file_size = 0
                        if out_path:
                            try:
                                p = Path(out_path).expanduser()
                                if p.is_file():
                                    file_size = int(p.stat().st_size)
                                    file_state = "ok" if file_size > 0 else "corrupt"
                            except OSError:
                                file_state = "missing"

                    cmd = str(r.get("generation_command") or "").strip()
                    mid = str(r.get("media_id") or "").strip()
                    ch_key = str(r.get("flow_channel_key") or r.get("dispatch_channel_key") or "").strip()
                    # Cloud re-download is supported whenever we have a real Flow media_id OR a Flow generation command
                    # (for local:* rows whose media_id can be recovered from flow_receipts).
                    can_redownload = bool(
                        is_completed
                        and (
                            _is_cloud_media_id(mid)
                            or (cmd and not cmd.startswith(("local-import", "custom-", "manual-")))
                        )
                    )

                    rt = rt_states.get(sid) or {}
                    rt_status = str(rt.get("status") or "")
                    rt_msg = str(rt.get("message") or "")
                    if rt_status in ("queued", "downloading"):
                        h_redl_active += 1
                        total_active_redl += 1

                    if is_completed:
                        if file_state == "ok":
                            h_ok_files += 1
                            total_ok += 1
                        else:
                            h_missing_files += 1
                            total_missing += 1
                        h_dl_segs += 1
                        total_downloaded += 1

                    exp_name = str(r.get("expected_filename") or "").strip()
                    if is_completed:
                        display_file = Path(out_path).name if out_path else (exp_name or f"{int(r['video_seq']):02d}-{int(r['seg_seq']):02d}-{host_g['host_name']}-S{sid:06d}.mp4")
                    else:
                        display_file = f"（未生成 · {f_status}）可点击右侧 📤 手动导入视频"

                    segs_out.append(
                        {
                            "segment_id": sid,
                            "video_id": vid,
                            "video_seq": int(r.get("video_seq") or 0),
                            "seg_seq": int(r.get("seg_seq") or 0),
                            "code": f"{int(r.get('video_seq') or 0):02d}-{int(r.get('seg_seq') or 0):02d}",
                            "filename": display_file,
                            "output_path": out_path,
                            "channel_key": ch_key or "—",
                            "flow_status": f_status,
                            "qc_status": str(r.get("qc_status") or "待质检"),
                            "file_state": file_state,
                            "file_size": file_size,
                            "can_redownload": can_redownload,
                            "redownload_status": rt_status,
                            "redownload_message": rt_msg,
                            "completed_at": str(r.get("flow_completed_at") or ""),
                        }
                    )

                videos_out.append(
                    {
                        "video_id": vid,
                        "video_seq": int(v_rows[0].get("video_seq") or 0),
                        "total_segments": v_total,
                        "downloaded_segments": len(dl_rows),
                        "complete_video": len(dl_rows) == v_total and v_total > 0,
                        "segments": segs_out,
                    }
                )

            if h_total_segs <= 0:
                continue

            rec_dl_segs += h_dl_segs
            rec_total_segs += h_total_segs
            rec_dl_videos += h_dl_videos
            rec_total_videos += h_total_videos
            rec_ok_files += h_ok_files
            rec_missing_files += h_missing_files
            rec_redl_active += h_redl_active

            hosts_out.append(
                {
                    "host_id": hid,
                    "recipient_id": rid,
                    "recipient_name": rec_g["recipient_name"],
                    "host_name": host_g["host_name"],
                    "image_path": host_g["image_path"],
                    "dl_videos": h_dl_videos,
                    "total_videos": h_total_videos,
                    "dl_segments": h_dl_segs,
                    "total_segments": h_total_segs,
                    "ok_files": h_ok_files,
                    "missing_files": h_missing_files,
                    "redl_active": h_redl_active,
                    "videos": videos_out,
                }
            )

        if not hosts_out:
            continue

        recipients_map[rid] = {
            "recipient_id": rid,
            "recipient_name": rec_g["recipient_name"],
            "hosts": hosts_out,
            "dl_hosts": len(hosts_out),
            "dl_videos": rec_dl_videos,
            "total_videos": rec_total_videos,
            "dl_segments": rec_dl_segs,
            "total_segments": rec_total_segs,
            "ok_files": rec_ok_files,
            "missing_files": rec_missing_files,
            "redl_active": rec_redl_active,
        }

    return {
        "work_date": day,
        "total_downloaded": total_downloaded,
        "total_ok": total_ok,
        "total_missing": total_missing,
        "total_active_redl": total_active_redl,
        "recipients": list(recipients_map.values()),
    }


def _recover_from_receipts(con, missing_pairs: list[tuple[int, str]]) -> dict[tuple[int, str], dict]:
    """Recover ``media_id`` and exact historical ``collection_url`` from ``flow_receipts``."""
    recovered: dict[tuple[int, str], dict] = {}
    if not missing_pairs:
        return recovered
    by_sid: dict[int, set[str]] = {}
    for sid, cmd in missing_pairs:
        by_sid.setdefault(int(sid), set()).add(str(cmd or ""))

    for sid, cmds in by_sid.items():
        # Match JSON payloads containing this segment_id
        rows = con.execute(
            "SELECT payload FROM flow_receipts WHERE payload LIKE ? OR payload LIKE ? ORDER BY rowid DESC LIMIT 30",
            (f'%"segment_id": {sid}%', f'%"segment_id":{sid}%'),
        ).fetchall()
        for r in rows:
            try:
                d = json.loads(r[0])
            except Exception:
                continue
            if int(d.get("segment_id") or 0) != sid:
                continue
            rcmd = str(d.get("command_id") or "")
            if cmds and rcmd not in cmds and "" not in cmds:
                continue
            key = (sid, rcmd)
            slot = recovered.setdefault(key, {})
            if not slot.get("media_id"):
                mid = str(d.get("media_id") or "").strip()
                if not _is_cloud_media_id(mid):
                    gen_ids = d.get("generation_ids")
                    if isinstance(gen_ids, list) and gen_ids:
                        cand = str(gen_ids[0] or "").strip()
                        if _is_cloud_media_id(cand):
                            mid = cand
                if _is_cloud_media_id(mid):
                    slot["media_id"] = mid
            if not slot.get("collection_url"):
                url = str(d.get("collection_url") or "").strip()
                if url.startswith("https://flow.google.com/"):
                    slot["collection_url"] = url
            if not slot.get("channel_key") and d.get("channel_key"):
                slot["channel_key"] = str(d.get("channel_key") or "").strip()
            if not slot.get("download_name") and (d.get("download_name") or d.get("task_name")):
                slot["download_name"] = str(d.get("download_name") or d.get("task_name") or "").strip()
    return recovered


def submit_redownload(segment_ids: list[int], bridge, work_date: str | None = None) -> dict:
    """Queue pure re-download jobs for ``segment_ids`` without touching prompts or QC status."""
    clean_ids = sorted({int(x) for x in (segment_ids or []) if int(x) > 0})
    if not clean_ids:
        raise ValueError("请先勾选需要重新下载的视频或片段。")
    if bridge is None:
        raise ValueError("本地 Bridge 未初始化，无法下发重新下载指令。")

    st = bridge.status()
    if not st.get("connected"):
        raise ValueError("当前未检测到浏览器插件连接（Bridge 离线）。请先确认 Chrome 已打开 Flow 页面且插件在线后再试。")

    placeholders = ",".join("?" * len(clean_ids))
    with connect() as con:
        rows = [
            dict(r)
            for r in con.execute(
                f"""
                SELECT
                    fs.id AS segment_id,
                    fs.seg_seq,
                    fs.flow_status,
                    COALESCE(fs.flow_output_path, '') AS flow_output_path,
                    COALESCE(fs.generation_command, '') AS generation_command,
                    COALESCE(fs.flow_channel_key, '') AS flow_channel_key,
                    v.id AS video_id,
                    v.seq AS video_seq,
                    h.id AS host_id,
                    COALESCE(h.name, '') AS host_name,
                    COALESCE(h.flow_collection_url, '') AS host_project_url,
                    r.id AS recipient_id,
                    COALESCE(r.name, '') AS recipient_name
                FROM flow_segments fs
                JOIN videos v ON v.id = fs.video_id
                JOIN hosts h ON h.id = v.host_id
                JOIN recipients r ON r.id = h.recipient_id
                WHERE fs.id IN ({placeholders})
                ORDER BY r.id DESC, h.id ASC, v.seq ASC, fs.seg_seq ASC
                """,
                clean_ids,
            ).fetchall()
        ]
        if not rows:
            raise ValueError("未找到选中的片段记录。")

        channels_by_key = {
            str(c["channel_key"]): dict(c)
            for c in repo.list_channel_pool(enabled_only=False)
        }
        has_owners_tbl = bool(
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='browser_command_owners'"
            ).fetchone()
        )
        owners_by_cmd: dict[str, str] = {}
        if has_owners_tbl:
            cmds = sorted({str(r["generation_command"]) for r in rows if r.get("generation_command")})
            if cmds:
                c_ph = ",".join("?" * len(cmds))
                for orow in con.execute(
                    f"SELECT command_id, owner FROM browser_command_owners WHERE command_id IN ({c_ph})",
                    cmds,
                ).fetchall():
                    owners_by_cmd[str(orow[0])] = str(orow[1] or "")

        outputs_by_seg: dict[int, list[dict]] = {}
        for orow in con.execute(
            f"SELECT segment_id, command_id, media_id, output_path FROM flow_outputs WHERE segment_id IN ({placeholders}) ORDER BY id DESC",
            clean_ids,
        ).fetchall():
            outputs_by_seg.setdefault(int(orow["segment_id"]), []).append(dict(orow))

        dispatches_by_seg: dict[int, list[dict]] = {}
        for drow in con.execute(
            f"""SELECT segment_id, command_id, channel_key, dispatch_order, round_no, task_name, expected_filename
                FROM flow_dispatches WHERE segment_id IN ({placeholders}) ORDER BY id DESC""",
            clean_ids,
        ).fetchall():
            dispatches_by_seg.setdefault(int(drow["segment_id"]), []).append(dict(drow))

        # Always check flow_receipts for historical collection_url (in case channel pool URL changed later)
        # and to recover cloud media_id when folder watcher recorded local:* first.
        pairs = [(int(r["segment_id"]), str(r.get("generation_command") or "")) for r in rows]
        receipt_meta = _recover_from_receipts(con, pairs)

    jobs_to_enqueue = []
    skipped = []
    now = time.time()

    with _LOCK:
        _expire_stale_locked(now)
        for r in rows:
            sid = int(r["segment_id"])
            cmd = str(r.get("generation_command") or "").strip()
            existing_active = _ACTIVE.get(sid)
            if existing_active and existing_active.get("status") in ("queued", "downloading"):
                skipped.append((sid, "已在重新下载队列中"))
                continue

            outs = outputs_by_seg.get(sid) or []
            matching_outs = [o for o in outs if not cmd or str(o.get("command_id") or "") == cmd] or outs
            media_id = ""
            fo_path = ""
            for o in matching_outs:
                if not fo_path and o.get("output_path"):
                    fo_path = str(o["output_path"])
                cand = str(o.get("media_id") or "").strip()
                if _is_cloud_media_id(cand):
                    media_id = cand
                    break

            rec_info = receipt_meta.get((sid, cmd)) or {}
            if not _is_cloud_media_id(media_id) and _is_cloud_media_id(rec_info.get("media_id", "")):
                media_id = str(rec_info["media_id"]).strip()

            if not _is_cloud_media_id(media_id):
                skipped.append((sid, "无云端视频 ID（本地手动导入片段无法从云端重下）"))
                continue

            disps = dispatches_by_seg.get(sid) or []
            disp = next((d for d in disps if not cmd or str(d.get("command_id") or "") == cmd), disps[0] if disps else {})

            ch_key = (
                str(r.get("flow_channel_key") or "").strip()
                or str(disp.get("channel_key") or "").strip()
                or str(rec_info.get("channel_key") or "").strip()
                or "CH1"
            )
            ch_row = channels_by_key.get(ch_key) or {}
            # Prefer exact historical collection_url from receipt so changing channel URL later never breaks re-download!
            collection_url = (
                str(rec_info.get("collection_url") or "").strip()
                or str(ch_row.get("collection_url") or "").strip()
                or str(r.get("host_project_url") or "").strip()
            )
            if not collection_url.startswith("https://flow.google.com/"):
                skipped.append((sid, f"通道 {ch_key} 未配置有效的 Flow 项目链接"))
                continue

            cur_path_str = str(r.get("flow_output_path") or fo_path or "").strip()
            stem = ""
            download_folder = ""
            if cur_path_str:
                cp = Path(cur_path_str).expanduser()
                stem = _clean_stem(cp.stem)
                parts = cp.parts
                if "FlowStudio_Channels" in parts:
                    idx = parts.index("FlowStudio_Channels")
                    if idx + 1 < len(parts) - 1:
                        download_folder = "/".join(parts[idx : len(parts) - 1])
            if not stem:
                stem = (
                    _clean_stem(disp.get("expected_filename") or "")
                    or _clean_stem(disp.get("task_name") or "")
                    or _clean_stem(rec_info.get("download_name") or "")
                    or _clean_stem(f"{int(r['video_seq']):02d}-{int(r['seg_seq']):02d}-{r['host_name']}-S{sid:06d}")
                )
            if not download_folder:
                subdir = str(ch_row.get("download_subdir") or ch_key or "CH1").strip().strip("/\\")
                download_folder = f"FlowStudio_Channels/{subdir}"

            owner_raw = owners_by_cmd.get(cmd, "")
            browser_instance = owner_raw.split(":", 1)[0] if ":" in owner_raw else ""
            browser_group = repo.channel_browser_group(ch_key) if ch_key else "A"

            req_id = f"redl-{sid}-{secrets.token_hex(6)}"
            round_no = int(disp.get("round_no") or 1)
            dispatch_order = int(disp.get("dispatch_order") or 1)
            doc_num = max(1, int(r.get("video_seq") or 1))
            dl_root = Path.home() / "Downloads"
            ch_root_setting = repo.get_setting("flow_channel_download_root", "").strip()
            if ch_root_setting and download_folder.startswith("FlowStudio_Channels/"):
                rel_sub = download_folder.split("/", 1)[1]
                expected_path = str((Path(ch_root_setting).expanduser() / rel_sub / f"{stem}.mp4"))
            else:
                expected_path = str(dl_root / download_folder / f"{stem}.mp4")

            job = {
                "request_id": req_id,
                "segment_id": sid,
                "command_id": cmd,
                "media_id": media_id,
                "collection_url": collection_url,
                "channel_id": int(ch_row.get("id") or 0),
                "channel_key": ch_key,
                "browser_group": browser_group,
                "browser_instance": browser_instance,
                "download_folder": download_folder,
                "download_name": stem,
                "task_name": stem,
                "task_id": f"{int(r['video_seq']):02d}-{int(r['seg_seq']):02d}",
                "document_number": doc_num,
                "dispatch_order": dispatch_order,
                "round": round_no,
                "host_id": int(r["host_id"]),
                "host_name": str(r["host_name"] or ""),
                "recipient_id": int(r["recipient_id"]),
                "recipient_name": str(r["recipient_name"] or ""),
                "expected_path": expected_path,
                "requested_at": now,
            }
            _ACTIVE[sid] = {
                "request_id": req_id,
                "segment_id": sid,
                "command_id": cmd,
                "media_id": media_id,
                "channel_key": ch_key,
                "collection_url": collection_url,
                "expected_path": expected_path,
                "status": "queued",
                "message": "已下发重下指令，等待浏览器拉取…",
                "created_at": now,
                "updated_at": now,
            }
            jobs_to_enqueue.append(job)

    if jobs_to_enqueue:
        bridge.enqueue_redownload_jobs(jobs_to_enqueue)
        runtime_log.log(
            "redownload_jobs_submitted",
            count=len(jobs_to_enqueue),
            skipped=len(skipped),
            segment_ids=[j["segment_id"] for j in jobs_to_enqueue],
        )

    return {
        "queued": len(jobs_to_enqueue),
        "skipped": skipped,
        "jobs": jobs_to_enqueue,
    }
