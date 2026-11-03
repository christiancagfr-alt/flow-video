"""Automatic rolling SQLite maintenance for studio.db and pre_gpt_pipeline.sqlite3.

Policy (Option B):
  1. Ephemeral process receipts / snapshots (> 14 days):
     - Clean old rows from flow_receipts, prompt_submission_history (finished segments only),
       flow_pending_downloads, flow_obsolete_commands, flow_obsolete_segments,
       flow_failure_attempts, flow_task_actions, pipeline_events, sync_history, web_fetch_jobs.
  2. Completed historical task partitions (> 30 days):
     - Clean historical videos/segments/hosts/recipients whose work_date is > 30 days old,
       strictly skipping the currently active date, any in-flight Flow/DaVinci work, and any
       task still present as an active row (sheet_row > 0) in the Google Sheet intake DB.
     - Clean retired (sheet_row < 0) intake tasks > 30 days old whose studio videos were purged.
  3. Core configuration, persona libraries/defaults, API keys, B-roll presets, Flow accounts,
     Flow channel pool, packaging assets, and all local files on disk are NEVER touched.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import re
import sqlite3
import threading
import time

from app.core import database, work_dates

_MAINT_LOCK = threading.Lock()
_EYE_KEY_RE = re.compile(r"^segment_eye_types:(\d+)$")
_PERSONA_KEY_RE = re.compile(r"^host_persona_(\d+)_(?:talking|praying)$")
_RATIO_KEY_RE = re.compile(r"^host_aspect_ratio_(\d+)$")
_V8_VOICE_KEY_RE = re.compile(r"^flow_master_v8_voice_(\d+)$")
_PRIORITY_KEY_RE = re.compile(r"^flow_host_priority:(.+)$")

RECEIPT_RETENTION_DAYS = 14
TASK_RETENTION_DAYS = 30
_BATCH_SIZE = 4000
_VIDEO_CHUNK = 200


def _log(message: str, level: str = "INFO", **extra) -> None:
    try:
        from app.services import runtime_log
        runtime_log.log("db_auto_maintenance", level=level, message=message, **extra)
    except Exception:
        pass


def _close_current_thread_handles() -> None:
    """Close any thread-local pooled SQLite handles on the current maintenance thread."""
    try:
        pool = getattr(database._TLS, "pool", None) or {}
        for bucket in list(pool.values()):
            while bucket:
                con = bucket.pop()
                try:
                    con._real_close()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        handles = getattr(work_dates._SCOPED_TLS, "handles", None) or {}
        for con in list(handles.values()):
            try:
                con.close()
            except Exception:
                pass
        handles.clear()
    except Exception:
        pass


def _existing_tables(con: sqlite3.Connection, schema: str = "main") -> set[str]:
    rows = con.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(r[0]) for r in rows}


def _batched_delete_by_time(
    con_factory,
    table: str,
    col: str,
    cutoff_iso: str,
    extra_where: str = "",
    batch_size: int = _BATCH_SIZE,
) -> int:
    total = 0
    where_clause = f"{col} >= '2000-01-01' AND {col} < ?"
    if extra_where:
        where_clause = f"{where_clause} AND ({extra_where})"
    sql = f'DELETE FROM "{table}" WHERE rowid IN (SELECT rowid FROM "{table}" WHERE {where_clause} LIMIT ?)'
    while True:
        with con_factory() as con:
            cur = con.execute(sql, (cutoff_iso, int(batch_size)))
            deleted = int(cur.rowcount or 0)
        total += deleted
        if deleted < batch_size:
            break
        time.sleep(0.01)
    return total


def _active_intake_video_ids() -> set[int]:
    """Return video_ids still linked to active rows (sheet_row > 0) in pre_gpt_pipeline.sqlite3."""
    protected: set[int] = set()
    try:
        from app.services import pre_gpt_pipeline as intake
        db_file = Path(intake.DB_FILE)
        if not db_file.is_file():
            return protected
        con = sqlite3.connect(str(db_file), timeout=5.0)
        try:
            tables = _existing_tables(con, "main")
            if {"tasks", "production_links"} <= tables:
                for (vid,) in con.execute(
                    """SELECT pl.video_id
                         FROM production_links pl
                         JOIN tasks t ON t.id = pl.task_id
                        WHERE t.sheet_row > 0 AND pl.video_id IS NOT NULL"""
                ).fetchall():
                    protected.add(int(vid))
        finally:
            con.close()
    except Exception:
        pass
    return protected


def _cleanup_retired_intake_tasks(cutoff_30d: str, existing_studio_vids: set[int]) -> int:
    """Clean retired (sheet_row < 0) rows > 30 days old in pre_gpt_pipeline.sqlite3 whose studio video is gone."""
    removed_tasks = 0
    try:
        from app.services import pre_gpt_pipeline as intake
        from app.services.sheet_columns import task_work_day

        db_file = Path(intake.DB_FILE)
        if not db_file.is_file():
            return 0
        con = intake.init_db()
        try:
            tables = _existing_tables(con, "main")
            if "tasks" not in tables:
                return 0
            links = (
                dict(con.execute("SELECT task_id, video_id FROM production_links").fetchall())
                if "production_links" in tables
                else {}
            )
            stale_tids: list[int] = []
            for tid, sheet_date, created_at in con.execute(
                "SELECT id, sheet_date, created_at FROM tasks WHERE sheet_row < 0"
            ).fetchall():
                tid_int = int(tid)
                linked_vid = links.get(tid_int)
                if linked_vid is not None and int(linked_vid) in existing_studio_vids:
                    continue
                t_day = work_dates.canonical(task_work_day(sheet_date or "", created_at or "")) or work_dates.canonical(created_at)
                if t_day and t_day < cutoff_30d:
                    stale_tids.append(tid_int)

            if stale_tids:
                for i in range(0, len(stale_tids), _VIDEO_CHUNK):
                    chunk = stale_tids[i : i + _VIDEO_CHUNK]
                    ph = ",".join("?" * len(chunk))
                    con.execute("BEGIN IMMEDIATE")
                    try:
                        if "production_links" in tables:
                            con.execute(f"DELETE FROM production_links WHERE task_id IN ({ph})", chunk)
                        if "task_source_styles" in tables:
                            con.execute(f"DELETE FROM task_source_styles WHERE task_id IN ({ph})", chunk)
                        if "assets" in tables:
                            con.execute(
                                f"""DELETE FROM assets
                                     WHERE matched_task_id IN ({ph})
                                       AND group_key NOT IN (SELECT DISTINCT group_key FROM tasks WHERE sheet_row > 0)""",
                                chunk,
                            )
                        cur = con.execute(f"DELETE FROM tasks WHERE id IN ({ph}) AND sheet_row < 0", chunk)
                        removed_tasks += int(cur.rowcount or 0)
                        con.commit()
                    except Exception:
                        con.rollback()
                        raise

            if "production_links" in tables:
                # Also drop dangling links for retired tasks whose studio video no longer exists
                dangling = [
                    int(tid)
                    for tid, vid in links.items()
                    if vid is not None and int(vid) not in existing_studio_vids
                ]
                if dangling:
                    for i in range(0, len(dangling), _VIDEO_CHUNK):
                        chunk = dangling[i : i + _VIDEO_CHUNK]
                        ph = ",".join("?" * len(chunk))
                        con.execute("BEGIN IMMEDIATE")
                        con.execute(
                            f"""DELETE FROM production_links
                                 WHERE task_id IN ({ph})
                                   AND task_id IN (SELECT id FROM tasks WHERE sheet_row < 0)""",
                            chunk,
                        )
                        con.commit()

            if "intake_view_state" in tables:
                old_days = [
                    str(d)
                    for (d,) in con.execute("SELECT day FROM intake_view_state").fetchall()
                    if (cd := work_dates.canonical(d)) and cd < cutoff_30d
                ]
                if old_days:
                    ph = ",".join("?" * len(old_days))
                    con.execute("BEGIN IMMEDIATE")
                    con.execute(f"DELETE FROM intake_view_state WHERE day IN ({ph})", old_days)
                    con.commit()
        finally:
            con.close()
    except Exception:
        pass
    return removed_tasks


def run_auto_maintenance(
    *,
    today_override: str | None = None,
    force: bool = False,
    receipt_retention_days: int = RECEIPT_RETENTION_DAYS,
    task_retention_days: int = TASK_RETENTION_DAYS,
) -> dict:
    """Execute rolling 14-day receipt cleanup and 30-day completed task cleanup safely."""
    if not _MAINT_LOCK.acquire(blocking=False):
        return {"skipped": "busy"}

    try:
        ref_today = work_dates.canonical(today_override) if today_override else date.today().isoformat()
        if not ref_today:
            ref_today = date.today().isoformat()
        ref_date = date.fromisoformat(ref_today)

        with database.connect() as con:
            tables = _existing_tables(con)
            if "app_settings" not in tables:
                return {"skipped": "uninitialized"}
            enabled_row = con.execute(
                "SELECT value FROM app_settings WHERE key='db_auto_cleanup_enabled'"
            ).fetchone()
            if enabled_row is not None and str(enabled_row[0] or "1").strip() in ("0", "false", "False"):
                return {"skipped": "disabled"}
            if not force:
                last_row = con.execute(
                    "SELECT value FROM app_settings WHERE key='db_auto_cleanup_last_day'"
                ).fetchone()
                if last_row and str(last_row[0] or "").strip() == ref_today:
                    return {"skipped": "already_ran_today", "day": ref_today}

        cutoff_14d = (ref_date - timedelta(days=max(1, int(receipt_retention_days)))).isoformat()
        cutoff_30d = (ref_date - timedelta(days=max(7, int(task_retention_days)))).isoformat()
        active_day = work_dates.canonical(work_dates.active()) or work_dates.active()

        # Ensure FK & timestamp indexes exist so batched/cascaded deletes never full-scan large tables
        with database.connect() as con:
            tables = _existing_tables(con)
            idx_specs = [
                ("videos", "CREATE INDEX IF NOT EXISTS idx_perf_videos_host ON videos(host_id)"),
                ("flow_outputs", "CREATE INDEX IF NOT EXISTS idx_perf_outputs_segment ON flow_outputs(segment_id)"),
                ("qc_decisions", "CREATE INDEX IF NOT EXISTS idx_perf_qc_decisions_segment ON qc_decisions(segment_id)"),
                ("prompt_submission_history", "CREATE INDEX IF NOT EXISTS idx_perf_prompt_hist_segment ON prompt_submission_history(segment_id)"),
                ("prompt_submission_history", "CREATE INDEX IF NOT EXISTS idx_perf_prompt_hist_submitted ON prompt_submission_history(submitted_at)"),
                ("api_usage_log", "CREATE INDEX IF NOT EXISTS idx_perf_api_usage_segment ON api_usage_log(flow_segment_id)"),
                ("source_tasks", "CREATE INDEX IF NOT EXISTS idx_perf_source_tasks_video ON source_tasks(video_id)"),
                ("flow_receipts", "CREATE INDEX IF NOT EXISTS idx_perf_flow_receipts_created ON flow_receipts(created_at)"),
            ]
            for tbl, ddl in idx_specs:
                if tbl in tables:
                    con.execute(ddl)

        stats: dict[str, int | str | bool] = {
            "day": ref_today,
            "cutoff_receipts": cutoff_14d,
            "cutoff_tasks": cutoff_30d,
            "receipt_rows_deleted": 0,
            "history_snapshots_deleted": 0,
            "ephemeral_rows_deleted": 0,
            "old_videos_deleted": 0,
            "old_segments_deleted": 0,
            "old_hosts_deleted": 0,
            "old_recipients_deleted": 0,
            "intake_tasks_deleted": 0,
            "orphan_meta_deleted": 0,
            "vacuumed": False,
        }

        # ── Tier 1: 14-day ephemeral process logs & submission snapshots ──
        if "flow_receipts" in tables:
            stats["receipt_rows_deleted"] = _batched_delete_by_time(
                database.connect, "flow_receipts", "created_at", cutoff_14d
            )
        if "prompt_submission_history" in tables:
            extra = (
                "segment_id NOT IN (SELECT id FROM flow_segments "
                "WHERE COALESCE(flow_status,'') IN ('待生成','已准备','已提交','生成中','下载中'))"
                if "flow_segments" in tables
                else ""
            )
            stats["history_snapshots_deleted"] = _batched_delete_by_time(
                database.connect, "prompt_submission_history", "submitted_at", cutoff_14d, extra_where=extra
            )

        ephemeral_specs = [
            ("flow_pending_downloads", "last_attempt", ""),
            ("flow_obsolete_commands", "invalidated_at", ""),
            ("flow_obsolete_segments", "created_at", ""),
            ("flow_failure_attempts", "created_at", ""),
            ("flow_task_actions", "created_at", ""),
            ("pipeline_events", "created_at", ""),
            ("sync_history", "created_at", ""),
            ("web_fetch_jobs", "created_at", "COALESCE(status,'') NOT IN ('PENDING','RUNNING')"),
        ]
        eph_count = 0
        for tbl, col, extra_w in ephemeral_specs:
            if tbl in tables:
                eph_count += _batched_delete_by_time(database.connect, tbl, col, cutoff_14d, extra_where=extra_w)
        stats["ephemeral_rows_deleted"] = eph_count

        # ── Tier 2: 30-day completed historical task partitions ──
        sheet_active_vids = _active_intake_video_ids()
        active_cmds: set[str] = set()
        eligible_vids: list[int] = []
        old_rids: list[int] = []

        with database.connect() as con:
            tables = _existing_tables(con)
            if "flow_channel_pool" in tables:
                for tc, uc in con.execute(
                    "SELECT task_command_id, upload_command_id FROM flow_channel_pool"
                ).fetchall():
                    if tc and str(tc).strip():
                        active_cmds.add(str(tc).strip())
                    if uc and str(uc).strip():
                        active_cmds.add(str(uc).strip())

            rec_dates = work_dates.recipient_dates(con) if "recipients" in tables else {}
            old_rids = [
                int(rid)
                for rid, rday in rec_dates.items()
                if rday
                and rday != work_dates.LEGACY
                and rday != active_day
                and rday != ref_today
                and rday < cutoff_30d
            ]

            if old_rids and {"hosts", "videos"} <= tables:
                r_ph = ",".join("?" * len(old_rids))
                candidate_rows = con.execute(
                    f"""SELECT v.id, h.id, COALESCE(h.flow_upload_command_id,''), COALESCE(h.flow_task_command_id,'')
                          FROM videos v
                          JOIN hosts h ON h.id = v.host_id
                         WHERE h.recipient_id IN ({r_ph})""",
                    old_rids,
                ).fetchall()

                inflight_vids: set[int] = set(sheet_active_vids)
                if "flow_segments" in tables and candidate_rows:
                    c_vids = [int(r[0]) for r in candidate_rows]
                    for i in range(0, len(c_vids), 500):
                        chunk = c_vids[i : i + 500]
                        vp = ",".join("?" * len(chunk))
                        for vid, fstatus, gcmd in con.execute(
                            f"""SELECT video_id, COALESCE(flow_status,''), COALESCE(generation_command,'')
                                  FROM flow_segments
                                 WHERE video_id IN ({vp})""",
                            chunk,
                        ).fetchall():
                            if fstatus in ("已提交", "生成中", "下载中") or (gcmd and str(gcmd).strip() in active_cmds):
                                inflight_vids.add(int(vid))

                if {"davinci_video_state", "davinci_batches"} <= tables:
                    for (vid,) in con.execute(
                        """SELECT dvs.video_id
                             FROM davinci_video_state dvs
                             JOIN davinci_batches db ON db.batch_id = dvs.batch_id
                            WHERE UPPER(COALESCE(db.status,'')) IN ('PENDING','RUNNING','PROCESSING')"""
                    ).fetchall():
                        inflight_vids.add(int(vid))

                for vid, _hid, h_ucmd, h_tcmd in candidate_rows:
                    vid_int = int(vid)
                    if vid_int in inflight_vids:
                        continue
                    if (h_ucmd and h_ucmd.strip() in active_cmds) or (h_tcmd and h_tcmd.strip() in active_cmds):
                        continue
                    eligible_vids.append(vid_int)

        seg_child_tables = (
            "flow_outputs",
            "flow_dispatches",
            "flow_failure_attempts",
            "flow_recovery",
            "flow_duration_choices",
            "flow_redo",
            "flow_obsolete_segments",
            "prompt_submission_history",
            "prompt_fill_sources",
            "qc_decisions",
            "flow_task_actions",
            "speech_analysis",
            "local_qc_results",
            "ai_qc_results",
            "flow_split_history",
            "pipeline_events",
        )
        vid_pre_tables = (
            "editing_history",
            "source_tasks",
            "asset_jobs",
            "video_enhancement",
            "video_enhancement_plans",
            "video_source_styles",
            "custom_task_meta",
            "eye_reconcile_cache",
            "flow_split_history",
            "pipeline_events",
        )

        deleted_vids = 0
        deleted_sids = 0
        for i in range(0, len(eligible_vids), _VIDEO_CHUNK):
            v_chunk = eligible_vids[i : i + _VIDEO_CHUNK]
            vp = ",".join("?" * len(v_chunk))
            with database.connect() as con:
                con.execute("BEGIN IMMEDIATE")
                tables = _existing_tables(con)
                sids = (
                    [int(r[0]) for r in con.execute(f"SELECT id FROM flow_segments WHERE video_id IN ({vp})", v_chunk).fetchall()]
                    if "flow_segments" in tables
                    else []
                )
                if sids:
                    sp = ",".join("?" * len(sids))
                    if {"qc_clip_transforms", "flow_outputs"} <= tables:
                        con.execute(
                            f"DELETE FROM qc_clip_transforms WHERE output_id IN (SELECT id FROM flow_outputs WHERE segment_id IN ({sp}))",
                            sids,
                        )
                    if "api_usage_log" in tables:
                        con.execute(f"DELETE FROM api_usage_log WHERE flow_segment_id IN ({sp})", sids)
                    for tbl in seg_child_tables:
                        if tbl in tables:
                            con.execute(f'DELETE FROM "{tbl}" WHERE segment_id IN ({sp})', sids)
                    cur_s = con.execute(f"DELETE FROM flow_segments WHERE id IN ({sp})", sids)
                    deleted_sids += int(cur_s.rowcount or 0)

                for tbl in vid_pre_tables:
                    if tbl in tables:
                        con.execute(f'DELETE FROM "{tbl}" WHERE video_id IN ({vp})', v_chunk)

                # Delete videos BEFORE davinci_video_state so protect_completed_davinci_video_state trigger allows cleanup
                cur_v = con.execute(f"DELETE FROM videos WHERE id IN ({vp})", v_chunk)
                deleted_vids += int(cur_v.rowcount or 0)

                if "davinci_video_state" in tables:
                    con.execute(f"DELETE FROM davinci_video_state WHERE video_id IN ({vp})", v_chunk)
            time.sleep(0.01)

        stats["old_videos_deleted"] = deleted_vids
        stats["old_segments_deleted"] = deleted_sids

        # Clean empty old hosts, recipients, and >30d completed DaVinci batches
        if old_rids:
            with database.connect() as con:
                con.execute("BEGIN IMMEDIATE")
                tables = _existing_tables(con)
                r_ph = ",".join("?" * len(old_rids))
                if "hosts" in tables:
                    empty_hosts = [
                        int(hid)
                        for hid, ucmd, tcmd in con.execute(
                            f"""SELECT h.id, COALESCE(h.flow_upload_command_id,''), COALESCE(h.flow_task_command_id,'')
                                  FROM hosts h
                                 WHERE h.recipient_id IN ({r_ph})
                                   AND NOT EXISTS (SELECT 1 FROM videos v WHERE v.host_id = h.id)""",
                            old_rids,
                        ).fetchall()
                        if ucmd.strip() not in active_cmds and tcmd.strip() not in active_cmds
                    ]
                    if empty_hosts:
                        hp = ",".join("?" * len(empty_hosts))
                        if "flow_channels" in tables:
                            con.execute(f"DELETE FROM flow_channels WHERE host_id IN ({hp})", empty_hosts)
                        cur_h = con.execute(f"DELETE FROM hosts WHERE id IN ({hp})", empty_hosts)
                        stats["old_hosts_deleted"] = int(cur_h.rowcount or 0)

                if "recipients" in tables:
                    cur_r = con.execute(
                        f"""DELETE FROM recipients
                             WHERE id IN ({r_ph})
                               AND NOT EXISTS (SELECT 1 FROM hosts h WHERE h.recipient_id = recipients.id)""",
                        old_rids,
                    )
                    stats["old_recipients_deleted"] = int(cur_r.rowcount or 0)

                if "davinci_batches" in tables:
                    old_batches = []
                    for bid, bday, bstatus in con.execute(
                        "SELECT batch_id, work_date, COALESCE(status,'') FROM davinci_batches"
                    ).fetchall():
                        cday = work_dates.canonical(bday)
                        if (
                            cday
                            and cday < cutoff_30d
                            and bstatus.upper() not in ("PENDING", "RUNNING", "PROCESSING")
                        ):
                            has_vid = (
                                con.execute(
                                    "SELECT 1 FROM davinci_video_state WHERE batch_id=? LIMIT 1", (bid,)
                                ).fetchone()
                                if "davinci_video_state" in tables
                                else None
                            )
                            if not has_vid:
                                old_batches.append(str(bid))
                    if old_batches:
                        bp = ",".join("?" * len(old_batches))
                        if "davinci_autoedit_runs" in tables:
                            con.execute(f"DELETE FROM davinci_autoedit_runs WHERE batch_id IN ({bp})", old_batches)
                        con.execute(f"DELETE FROM davinci_batches WHERE batch_id IN ({bp})", old_batches)

                if "davinci_rebuild_receipts" in tables:
                    old_rebuilds = [
                        str(rid)
                        for rid, wday in con.execute("SELECT rebuild_id, work_date FROM davinci_rebuild_receipts").fetchall()
                        if (cday := work_dates.canonical(wday)) and cday < cutoff_30d
                    ]
                    if old_rebuilds:
                        rp = ",".join("?" * len(old_rebuilds))
                        con.execute(f"DELETE FROM davinci_rebuild_receipts WHERE rebuild_id IN ({rp})", old_rebuilds)

        # ── Tier 3: Orphan runtime metadata & intake retired rows ──
        orphan_deleted = 0
        with database.connect() as con:
            tables = _existing_tables(con)
            live_vids = {int(r[0]) for r in con.execute("SELECT id FROM videos").fetchall()} if "videos" in tables else set()
            live_hids = {int(r[0]) for r in con.execute("SELECT id FROM hosts").fetchall()} if "hosts" in tables else set()
            live_days = set(work_dates.recipient_dates(con).values()) if "recipients" in tables else set()

            con.execute("BEGIN IMMEDIATE")
            if {"browser_command_owners", "flow_dispatches"} <= tables:
                if active_cmds:
                    ap = ",".join("?" * len(active_cmds))
                    cur_b = con.execute(
                        f"""DELETE FROM browser_command_owners
                             WHERE command_id NOT IN (SELECT command_id FROM flow_dispatches WHERE command_id IS NOT NULL)
                               AND command_id NOT IN ({ap})""",
                        tuple(active_cmds),
                    )
                else:
                    cur_b = con.execute(
                        """DELETE FROM browser_command_owners
                            WHERE command_id NOT IN (SELECT command_id FROM flow_dispatches WHERE command_id IS NOT NULL)"""
                    )
                orphan_deleted += int(cur_b.rowcount or 0)

            if {"qc_clip_transforms", "flow_outputs"} <= tables:
                cur_q = con.execute(
                    "DELETE FROM qc_clip_transforms WHERE output_id NOT IN (SELECT id FROM flow_outputs)"
                )
                orphan_deleted += int(cur_q.rowcount or 0)

            if {"davinci_video_state", "videos"} <= tables:
                cur_dvs = con.execute(
                    "DELETE FROM davinci_video_state WHERE video_id NOT IN (SELECT id FROM videos)"
                )
                orphan_deleted += int(cur_dvs.rowcount or 0)

            # Strictly prune ONLY orphaned per-ID / per-date runtime keys in app_settings;
            # never touch any global setting, persona library, default persona, or API key.
            stale_keys: list[str] = []
            for (k,) in con.execute(
                """SELECT key FROM app_settings
                    WHERE key LIKE 'segment_eye_types:%'
                       OR key LIKE 'host_persona_%'
                       OR key LIKE 'host_aspect_ratio_%'
                       OR key LIKE 'flow_master_v8_voice_%'
                       OR key LIKE 'flow_host_priority:%'"""
            ).fetchall():
                key_str = str(k or "")
                m = _EYE_KEY_RE.match(key_str)
                if m:
                    if int(m.group(1)) not in live_vids:
                        stale_keys.append(key_str)
                    continue
                for rx in (_PERSONA_KEY_RE, _RATIO_KEY_RE, _V8_VOICE_KEY_RE):
                    mh = rx.match(key_str)
                    if mh:
                        if int(mh.group(1)) not in live_hids:
                            stale_keys.append(key_str)
                        break
                else:
                    mp = _PRIORITY_KEY_RE.match(key_str)
                    if mp:
                        pday = work_dates.canonical(mp.group(1))
                        if pday and pday < cutoff_30d and pday not in live_days:
                            stale_keys.append(key_str)

            for i in range(0, len(stale_keys), 500):
                kchunk = stale_keys[i : i + 500]
                kp = ",".join("?" * len(kchunk))
                cur_k = con.execute(f"DELETE FROM app_settings WHERE key IN ({kp})", kchunk)
                orphan_deleted += int(cur_k.rowcount or 0)

            con.execute(
                "INSERT INTO app_settings(key, value) VALUES('db_auto_cleanup_last_day', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (ref_today,),
            )

        stats["orphan_meta_deleted"] = orphan_deleted
        stats["intake_tasks_deleted"] = _cleanup_retired_intake_tasks(cutoff_30d, live_vids)

        if deleted_vids > 0:
            try:
                from app.services import sheet_style, packaging_tasks
                sheet_style._snapshot_cache.clear()
                packaging_tasks._PATH_KEY_CACHE.clear()
            except Exception:
                pass

        # ── Step 4: Non-blocking WAL checkpoint + idle compaction when free space >= 64 MB ──
        _close_current_thread_handles()
        try:
            raw = sqlite3.connect(str(database.DB_PATH), timeout=5.0, isolation_level=None)
            try:
                raw.execute("PRAGMA wal_checkpoint(PASSIVE)")
                if not active_cmds:
                    page_size = int(raw.execute("PRAGMA page_size").fetchone()[0] or 4096)
                    freelist = int(raw.execute("PRAGMA freelist_count").fetchone()[0] or 0)
                    free_bytes = page_size * freelist
                    if free_bytes >= 64 * 1024 * 1024:
                        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        raw.execute("VACUUM")
                        stats["vacuumed"] = True
            finally:
                raw.close()
        except Exception:
            pass

        _log(
            "auto cleanup finished",
            receipts=stats["receipt_rows_deleted"],
            snapshots=stats["history_snapshots_deleted"],
            videos=stats["old_videos_deleted"],
            segments=stats["old_segments_deleted"],
            orphans=stats["orphan_meta_deleted"],
            vacuumed=stats["vacuumed"],
        )
        return stats
    except Exception as exc:
        _log(f"auto cleanup error: {exc}", level="ERROR")
        return {"error": str(exc)}
    finally:
        _close_current_thread_handles()
        _MAINT_LOCK.release()


def trigger_background_maintenance() -> None:
    """Spawn a low-impact daemon thread to run daily DB auto-maintenance if due."""
    threading.Thread(
        target=run_auto_maintenance,
        name="db-auto-maintenance",
        daemon=True,
    ).start()
