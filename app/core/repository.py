
from __future__ import annotations
from pathlib import Path
import json
from .database import connect
from .work_dates import read_connection
import re as _re
import json as _json
import time as _time
import uuid as _uuid

def list_recipients(*, work_date=None):
    with read_connection(work_date) as con:
        return con.execute("""
            SELECT r.*,
                   COUNT(DISTINCT h.id) AS host_count,
                   COUNT(v.id) AS video_count
            FROM recipients r
            LEFT JOIN hosts h ON h.recipient_id = r.id
            LEFT JOIN videos v ON v.host_id = h.id
            GROUP BY r.id
            ORDER BY r.id DESC
        """).fetchall()


def add_recipient(name, fixed_code, creator, work_date):
    with connect() as con:
        cur = con.execute(
            "INSERT INTO recipients(name,fixed_code,creator,work_date) VALUES(?,?,?,?)",
            (name.strip(), fixed_code.strip() or "ZB", creator.strip(), work_date)
        )
        return cur.lastrowid

def get_recipient(recipient_id):
    with connect() as con:
        return con.execute("SELECT * FROM recipients WHERE id=?", (recipient_id,)).fetchone()

def delete_recipient(recipient_id):
    with connect() as con:
        con.execute("DELETE FROM recipients WHERE id=?", (recipient_id,))

def list_hosts(recipient_id, *, work_date=None):
    with read_connection(work_date) as con:
        return con.execute("""
            SELECT h.*,
                   COALESCE(
                       NULLIF((SELECT value FROM app_settings WHERE key='host_aspect_ratio_' || h.id), ''),
                       NULLIF((SELECT value FROM app_settings WHERE key='host_aspect_ratio_name_' || TRIM(h.name)), ''),
                       '9:16'
                   ) AS aspect_ratio,
                   COUNT(v.id) AS actual_video_count
            FROM hosts h
            LEFT JOIN videos v ON v.host_id=h.id
            WHERE h.recipient_id=?
            GROUP BY h.id
            ORDER BY h.id
        """, (recipient_id,)).fetchall()


def get_host_with_recipient(host_id):
    with connect() as con:
        return con.execute("""
            SELECT h.*, r.name recipient_name, r.fixed_code, r.creator, r.work_date
            FROM hosts h JOIN recipients r ON r.id=h.recipient_id
            WHERE h.id=?
        """, (host_id,)).fetchone()

def add_host(recipient_id, name, video_count, image_path=""):
    with connect() as con:
        cur = con.execute(
            "INSERT INTO hosts(recipient_id,name,video_count,image_path) VALUES(?,?,?,?)",
            (recipient_id, name.strip(), int(video_count), image_path)
        )
        host_id = cur.lastrowid
        con.executemany(
            "INSERT INTO videos(host_id,seq) VALUES(?,?)",
            [(host_id, i) for i in range(1, int(video_count)+1)]
        )
        return host_id

def delete_host(host_id):
    with connect() as con:
        con.execute("DELETE FROM hosts WHERE id=?", (host_id,))


def normalize_aspect_ratio(value) -> str:
    raw = str(value or "").strip().upper()
    if raw in ("16:9", "LANDSCAPE", "VIDEO_ASPECT_RATIO_LANDSCAPE", "横屏"):
        return "16:9"
    return "9:16"


def get_host_aspect_ratio(host_id, *, work_date=None) -> str:
    if not host_id:
        return "9:16"
    hid = int(host_id)
    with read_connection(work_date) as con:
        row = con.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (f"host_aspect_ratio_{hid}",),
        ).fetchone()
        if row and str(row["value"] or "").strip():
            return normalize_aspect_ratio(row["value"])
        try:
            nrow = con.execute("SELECT name FROM hosts WHERE id=?", (hid,)).fetchone()
            hname = str(nrow["name"] or "").strip() if nrow else ""
            if hname:
                by_name = con.execute(
                    "SELECT value FROM app_settings WHERE key=?",
                    (f"host_aspect_ratio_name_{hname}",),
                ).fetchone()
                if by_name and str(by_name["value"] or "").strip():
                    return normalize_aspect_ratio(by_name["value"])
        except Exception:
            pass
        try:
            hrow = con.execute(
                "SELECT flow_aspect_ratio FROM hosts WHERE id=?",
                (hid,),
            ).fetchone()
            if hrow and str(hrow["flow_aspect_ratio"] or "").strip():
                return normalize_aspect_ratio(hrow["flow_aspect_ratio"])
        except Exception:
            pass
    return "9:16"


def set_host_aspect_ratio(host_id, aspect_ratio: str) -> str:
    if not host_id:
        return "9:16"
    hid = int(host_id)
    ratio = normalize_aspect_ratio(aspect_ratio)
    with connect() as con:
        con.execute(
            "INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"host_aspect_ratio_{hid}", ratio),
        )
        try:
            nrow = con.execute("SELECT name FROM hosts WHERE id=?", (hid,)).fetchone()
            hname = str(nrow["name"] or "").strip() if nrow else ""
            if hname:
                con.execute(
                    "INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (f"host_aspect_ratio_name_{hname}", ratio),
                )
        except Exception:
            pass
        try:
            con.execute(
                "UPDATE hosts SET flow_aspect_ratio=? WHERE id=?",
                (ratio, hid),
            )
        except Exception:
            try:
                con.execute("ALTER TABLE hosts ADD COLUMN flow_aspect_ratio TEXT NOT NULL DEFAULT '9:16'")
                con.execute("UPDATE hosts SET flow_aspect_ratio=? WHERE id=?", (ratio, hid))
            except Exception:
                pass
    return ratio


def list_videos(host_id, *, work_date=None):
    with read_connection(work_date) as con:
        return con.execute("SELECT * FROM videos WHERE host_id=? ORDER BY seq", (host_id,)).fetchall()


def update_video_fields(video_id, chinese=None, foreign=None, image_path=None):
    fields, vals = [], []
    if chinese is not None:
        fields.append("chinese_script=?"); vals.append(chinese)
    if foreign is not None:
        fields.append("script=?"); vals.append(foreign)
    if image_path is not None:
        fields.append("image_path=?"); vals.append(image_path)
    if not fields:
        return
    vals.append(video_id)
    with connect() as con:
        con.execute(f"UPDATE videos SET {', '.join(fields)} WHERE id=?", vals)

def bulk_set_images(host_id, seq_to_path):
    with connect() as con:
        for seq, path in seq_to_path.items():
            con.execute(
                "UPDATE videos SET image_path=? WHERE host_id=? AND seq=?",
                (path, host_id, seq)
            )

def clear_host_images(host_id):
    with connect() as con:
        con.execute("UPDATE videos SET image_path='' WHERE host_id=?", (host_id,))


def recipient_dashboard(recipient_id, *, work_date=None):
    with read_connection(work_date) as con:
        recipient = con.execute("SELECT * FROM recipients WHERE id=?", (recipient_id,)).fetchone()
        hosts = con.execute("""
            SELECT h.*,
                   COUNT(v.id) AS video_count_actual,
                   SUM(CASE WHEN TRIM(COALESCE(v.chinese_script,''))<>'' THEN 1 ELSE 0 END) AS chinese_ready,
                   SUM(CASE WHEN TRIM(COALESCE(v.script,''))<>'' THEN 1 ELSE 0 END) AS foreign_ready,
                   SUM(CASE WHEN TRIM(COALESCE(v.image_path,''))<>'' THEN 1 ELSE 0 END) AS images_ready,
                   MIN(CASE WHEN TRIM(COALESCE(v.image_path,''))<>'' THEN v.image_path ELSE NULL END) AS thumbnail
            FROM hosts h
            LEFT JOIN videos v ON v.host_id=h.id
            WHERE h.recipient_id=?
            GROUP BY h.id
            ORDER BY h.id
        """, (recipient_id,)).fetchall()

        total = sum(int(h["video_count_actual"] or 0) for h in hosts)
        chinese = sum(int(h["chinese_ready"] or 0) for h in hosts)
        foreign = sum(int(h["foreign_ready"] or 0) for h in hosts)
        images = sum(int(h["images_ready"] or 0) for h in hosts)

        fully_prepared = min(chinese, foreign, images) if total else 0

        # Flow segments / prompts / generated / QA are already represented by flow_segments.
        flow_total = con.execute("""
            SELECT COUNT(fs.id) c
            FROM flow_segments fs
            JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id
            WHERE h.recipient_id=?
        """, (recipient_id,)).fetchone()["c"] or 0

        prompt_ready = con.execute("""
            SELECT COUNT(fs.id) c
            FROM flow_segments fs
            JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id
            WHERE h.recipient_id=?
              AND TRIM(COALESCE(fs.prompt,''))<>''
        """, (recipient_id,)).fetchone()["c"] or 0

        generated = con.execute("""
            SELECT COUNT(fs.id) c
            FROM flow_segments fs
            JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id
            WHERE h.recipient_id=?
              AND fs.status IN ('已生成','已完成','质检通过')
        """, (recipient_id,)).fetchone()["c"] or 0

        qa_passed = con.execute("""
            SELECT COUNT(fs.id) c
            FROM flow_segments fs
            JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id
            WHERE h.recipient_id=?
              AND fs.status='质检通过'
        """, (recipient_id,)).fetchone()["c"] or 0

        # Overall workflow weights:
        # 资料准备 20% / GPT 20% / Flow生成 35% / 质检 10% / DaVinci 10% / 上传 5%
        # 当前后两阶段尚未接入数据库，所以不会虚假显示完成。
        prep_ratio = ((chinese + foreign + images) / (total * 3)) if total else 0
        prompt_ratio = (prompt_ready / flow_total) if flow_total else 0
        generated_ratio = (generated / flow_total) if flow_total else 0
        qa_ratio = (qa_passed / flow_total) if flow_total else 0

        overall = round(
            min(prep_ratio, 1) * 20 +
            min(prompt_ratio, 1) * 20 +
            min(generated_ratio, 1) * 35 +
            min(qa_ratio, 1) * 10
        )

        return {
            "recipient": recipient,
            "hosts": hosts,
            "total": total,
            "chinese": chinese,
            "foreign": foreign,
            "images": images,
            "ready": fully_prepared,
            "flow_segments": int(flow_total),
            "prompt_ready": int(prompt_ready),
            "generated": int(generated),
            "qa_passed": int(qa_passed),
            "overall_progress": int(overall),
        }


def global_dashboard(*, work_date=None):
    with read_connection(work_date) as con:
        recipients = int((con.execute("SELECT COUNT(*) c FROM recipients").fetchone()["c"] or 0))
        hosts = int((con.execute("SELECT COUNT(*) c FROM hosts").fetchone()["c"] or 0))
        videos = int((con.execute("SELECT COUNT(*) c FROM videos").fetchone()["c"] or 0))

        chinese = int((con.execute("""
            SELECT COUNT(*) c FROM videos WHERE TRIM(COALESCE(chinese_script,''))<>''
        """).fetchone()["c"] or 0))
        foreign = int((con.execute("""
            SELECT COUNT(*) c FROM videos WHERE TRIM(COALESCE(script,''))<>''
        """).fetchone()["c"] or 0))
        images = int((con.execute("""
            SELECT COUNT(*) c FROM videos WHERE TRIM(COALESCE(image_path,''))<>''
        """).fetchone()["c"] or 0))
        ready = int((con.execute("""
            SELECT COUNT(*) c FROM videos
            WHERE TRIM(COALESCE(chinese_script,''))<>''
              AND TRIM(COALESCE(script,''))<>''
              AND TRIM(COALESCE(image_path,''))<>''
        """).fetchone()["c"] or 0))

        flow_total = int((con.execute("SELECT COUNT(*) c FROM flow_segments").fetchone()["c"] or 0))
        prompt_ready = int((con.execute("""
            SELECT COUNT(*) c FROM flow_segments
            WHERE TRIM(COALESCE(prompt,''))<>''
        """).fetchone()["c"] or 0))
        generated = int((con.execute("""
            SELECT COUNT(*) c FROM flow_segments
            WHERE status IN ('已生成','已完成','质检通过')
        """).fetchone()["c"] or 0))
        qa_passed = int((con.execute("""
            SELECT COUNT(*) c FROM flow_segments WHERE status='质检通过'
        """).fetchone()["c"] or 0))

        prep_ratio = ((chinese + foreign + images) / (videos * 3)) if videos else 0
        prompt_ratio = (prompt_ready / flow_total) if flow_total else 0
        generated_ratio = (generated / flow_total) if flow_total else 0
        qa_ratio = (qa_passed / flow_total) if flow_total else 0

        overall = round(
            min(prep_ratio, 1) * 20 +
            min(prompt_ratio, 1) * 20 +
            min(generated_ratio, 1) * 35 +
            min(qa_ratio, 1) * 10
        )

        return {
            "recipients": recipients,
            "hosts": hosts,
            "videos": videos,
            "ready": ready,
            "flow_segments": flow_total,
            "prompt_ready": prompt_ready,
            "generated": generated,
            "qa_passed": qa_passed,
            "overall_progress": int(overall),
        }



def sync_flow_segments(video_id, lines, *, edit_unstarted=False, manual_lock=False, timing_meta=None):
    """Merge by durable video/clip sequence. Never replace existing production clips.

    ``manual_lock`` is used only when the user explicitly edits segmentation.  Automatic
    preparation refuses to overwrite such segments.  Timing metadata is advisory and is
    written only together with an otherwise-safe text edit/insert.
    """
    clean = [x.strip() for x in lines if x.strip()]
    if timing_meta is not None and len(timing_meta) != len(clean):
        raise ValueError("时长元数据与片段数量不一致")

    def meta_for(seq, line):
        if timing_meta is not None:
            m = timing_meta[seq - 1] or {}
        else:
            from app.services.speech_preparation import timing_metadata
            m = timing_metadata(line)
        return (
            float(m.get("estimated_speech_duration") or m.get("estimated_speech_seconds") or 0),
            int(m.get("flow_duration_seconds") or m.get("duration") or 0),
            str(m.get("timing_status") or ""),
        )

    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        if edit_unstarted:
            rows=con.execute("SELECT * FROM flow_segments WHERE video_id=?",(video_id,)).fetchall()
            for row in rows:
                if row['prompt'] or row['generation_command'] or row['flow_output_path'] or row['status']!='待处理' or row['qc_status']!='待质检':
                    return False
                if not manual_lock and int(row['manual_text_lock'] or 0):
                    return False
                for table in ('flow_outputs','flow_redo','flow_recovery','flow_dispatches'):
                    if con.execute('SELECT 1 FROM '+table+' WHERE segment_id=?',(row['id'],)).fetchone():return False
            for seq,line in enumerate(clean,1):
                est,dur,tstatus=meta_for(seq,line)
                con.execute("""UPDATE flow_segments SET foreign_text=?,estimated_speech_duration=?,flow_duration_seconds=?,timing_status=?,manual_text_lock=?
                               WHERE video_id=? AND seg_seq=?""",
                            (line,est,dur,tstatus,1 if manual_lock else 0,video_id,seq))
            con.execute("DELETE FROM flow_segments WHERE video_id=? AND seg_seq>?",(video_id,len(clean)))
        for seq, line in enumerate(clean, 1):
            old = con.execute("SELECT id FROM flow_segments WHERE video_id=? AND seg_seq=?", (video_id,seq)).fetchone()
            if old is None:
                est,dur,tstatus=meta_for(seq,line)
                con.execute("""INSERT INTO flow_segments(video_id,seg_seq,foreign_text,estimated_speech_duration,flow_duration_seconds,timing_status,manual_text_lock)
                               VALUES(?,?,?,?,?,?,?)""",
                            (video_id,seq,line,est,dur,tstatus,1 if manual_lock else 0))
    return True


def get_flow_segment_text(video_id):
    with connect() as con:
        rows = con.execute("""
            SELECT foreign_text
            FROM flow_segments
            WHERE video_id=?
            ORDER BY seg_seq
        """, (video_id,)).fetchall()
        return "\n".join(r["foreign_text"] for r in rows if (r["foreign_text"] or "").strip())

def count_flow_segments_for_recipient(recipient_id):
    with connect() as con:
        row = con.execute("""
            SELECT COUNT(fs.id) AS c
            FROM flow_segments fs
            JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id
            WHERE h.recipient_id=?
        """, (recipient_id,)).fetchone()
        return int(row["c"] or 0)



def get_setting(key, default=""):
    with connect() as con:
        row = con.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

def set_setting(key, value):
    with connect() as con:
        con.execute("""
            INSERT INTO app_settings(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))


def set_video_prompt_template_snapshot(video_id, template_text):
    with connect() as con:
        con.execute("UPDATE videos SET prompt_template_snapshot=? WHERE id=?", (template_text or "", int(video_id)))

def set_video_performance_mode(video_id, mode):
    mode = "PRAYING" if str(mode or "").upper() == "PRAYING" else "TALKING"
    with connect() as con:
        con.execute("UPDATE videos SET performance_mode=? WHERE id=?", (mode, int(video_id)))

def set_host_prompt_rule(host_id, rule):
    with connect() as con:
        con.execute("UPDATE hosts SET prompt_rule=? WHERE id=?", (rule or "", host_id))

def set_video_special_requirements(video_id, requirements):
    with connect() as con:
        con.execute(
            "UPDATE videos SET special_requirements=? WHERE id=?",
            (requirements or "", video_id)
        )

def apply_video_rule_to_host(host_id, requirements):
    with connect() as con:
        con.execute(
            "UPDATE videos SET special_requirements=? WHERE host_id=?",
            (requirements or "", host_id)
        )

def update_segment_rule(segment_id, rule):
    with connect() as con:
        con.execute("UPDATE flow_segments SET segment_rule=? WHERE id=?", (rule or "", segment_id))

def ensure_flow_segments_for_host(host_id):
    with read_connection() as rcon:
        videos = rcon.execute("""
            SELECT v.* FROM videos v
            LEFT JOIN flow_segments fs ON fs.video_id = v.id
            WHERE v.host_id = ?
            GROUP BY v.id
            HAVING COUNT(fs.id) = 0
            ORDER BY v.seq
        """, (host_id,)).fetchall()
    if not videos:
        return
    try:
        max_chars = int(get_setting("default_wrap", "0") or 0)
    except (TypeError, ValueError):
        max_chars = 0
    from app.services.reflow_rules import prepare_configured_speech as prepare_swahili_speech
    with connect() as con:
        for v in videos:
            count = con.execute(
                "SELECT COUNT(*) c FROM flow_segments WHERE video_id=?", (v["id"],)
            ).fetchone()["c"]
            if count:
                continue
            source = (v["original_script"] or v["script"] or "").replace("\r\n", "\n").replace("\r", "\n")
            if not source.strip():
                continue
            prepared = prepare_swahili_speech(source, max_chars=max_chars or None)
            if not prepared.integrity_ok:
                # Never silently create altered dialogue.  Keep the exact current text as one
                # segment and let the duration gate request manual handling if necessary.
                lines = [source.strip()]
                meta = [{"estimated_speech_duration": 0, "flow_duration_seconds": 8, "timing_status": "INTEGRITY_FAILED"}]
                spoken = source.strip()
            else:
                lines = list(prepared.segments)
                meta = list(prepared.timings)
                spoken = prepared.spoken_text
            con.execute("""UPDATE videos SET original_script=CASE WHEN TRIM(COALESCE(original_script,''))='' THEN ? ELSE original_script END,
                           production_script=?,script=? WHERE id=?""",
                        (source, spoken, spoken, int(v["id"])))
            for i, line in enumerate(lines, 1):
                m=meta[i-1] if i-1<len(meta) else {}
                con.execute("""INSERT INTO flow_segments(video_id,seg_seq,foreign_text,estimated_speech_duration,flow_duration_seconds,timing_status)
                               VALUES(?,?,?,?,?,?)""",
                            (v["id"],i,line,float(m.get('estimated_speech_duration') or m.get('estimated_speech_seconds') or 0),
                             int(m.get('flow_duration_seconds') or m.get('duration') or 8),
                             str(m.get('timing_status') or prepared.timing_status if prepared.integrity_ok else 'INTEGRITY_FAILED')))


def prompt_global_stats(*, work_date=None):
    with read_connection(work_date) as con:
        row = con.execute("""
            SELECT
                (SELECT COUNT(h.id) FROM hosts h JOIN recipients r ON r.id = h.recipient_id) AS all_hosts,
                COUNT(fs.id) AS total_tasks,
                SUM(CASE WHEN TRIM(COALESCE(fs.prompt, '')) = '' AND COALESCE(fs.status, '') <> '失败' THEN 1 ELSE 0 END) AS pending_all,
                SUM(CASE WHEN TRIM(COALESCE(fs.prompt, '')) <> '' THEN 1 ELSE 0 END) AS generated_all,
                SUM(CASE WHEN COALESCE(fs.status, '') = '失败' THEN 1 ELSE 0 END) AS failed_all
            FROM flow_segments fs
            JOIN videos v ON v.id = fs.video_id
            JOIN hosts h ON h.id = v.host_id
            JOIN recipients r ON r.id = h.recipient_id
        """).fetchone()
    hosts_val = int(row["all_hosts"] or 0) if row else 0
    pending_val = int(row["pending_all"] or 0) if row else 0
    generated_val = int(row["generated_all"] or 0) if row else 0
    failed_val = int(row["failed_all"] or 0) if row else 0
    return {
        "hosts": hosts_val,
        "pending": pending_val,
        "generated": generated_val,
        "failed": failed_val,
        "all_hosts": hosts_val,
        "pending_all": pending_val,
        "generated_all": generated_val,
        "failed_all": failed_val,
    }


def list_prompt_tasks(recipient_id=None, host_id=None, status_filter="全部", *, work_date=None):
    where = []
    args = []
    if recipient_id:
        where.append("r.id=?")
        args.append(recipient_id)
    if host_id:
        where.append("h.id=?")
        args.append(host_id)

    if status_filter == "未生成":
        where.append("TRIM(COALESCE(fs.prompt,''))=''")
    elif status_filter == "已生成":
        where.append("TRIM(COALESCE(fs.prompt,''))<>''")
    elif status_filter == "失败":
        where.append("fs.status='失败'")
    elif status_filter == "已自定义":
        where.append("TRIM(COALESCE(v.special_requirements,''))<>''")

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT
            fs.id segment_id, fs.seg_seq, fs.foreign_text, fs.prompt,
            COALESCE(fs.generation_mode,'FRAME') generation_mode, COALESCE(fs.video_model,'') video_model,
            COALESCE(fs.flow_duration_seconds,8) flow_duration_seconds,
            fs.ai_original_prompt, fs.segment_rule, fs.status, fs.model,
            fs.input_tokens, fs.cached_tokens, fs.output_tokens, fs.cost_usd,
            COALESCE(fs.prompt_review_status,'待检查') prompt_review_status, COALESCE(fs.prompt_submitted_at,'') prompt_submitted_at,
            v.id video_id, v.seq video_seq, v.chinese_script,
            v.image_path, v.special_requirements, v.performance_mode, v.prompt_template_snapshot,
            h.id host_id, h.name host_name, h.prompt_rule,
            r.id recipient_id, r.name recipient_name
        FROM flow_segments fs
        JOIN videos v ON v.id=fs.video_id
        JOIN hosts h ON h.id=v.host_id
        JOIN recipients r ON r.id=h.recipient_id
        {clause}
        ORDER BY r.id DESC, h.id, v.seq, fs.seg_seq
    """
    with read_connection(work_date) as con:
        from app.services.performance_types import apply_choices
        return apply_choices(con,con.execute(sql, args).fetchall())


def get_prompt_task(segment_id):
    rows = get_prompt_tasks_by_ids([segment_id])
    return rows[0] if rows else None


def get_prompt_tasks_by_ids(segment_ids):
    clean_ids = [int(sid) for sid in (segment_ids or []) if sid is not None]
    if not clean_ids:
        return []
    with connect() as con:
        rows_out = []
        # SQLite parameter chunking (max 500 per IN clause)
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            placeholders = ",".join("?" for _ in chunk)
            fetched = con.execute(f"""
                SELECT
                    fs.id segment_id, fs.seg_seq, fs.foreign_text, fs.prompt,
                    COALESCE(fs.generation_mode,'FRAME') generation_mode, COALESCE(fs.video_model,'') video_model,
                    COALESCE(fs.flow_duration_seconds,8) flow_duration_seconds,
                    fs.ai_original_prompt, fs.segment_rule, fs.status, fs.model,
                    fs.input_tokens, fs.cached_tokens, fs.output_tokens, fs.cost_usd,
                    COALESCE(fs.prompt_review_status,'待检查') prompt_review_status, COALESCE(fs.prompt_submitted_at,'') prompt_submitted_at,
                    v.id video_id, v.seq video_seq, v.chinese_script,
                    v.image_path, v.special_requirements, v.performance_mode, v.prompt_template_snapshot,
                    h.id host_id, h.name host_name, h.prompt_rule,
                    r.id recipient_id, r.name recipient_name
                FROM flow_segments fs
                JOIN videos v ON v.id=fs.video_id
                JOIN hosts h ON h.id=v.host_id
                JOIN recipients r ON r.id=h.recipient_id
                WHERE fs.id IN ({placeholders})
            """, chunk).fetchall()
            rows_out.extend(fetched)
        if not rows_out:
            return []
        from app.services.performance_types import apply_choices
        enriched = apply_choices(con, rows_out)
        by_id = {int(r["segment_id"]): r for r in enriched}
        return [by_id[sid] for sid in clean_ids if sid in by_id]

def save_prompt_result(segment_id, original_prompt, final_prompt, status, model,
                       input_tokens=0, cached_tokens=0, output_tokens=0, cost_usd=0.0):
    with connect() as con:
        con.execute("""
            UPDATE flow_segments
            SET ai_original_prompt=?, prompt=?, status=?, model=?,
                input_tokens=?, cached_tokens=?, output_tokens=?, cost_usd=?,
                prompt_review_status=CASE WHEN ?='已生成' THEN '待检查' ELSE prompt_review_status END
            WHERE id=?
        """, (
            original_prompt or "", final_prompt or "", status, model,
            int(input_tokens or 0), int(cached_tokens or 0), int(output_tokens or 0),
            float(cost_usd or 0), status, segment_id
        ))
        con.execute("""
            INSERT INTO api_usage_log(
                flow_segment_id,model,input_tokens,cached_tokens,output_tokens,cost_usd
            ) VALUES(?,?,?,?,?,?)
        """, (
            segment_id, model, int(input_tokens or 0), int(cached_tokens or 0),
            int(output_tokens or 0), float(cost_usd or 0)
        ))

def mark_prompt_failed(segment_id, model):
    with connect() as con:
        con.execute(
            "UPDATE flow_segments SET status='失败', model=? WHERE id=?",
            (model, segment_id)
        )

def prompt_usage_summary(*, work_date=None):
    with read_connection(work_date) as con:
        row = con.execute("""
            SELECT
                COALESCE(SUM(input_tokens),0) input_tokens,
                COALESCE(SUM(cached_tokens),0) cached_tokens,
                COALESCE(SUM(output_tokens),0) output_tokens,
                COALESCE(SUM(cost_usd),0) cost_usd
            FROM api_usage_log
        """).fetchone()
        return dict(row)



def create_broll_plan_segments(video_id, broll_plan, model):
    if not broll_plan:
        return
    with connect() as con:
        row = con.execute("SELECT MAX(seg_seq) as m FROM flow_segments WHERE video_id=?", (video_id,)).fetchone()
        next_seq = (int(row['m']) if row and row['m'] is not None else 0) + 1
        if next_seq < 2000:
            next_seq = 2000
            
        for plan in broll_plan:
            broll_id = str(plan.get("BROLL_ID") or "")
            segment_id = str(plan.get("SEGMENT_ID") or "")
            prompt = str(plan.get("IMAGE_PROMPT") or "").strip()
            if not prompt: continue
            
            foreign_text = f"[B-roll] {broll_id} for {segment_id}"
            
            existing = con.execute("SELECT id FROM flow_segments WHERE video_id=? AND foreign_text=?", (video_id, foreign_text)).fetchone()
            if existing:
                con.execute("UPDATE flow_segments SET prompt=?, ai_original_prompt=?, prompt_review_status='待检查' WHERE id=?", 
                            (prompt, prompt, existing['id']))
            else:
                con.execute("""
                    INSERT INTO flow_segments (
                        video_id, seg_seq, foreign_text, prompt, ai_original_prompt,
                        generation_mode, model, status, prompt_review_status
                    ) VALUES (?, ?, ?, ?, ?, 'FRAME', ?, '待处理', '待检查')
                """, (video_id, next_seq, foreign_text, prompt, prompt, model))
                next_seq += 1

def create_image_plan_segments(video_id, image_plan, model):
    import re
    with connect() as con:
        for item in image_plan or []:
            shot=str(item.get('SHOT_ID') or '')
            if not re.fullmatch(r'SHOT_[0-9]+',shot):raise ValueError('INVALID_AUX_SHOT_ID')
            text='[辅助图] '+shot+': '+str(item.get('PURPOSE') or '')
            prompt=str(item.get('IMAGE_PROMPT') or '')
            old=con.execute("SELECT id FROM flow_segments WHERE video_id=? AND foreign_text LIKE ?",(video_id,'[辅助图] '+shot+':%')).fetchone()
            if old:
                con.execute("UPDATE flow_segments SET foreign_text=?,prompt=?,ai_original_prompt=?,prompt_review_status='待检查' WHERE id=?",(text,prompt,prompt,old['id']))
            else:
                seq=max(1000,con.execute('SELECT COALESCE(MAX(seg_seq),0)+1 FROM flow_segments WHERE video_id=?',(video_id,)).fetchone()[0])
                con.execute("INSERT INTO flow_segments(video_id,seg_seq,foreign_text,prompt,ai_original_prompt,generation_mode,model,status,prompt_review_status) VALUES(?,?,?,?,?,'FRAME',?,'待处理','待检查')",(video_id,seq,text,prompt,prompt,model))
            con.execute("INSERT OR IGNORE INTO asset_jobs(video_id,source_url,job_type,job_id,status) VALUES(?,?,'CAMERA_AUX_IMAGE',?,'PLANNED')",(video_id,'camera_aux:'+shot,shot))


def save_prompt_batch_results(segment_prompt_map, model, input_tokens=0,
                              cached_tokens=0, output_tokens=0, cost_usd=0.0,
                              original_prompt_map=None):
    """
    Save one image-level API response across multiple Flow segments.
    Usage/cost is apportioned so the per-row values sum to the real request total.
    """
    items = list(segment_prompt_map.items())
    if not items:
        return

    n = len(items)

    def split_int(total):
        total = int(total or 0)
        base, rem = divmod(total, n)
        return [base + (1 if i < rem else 0) for i in range(n)]

    input_parts = split_int(input_tokens)
    cache_parts = split_int(cached_tokens)
    output_parts = split_int(output_tokens)

    total_cost = float(cost_usd or 0.0)
    base_cost = total_cost / n
    cost_parts = [base_cost] * n
    # Force floating sum to the exact request cost on the last item.
    if n:
        cost_parts[-1] = total_cost - sum(cost_parts[:-1])

    with connect() as con:
        originals = {int(k): str(v or '') for k, v in dict(original_prompt_map or {}).items()}
        for i, (segment_id, prompt) in enumerate(items):
            sid = int(segment_id)
            original = originals.get(sid, prompt)
            con.execute("""
                UPDATE flow_segments
                SET ai_original_prompt=?, prompt=?, status='已生成', model=?,
                    input_tokens=?, cached_tokens=?, output_tokens=?, cost_usd=?, prompt_review_status='待检查'
                WHERE id=?
            """, (
                original, prompt, model,
                input_parts[i], cache_parts[i], output_parts[i], cost_parts[i],
                sid,
            ))

        # One usage-log row per actual API request, so API累计 never multiplies
        # the same image-level request by the number of returned segments.
        first_sid = int(items[0][0])
        con.execute("""
            INSERT INTO api_usage_log(
                flow_segment_id,model,input_tokens,cached_tokens,output_tokens,cost_usd
            ) VALUES(?,?,?,?,?,?)
        """, (
            first_sid, model, int(input_tokens or 0), int(cached_tokens or 0),
            int(output_tokens or 0), total_cost,
        ))

def prompt_usage_breakdown(*, work_date=None):
    with read_connection(work_date) as con:
        row = con.execute("""
            SELECT
                COALESCE(SUM(input_tokens),0) input_tokens,
                COALESCE(SUM(cached_tokens),0) cached_tokens,
                COALESCE(SUM(output_tokens),0) output_tokens,
                COALESCE(SUM(cost_usd),0) cost_usd,
                COUNT(*) request_count
            FROM api_usage_log
        """).fetchone()
        return dict(row)


def daily_api_usage_breakdown(day: str | None = None):
    """Exact GPT API usage & cost incurred on a local calendar day (YYYY-MM-DD)."""
    target_day = str(day or _time.strftime("%Y-%m-%d")).strip()
    with read_connection() as con:
        row = con.execute("""
            SELECT
                COALESCE(SUM(input_tokens), 0) input_tokens,
                COALESCE(SUM(cached_tokens), 0) cached_tokens,
                COALESCE(SUM(output_tokens), 0) output_tokens,
                COALESCE(SUM(cost_usd), 0) cost_usd,
                COUNT(*) request_count
            FROM api_usage_log
            WHERE date(created_at, 'localtime') = ?
        """, (target_day,)).fetchone()
        return {"day": target_day, **dict(row)}





def list_flow_tasks(recipient_id=None, host_id=None, status_filter="全部", *, work_date=None):
    where = ["TRIM(COALESCE(fs.prompt,''))<>''", "COALESCE(fs.prompt_review_status,'待检查')='已提交'"]
    args = []

    if recipient_id:
        where.append("r.id=?")
        args.append(recipient_id)
    if host_id:
        where.append("h.id=?")
        args.append(host_id)

    if status_filter != "全部":
        where.append("COALESCE(NULLIF(fs.flow_status,''),'待生成')=?")
        args.append(status_filter)

    clause = " WHERE " + " AND ".join(where)

    sql = f"""
        SELECT
            fs.id segment_id, fs.seg_seq, fs.foreign_text, fs.prompt,
            COALESCE(fs.generation_mode,'FRAME') generation_mode, COALESCE(fs.video_model,'') video_model,
            COALESCE(fs.flow_duration_seconds,8) flow_duration_seconds,
            fs.flow_status, fs.flow_output_path, COALESCE(fs.flow_output_url,'') flow_output_url, fs.flow_error,
            CASE 
                WHEN fs.seg_seq >= 1000 AND (fs.foreign_text LIKE '[辅助图] %' OR fs.foreign_text LIKE '%[LEGACY_AUX]%') THEN 'CAMERA_AUX_IMAGE'
                WHEN fs.seg_seq >= 1000 AND fs.foreign_text LIKE '%[B-roll]%' THEN 'BROLL_IMAGE'
                ELSE 'VIDEO'
            END AS TASK_TYPE,
            fs.flow_attempts, fs.flow_submitted_at, fs.flow_completed_at,
            COALESCE(fs.prompt_review_status,'待检查') prompt_review_status,
            COALESCE(fs.generation_command,'') generation_command,
            COALESCE(fs.flow_channel_key,'') flow_channel_key, COALESCE(fs.flow_retry_count,0) flow_retry_count,
            v.id video_id, v.seq video_seq, v.image_path, v.performance_mode, '' prompt_template_snapshot,
            h.id host_id, h.name host_name,
            r.id recipient_id, r.name recipient_name
        FROM flow_segments fs
        JOIN videos v ON v.id=fs.video_id
        JOIN hosts h ON h.id=v.host_id
        JOIN recipients r ON r.id=h.recipient_id
        {clause}
        ORDER BY r.id DESC, h.id, v.seq, fs.seg_seq
    """
    with read_connection(work_date) as con:
        from app.services.performance_types import apply_choices
        return apply_choices(con, con.execute(sql, args).fetchall())


def count_waiting_flow_submissions(work_date=None):
    """Count videos waiting to be submitted. Same filter as the account-page plan, without loading every row."""
    sql = """
        SELECT COUNT(*) AS c
        FROM flow_segments fs
        JOIN videos v ON v.id = fs.video_id
        WHERE TRIM(COALESCE(fs.prompt,'')) <> ''
          AND COALESCE(fs.prompt_review_status,'待检查') = '已提交'
          AND COALESCE(fs.generation_command,'') = ''
          AND COALESCE(NULLIF(fs.flow_status,''),'待生成') IN ('待生成', '已准备')
    """
    with read_connection(work_date) as con:
        row = con.execute(sql).fetchone()
    return int(row["c"] or 0) if row else 0



def set_flow_task_status(segment_id, status, error=""):
    with connect() as con:
        if status == "已提交":
            con.execute("""
                UPDATE flow_segments
                SET flow_status=?, flow_error='', flow_attempts=flow_attempts+1,
                    flow_submitted_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (status, segment_id))
        elif status == "已完成":
            con.execute("""
                UPDATE flow_segments
                SET flow_status=?, flow_error='', flow_completed_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (status, segment_id))
        elif status == "失败":
            con.execute("""
                UPDATE flow_segments SET flow_status=?, flow_error=? WHERE id=?
            """, (status, error or "", segment_id))
        else:
            con.execute("""
                UPDATE flow_segments SET flow_status=?, flow_error=? WHERE id=?
            """, (status, error or "", segment_id))


def reset_flow_tasks(segment_ids):
    ids = [int(x) for x in segment_ids]
    if not ids:
        return
    q = ",".join("?" for _ in ids)
    with connect() as con:
        con.execute(f"""
            UPDATE flow_segments
            SET flow_status='待生成', flow_error='', flow_output_path='',
                flow_submitted_at='', flow_completed_at=''
            WHERE id IN ({q})
        """, ids)


def save_flow_output(segment_id, output_path):
    with connect() as con:
        con.execute("""
            UPDATE flow_segments
            SET flow_status='已完成', flow_output_path=?, flow_error='',
                flow_completed_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (output_path or "", segment_id))


def count_flow_task_status(recipient_id=None, host_id=None, *, work_date=None):
    where = ["TRIM(COALESCE(fs.prompt,''))<>''"]
    args = []
    joins = """
        FROM flow_segments fs
        JOIN videos v ON v.id=fs.video_id
        JOIN hosts h ON h.id=v.host_id
        JOIN recipients r ON r.id=h.recipient_id
    """
    if recipient_id:
        where.append("r.id=?")
        args.append(recipient_id)
    if host_id:
        where.append("h.id=?")
        args.append(host_id)
    clause = " WHERE " + " AND ".join(where)

    with read_connection(work_date) as con:
        rows = con.execute(
            f"""SELECT COALESCE(NULLIF(fs.flow_status,''),'待生成') s, COUNT(*) c
                {joins} {clause}
                GROUP BY COALESCE(NULLIF(fs.flow_status,''),'待生成')""",
            args
        ).fetchall()
        counts = {row["s"]: int(row["c"] or 0) for row in rows}
        total = sum(counts.values())
        # “已提交 / 生成中”是运行态，不可信任 flow_segments 的历史状态单独计数。
        # 只有当前 generation_command 仍有 submitted dispatch 的片段才属于实时运行任务。
        live_rows = con.execute(
            f"""SELECT COALESCE(NULLIF(fs.flow_status,''),'待生成') s, COUNT(DISTINCT fs.id) c
                {joins} {clause}
                AND fs.flow_status IN ('已提交','生成中')
                AND EXISTS (SELECT 1 FROM flow_dispatches d
                            WHERE d.segment_id=fs.id
                              AND d.command_id=fs.generation_command
                              AND d.status='submitted'
                              AND datetime(COALESCE(NULLIF(d.submitted_at,''),NULLIF(d.detected_at,''),d.created_at))
                                    >= datetime('now','-30 minutes'))
                GROUP BY COALESCE(NULLIF(fs.flow_status,''),'待生成')""",
            args
        ).fetchall()
        live_counts={row['s']:int(row['c'] or 0) for row in live_rows}
        return {
            "total": total,
            "pending": counts.get("待生成", 0),
            "prepared": counts.get("已准备", 0),
            "submitted": live_counts.get("已提交", 0),
            "running": live_counts.get("生成中", 0),
            "done": counts.get("已完成", 0),
            "failed": counts.get("失败", 0)+counts.get("下载失败", 0),
            "downloading": counts.get("下载中", 0),
        }



def set_recipient_flow_project_name(recipient_id, name):
    with connect() as con:
        con.execute(
            "UPDATE recipients SET flow_project_name=? WHERE id=?",
            (name or "", recipient_id)
        )

def set_host_flow_collection(host_id, name):
    with connect() as con:
        con.execute(
            "UPDATE hosts SET flow_collection_name=? WHERE id=?",
            (name or "", host_id)
        )

def set_host_flow_prep(host_id, status, uploaded=None, total=None,
                       window_key=None, refreshed=False):
    fields = ["flow_prep_status=?"]
    args = [status]
    if uploaded is not None:
        fields.append("flow_images_uploaded=?")
        args.append(int(uploaded))
    if total is not None:
        fields.append("flow_images_total=?")
        args.append(int(total))
    if window_key is not None:
        fields.append("flow_window_key=?")
        args.append(window_key or "")
    if refreshed:
        fields.append("flow_last_refresh_at=CURRENT_TIMESTAMP")
    args.append(host_id)
    with connect() as con:
        con.execute(
            f"UPDATE hosts SET {', '.join(fields)} WHERE id=?",
            args
        )

def get_flow_prep_rows(recipient_id=None, *, work_date=None):
    where = []
    args = []
    if recipient_id:
        where.append("r.id=?")
        args.append(recipient_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT
            r.id recipient_id, r.name recipient_name, r.work_date,
            r.flow_project_name,
            h.id host_id, h.name host_name,
            h.flow_collection_name, h.flow_prep_status, h.flow_window_key,
            h.flow_images_uploaded, h.flow_images_total, h.flow_last_refresh_at,
            h.flow_upload_state, h.flow_upload_command_id, h.flow_upload_fingerprint,
            h.flow_upload_verified_at, h.flow_upload_error,
            COUNT(v.id) video_count,
            SUM(CASE WHEN TRIM(COALESCE(v.image_path,''))<>'' THEN 1 ELSE 0 END) image_count
        FROM hosts h
        JOIN recipients r ON r.id=h.recipient_id
        LEFT JOIN videos v ON v.host_id=h.id
        {clause}
        GROUP BY h.id
        ORDER BY r.id, h.id
    """
    with read_connection(work_date) as con:
        return con.execute(sql, args).fetchall()


def get_host_upload_runtime(host_id):
    with connect() as con:
        return con.execute("""
            SELECT id host_id, flow_prep_status, flow_images_uploaded, flow_images_total,
                   flow_upload_state, flow_upload_command_id, flow_upload_fingerprint,
                   flow_upload_verified_at, flow_upload_error
            FROM hosts WHERE id=?
        """, (host_id,)).fetchone()


def set_host_upload_runtime(host_id, state, *, command_id=None, fingerprint=None,
                            uploaded=None, total=None, status=None, error=None, verified=False):
    """Persist the upload workflow state. Only a final verified state should expose uploaded==total."""
    fields=["flow_upload_state=?"]
    args=[state or "idle"]
    if command_id is not None:
        fields.append("flow_upload_command_id=?")
        args.append(command_id or "")
    if fingerprint is not None:
        fields.append("flow_upload_fingerprint=?")
        args.append(fingerprint or "")
    if uploaded is not None:
        fields.append("flow_images_uploaded=?")
        args.append(int(uploaded))
    if total is not None:
        fields.append("flow_images_total=?")
        args.append(int(total))
    if status is not None:
        fields.append("flow_prep_status=?")
        args.append(status or "")
    if error is not None:
        fields.append("flow_upload_error=?")
        args.append(error or "")
    if state == "queued":
        fields.append("flow_upload_verified_at='' ")
    if verified:
        fields.append("flow_upload_verified_at=CURRENT_TIMESTAMP")
        if error is None:
            fields.append("flow_upload_error='' ")
    args.append(host_id)
    with connect() as con:
        con.execute(f"UPDATE hosts SET {', '.join(fields)} WHERE id=?", args)


def set_host_task_command(host_id, command_id):
    """Persist the one generation command allowed to mutate this host."""
    with connect() as con:
        con.execute("UPDATE hosts SET flow_task_command_id=? WHERE id=?", (command_id or "", int(host_id)))


def get_host_task_command(host_id):
    with connect() as con:
        row=con.execute("SELECT flow_task_command_id FROM hosts WHERE id=?", (int(host_id),)).fetchone()
    return str(row["flow_task_command_id"] or "") if row else ""


def get_host_images(host_id):
    with connect() as con:
        return con.execute("""
            SELECT id, seq, image_path
            FROM videos
            WHERE host_id=? AND TRIM(COALESCE(image_path,''))<>''
            ORDER BY seq
        """, (host_id,)).fetchall()


def set_host_flow_collection_url(host_id, url):
    url = (url or "").strip()
    with connect() as con:
        con.execute("""
            UPDATE hosts
            SET flow_images_uploaded=CASE WHEN COALESCE(flow_collection_url,'')<>? THEN 0 ELSE flow_images_uploaded END,
                flow_upload_state=CASE WHEN COALESCE(flow_collection_url,'')<>? THEN 'idle' ELSE flow_upload_state END,
                flow_upload_command_id=CASE WHEN COALESCE(flow_collection_url,'')<>? THEN '' ELSE flow_upload_command_id END,
                flow_upload_fingerprint=CASE WHEN COALESCE(flow_collection_url,'')<>? THEN '' ELSE flow_upload_fingerprint END,
                flow_upload_verified_at=CASE WHEN COALESCE(flow_collection_url,'')<>? THEN '' ELSE flow_upload_verified_at END,
                flow_upload_error=CASE WHEN COALESCE(flow_collection_url,'')<>? THEN '' ELSE flow_upload_error END,
                flow_task_command_id=CASE WHEN COALESCE(flow_collection_url,'')<>? THEN '' ELSE flow_task_command_id END,
                flow_collection_url=?,
                flow_link_status=CASE WHEN ?<>'' THEN '已绑定' ELSE '未绑定' END
            WHERE id=?
        """, (url, url, url, url, url, url, url, url, url, host_id))

def list_flow_host_links(recipient_id=None, *, work_date=None):
    where = []
    args = []
    if recipient_id:
        where.append("r.id=?")
        args.append(recipient_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with read_connection(work_date) as con:
        return con.execute(f"""
            SELECT
                h.id host_id, h.name host_name,
                h.flow_collection_url, h.flow_link_status,
                h.flow_prep_status, h.flow_images_uploaded, h.flow_images_total,
                h.flow_upload_state, h.flow_upload_command_id, h.flow_upload_fingerprint,
                h.flow_upload_verified_at, h.flow_upload_error, h.flow_task_command_id,
                r.id recipient_id, r.name recipient_name, r.work_date,
                COUNT(v.id) video_count,
                SUM(CASE WHEN TRIM(COALESCE(v.image_path,''))<>'' THEN 1 ELSE 0 END) image_count
            FROM hosts h
            JOIN recipients r ON r.id=h.recipient_id
            LEFT JOIN videos v ON v.host_id=h.id
            {clause}
            GROUP BY h.id
            ORDER BY r.id, h.id
        """, args).fetchall()



def save_manual_prompt_result(segment_id, prompt):
    """Save an inline edit without destroying the original API usage audit trail."""
    prompt = (prompt or "").strip()
    with connect() as con:
        con.execute("""
            UPDATE flow_segments
            SET prompt=?,
                status=CASE
                    WHEN ?='' THEN '待处理'
                    WHEN TRIM(COALESCE(ai_original_prompt,''))<>'' THEN '已修改'
                    ELSE '已自定义'
                END,
                model=CASE
                    WHEN ?<>'' AND TRIM(COALESCE(model,''))='' THEN '手动编辑'
                    ELSE model
                END,
                prompt_review_status=CASE WHEN ?<>'' THEN '待检查' ELSE '待检查' END
            WHERE id=?
        """, (prompt, prompt, prompt, prompt, int(segment_id)))
    return 1


def clear_prompt_results(segment_ids):
    """Clear prompt fields only before a task enters Flow; preserve every downstream row."""
    ids=[int(x) for x in segment_ids]
    if not ids:return 0
    q=','.join('?' for _ in ids)
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        for sid in ids:
            row=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
            if row and (row['generation_command'] or row['flow_output_path'] or row['qc_status']!='待质检'):
                raise ValueError('选中任务已进入生产流程，已阻止清空以保留下载、质检和剪辑记录。')
            for table in ('flow_outputs','flow_redo','flow_recovery','flow_dispatches'):
                if con.execute('SELECT 1 FROM '+table+' WHERE segment_id=?',(sid,)).fetchone():
                    raise ValueError('选中任务有关联的生产记录，不能清空提示词。')
        con.execute(f"UPDATE flow_segments SET ai_original_prompt='',prompt='',status='待处理',prompt_review_status='待检查',prompt_submitted_at='' WHERE id IN ({q})",ids)
    return len(ids)


def save_manual_prompt_results(segment_prompt_map):
    """Save manually pasted final prompts without API usage/cost records."""
    items = [(int(k), (v or "").strip()) for k, v in segment_prompt_map.items()]
    if not items:
        return 0
    with connect() as con:
        for segment_id, prompt in items:
            con.execute("""
                UPDATE flow_segments
                SET ai_original_prompt='',
                    prompt=?,
                    status='已自定义',
                    model='手动粘贴',
                    input_tokens=0,
                    cached_tokens=0,
                    output_tokens=0,
                    cost_usd=0,
                    prompt_review_status='待检查', prompt_submitted_at=''
                WHERE id=?
            """, (prompt, segment_id))
    return len(items)


def list_qc_segments(recipient_id=None, host_id=None, status_filter="全部", *, work_date=None):
    where = ["fs.flow_status='已完成'", "TRIM(fo.output_path)<>''", "COALESCE(v.edit_status,'')<>'已放弃'"]
    args = []
    if recipient_id:
        where.append("r.id=?")
        args.append(recipient_id)
    if host_id:
        where.append("h.id=?")
        args.append(host_id)
    if status_filter and status_filter != "全部":
        where.append("COALESCE(fo.qc_status,'待质检')=?")
        args.append(status_filter)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with read_connection(work_date) as con:
        return con.execute(f"""
            SELECT
                fs.id segment_id, fo.id output_id,
                r.id recipient_id, r.name recipient_name,
                h.id host_id, h.name host_name,
                v.id video_id, v.seq video_seq,
                v.chinese_script, v.script full_foreign_text,
                fs.seg_seq,
                fs.foreign_text,
                fs.prompt,
                fs.flow_status,
                fo.output_path flow_output_path,
                COALESCE(fo.qc_status,'待质检') qc_status,
                COALESCE(fs.qc_note,'') qc_note
            FROM flow_segments fs
            JOIN flow_outputs fo ON fo.segment_id=fs.id AND fo.command_id=fs.generation_command
            JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id
            JOIN recipients r ON r.id=h.recipient_id
            {clause}
            ORDER BY r.id DESC, h.id, v.seq, fs.seg_seq
        """, args).fetchall()


def set_segment_qc_status(segment_ids, status, note=""):
    from app.services.workflow import review
    return review(segment_ids, status, note)

def is_aux_image_segment(row):
    """遗留废弃数据伪片段：seg_seq>=1000 且 foreign_text 以 [LEGACY_AUX] 开头。"""
    try:
        return int(row['seg_seq']) >= 1000 and str(row['foreign_text'] or '').startswith('[LEGACY_AUX]')
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def _current_edit_segments(con, video_ids=None):
    # The selected path + generation command identify the current output; history never joins out.
    ids = list(video_ids or [])
    clause = ' WHERE fs.video_id IN (%s)' % ','.join('?' for _ in ids) if ids else ''
    rows = con.execute("""SELECT fs.*,
        EXISTS(SELECT 1 FROM flow_outputs fo WHERE fo.segment_id=fs.id
               AND fo.command_id=fs.generation_command AND fo.output_path=fs.flow_output_path
               AND fo.qc_status='通过') current_passed
        FROM flow_segments fs""" + clause, ids).fetchall()
    result = []
    from pathlib import Path
    for raw in rows:
        row = dict(raw)
        # 遗留废弃数据是图片伪片段（seg_seq>=1000），只用于生成视频的起止帧，不参与质检/剪辑。
        if is_aux_image_segment(row):
            continue
        path = str(row['flow_output_path'] or '').strip()
        row['download_valid'] = bool(row['generation_command'] and row['flow_status']=='已完成'
                                     and path and Path(path).expanduser().is_file())
        row['material_valid'] = row['download_valid'] and row['qc_status']=='通过' and bool(row['current_passed'])
        result.append(row)
    return result


def editing_stage(status, ready=None):
    if status == '已放弃':
        return 'ABANDONED'
    if status in ('待准备', '等待片段', '素材待齐', '需要画面处理', ''):
        return 'WAITING_MATERIAL'
    if status in ('等待剪辑', '待剪辑', '待导入DaVinci', 'AUTO_EDIT_PENDING'):
        return 'READY_TO_EDIT'
    if status in ('剪辑中', '自动剪辑中', '已导入DaVinci', 'AUTO_EDIT_PROCESSING'):
        return 'EDITING'
    if status in ('已剪辑', '待人工检查', 'AUTO_EDIT_DONE'):
        return 'REVIEW'
    if status in ('待导出', '导出中', 'EXPORTING'):
        return 'EXPORTING'
    if status in ('已导出', '已完成', 'COMPLETED'):
        return 'COMPLETED'
    return 'ERROR'


def list_edit_queue(recipient_id=None, host_id=None, *, work_date=None):
    where, args = ["COALESCE(v.edit_status,'')<>'已放弃'", "COALESCE(v.status,'')<>'已放弃'"], []
    if recipient_id:
        where.append('r.id=?'); args.append(recipient_id)
    if host_id:
        where.append('h.id=?'); args.append(host_id)
    clause = ' WHERE ' + ' AND '.join(where) if where else ''
    with read_connection(work_date) as con:
        rows = con.execute("""SELECT v.id video_id, r.id recipient_id, r.name recipient_name,
            h.id host_id,h.name host_name,v.seq video_seq,r.work_date,v.image_path,
            COALESCE(v.edit_status,'等待片段') edit_status,
            COALESCE(v.edit_output_path,'') edit_output_path
            FROM videos v JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            """ + clause + ' ORDER BY r.id DESC,h.id,v.seq', args).fetchall()
        segments = _current_edit_segments(con, [r['video_id'] for r in rows]) if rows else []
        ratio_by_host = {}
        if rows:
            try:
                for srow in con.execute(
                    "SELECT key, value FROM app_settings WHERE key LIKE 'host_aspect_ratio_%'"
                ).fetchall():
                    k = str(srow['key'] or '')
                    tail = k[len('host_aspect_ratio_'):]
                    if tail.isdigit() and str(srow['value'] or '').strip():
                        ratio_by_host[int(tail)] = normalize_aspect_ratio(srow['value'])
            except Exception:
                pass
            missing_hids = sorted({
                int(r['host_id']) for r in rows
                if r['host_id'] is not None and int(r['host_id']) not in ratio_by_host
            })
            if missing_hids:
                try:
                    marks = ','.join('?' for _ in missing_hids)
                    for hrow in con.execute(
                        f"SELECT id, flow_aspect_ratio FROM hosts WHERE id IN ({marks})",
                        missing_hids,
                    ).fetchall():
                        if str(hrow['flow_aspect_ratio'] or '').strip():
                            ratio_by_host[int(hrow['id'])] = normalize_aspect_ratio(hrow['flow_aspect_ratio'])
                except Exception:
                    pass
    grouped = {}
    for segment in segments:
        grouped.setdefault(segment['video_id'], []).append(segment)
    result = []
    for raw in rows:
        row = dict(raw)
        row['aspect_ratio'] = (
            ratio_by_host.get(int(row['host_id']), '9:16')
            if row.get('host_id') is not None else '9:16'
        )
        parts = grouped.get(row['video_id'], [])
        # 整条完整视频只要有任意有效片段被标记为「已放弃」，整条视频即作废，不进入自动剪辑队列。
        if parts and any(
            str(p.get('flow_status') or '') == '已放弃'
            or str(p.get('prompt_review_status') or '') == '已放弃'
            for p in parts
        ):
            continue
        materials_ready = row['edit_status'] not in ('待准备', '等待片段', '素材待齐', '需要画面处理', '')
        # 上游跳过未做（从未提交到 Flow）或已从 Flow 撤回排队的任务尚未进入生产管线，不计入「素材待齐」。
        if not materials_ready:
            entered_pipeline = bool(parts) and any(
                str(p.get('prompt_review_status') or '') == '已提交'
                or str(p.get('flow_status') or '') not in ('', '待生成', '已放弃')
                or bool(str(p.get('generation_command') or '').strip())
                or bool(p.get('download_valid'))
                or bool(p.get('material_valid'))
                for p in parts
            )
            if not entered_pipeline:
                continue
        row['segment_count'] = len(parts)
        row['completed_segments'] = sum(p['download_valid'] for p in parts)
        row['qc_passed'] = sum(p['material_valid'] for p in parts)
        row['waiting_reasons'] = {
            '返工中': sum(not p['material_valid'] and p['qc_status']=='退回' for p in parts),
            '等待质检': sum(p['download_valid'] and not p['material_valid'] and p['qc_status']!='退回' for p in parts),
            '生成失败': sum(not p['download_valid'] and p['qc_status']!='退回' and p['flow_status']=='失败' for p in parts),
            '等待生成 / 下载': sum(not p['download_valid'] and p['qc_status']!='退回' and p['flow_status']!='失败' for p in parts),
        }
        row['materials_ready'] = materials_ready
        row['editing_stage'] = editing_stage(row['edit_status'])
        result.append(row)
    return result



def editing_stats(rows):
    import logging
    from collections import Counter
    log = logging.getLogger(__name__)
    ids = Counter(r['video_id'] for r in rows)
    duplicates = {key: count for key, count in ids.items() if count > 1}
    unique = {r['video_id']: r for r in rows}
    counts = Counter(r['editing_stage'] for r in unique.values())
    if duplicates:
        log.warning('[EDITING_STATS_MISMATCH] visible=%d stats_total=%d duplicate_video_task_ids=%s',
                    len(rows), len(unique), duplicates)
    log.info('[EDITING_STATS] visible_unique_video_tasks=%d waiting_material=%d ready_to_edit=%d editing=%d completed=%d review=%d exporting=%d error=%d',
             len(unique), counts['WAITING_MATERIAL'], counts['READY_TO_EDIT'], counts['EDITING'],
             counts['COMPLETED'], counts['REVIEW'], counts['EXPORTING'], counts['ERROR'])
    return counts


def list_edit_source_segments(video_ids=None, *, reedit=False):
    """Only complete, current, downloaded, QC-passed videos awaiting submission."""
    requested = {int(x) for x in (video_ids or [])}
    ready = {r['video_id'] for r in list_edit_queue()
             if (r['editing_stage']=='READY_TO_EDIT' or (reedit and r['materials_ready'] and r['editing_stage'] not in ('EDITING','EXPORTING'))) and (not requested or r['video_id'] in requested)}
    if not ready:
        return []
    with connect() as con:
        parts = _current_edit_segments(con, sorted(ready))
        # Revalidate the entire video before exposing even one segment.
        invalid = {r['video_id'] for r in parts if not r['material_valid']}
        rows = con.execute("""SELECT fs.id segment_id,fs.seg_seq,fs.flow_output_path,
            v.id video_id,v.seq video_seq,h.id host_id,h.name host_name,
            r.id recipient_id,r.name recipient_name,r.work_date
            FROM flow_segments fs JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            WHERE NOT (fs.seg_seq>=1000 AND fs.foreign_text LIKE '[LEGACY_AUX]%')
            ORDER BY r.work_date,r.id,h.id,v.seq,fs.seg_seq""").fetchall()
    from pathlib import Path as _P
    # 剪辑协议只接受视频文件；遗留废弃数据永远不能进入。
    return [r for r in rows if r['video_id'] in ready - invalid
            and int(r['seg_seq'])<1000
            and _P(str(r['flow_output_path'] or '')).suffix.lower() in ('.mp4','.mov','.m4v','.webm')]



def rebind_flow_output_path(segment_id, old_path, new_path):
    """Update current segment and every matching output revision after a local file move."""
    with connect() as con:
        con.execute(
            "UPDATE flow_segments SET flow_output_path=? WHERE id=? AND flow_output_path=?",
            (new_path, int(segment_id), old_path),
        )
        con.execute(
            "UPDATE flow_outputs SET output_path=? WHERE segment_id=? AND output_path=?",
            (new_path, int(segment_id), old_path),
        )

def set_video_edit_status(video_ids, status):
    ids = [int(x) for x in video_ids]
    if not ids:
        return 0
    with connect() as con:
        con.executemany(
            "UPDATE videos SET edit_status=? WHERE id=?",
            [(status, vid) for vid in ids]
        )
        con.executemany("UPDATE editing_history SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=(SELECT MAX(id) FROM editing_history WHERE video_id=?)",[(status,vid) for vid in ids])
    return len(ids)

def list_upload_queue(recipient_id=None, host_id=None, *, work_date=None):
    where = []
    args = []
    if recipient_id:
        where.append("r.id=?")
        args.append(recipient_id)
    if host_id:
        where.append("h.id=?")
        args.append(host_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with read_connection(work_date) as con:
        return con.execute(f"""
            SELECT
                v.id video_id,
                r.name recipient_name,
                r.work_date work_date,
                h.name host_name,
                v.seq video_seq,
                COALESCE(v.edit_status,'等待片段') edit_status,
                COALESCE(v.edit_output_path,'') edit_output_path,
                COALESCE(v.upload_status,'未上传') upload_status,
                COALESCE(v.upload_target,'') upload_target,
                COALESCE(v.upload_url,'') upload_url
                ,COALESCE(v.upload_confirm_mode,'') upload_confirm_mode
                ,COALESCE(v.upload_confirmed_at,'') upload_confirmed_at
            FROM videos v
            JOIN hosts h ON h.id=v.host_id
            JOIN recipients r ON r.id=h.recipient_id
            {clause}
            ORDER BY r.id DESC, h.id, v.seq
        """, args).fetchall()


def set_video_upload_status(video_ids, status):
    ids = [int(x) for x in video_ids]
    if not ids:
        return 0
    with connect() as con:
        con.executemany(
            "UPDATE videos SET upload_status=? WHERE id=?",
            [(status, vid) for vid in ids]
        )
    return len(ids)

def manual_confirm_video_uploads(video_ids):
    """Mark selected exported videos as uploaded by explicit human confirmation.

    This does not invent Drive ids/URLs and only changes delivery state.
    """
    ids = sorted({int(x) for x in video_ids if int(x) > 0})
    if not ids:
        return 0
    now = _time.strftime("%Y-%m-%d %H:%M:%S")
    placeholders = ",".join("?" for _ in ids)
    with connect() as con:
        cur = con.execute(
            f"""UPDATE videos
                   SET upload_status='已上传',
                       upload_confirm_mode='manual',
                       upload_confirmed_at=?
                 WHERE id IN ({placeholders})
                   AND COALESCE(upload_status,'未上传') NOT IN ('已上传','已交付')""",
            [now, *ids],
        )
        return int(cur.rowcount or 0)


def cancel_manual_video_uploads(video_ids):
    """Undo only manual upload confirmations; never touches files or later workflow data."""
    ids = sorted({int(x) for x in video_ids if int(x) > 0})
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with connect() as con:
        cur = con.execute(
            f"""UPDATE videos
                   SET upload_status='未上传',
                       upload_confirm_mode='',
                       upload_confirmed_at=''
                 WHERE id IN ({placeholders})
                   AND COALESCE(upload_confirm_mode,'')='manual'
                   AND COALESCE(upload_status,'未上传')='已上传'""",
            ids,
        )
        return int(cur.rowcount or 0)


def get_dashboard_statistics(*, work_date=None):
    with read_connection(work_date) as con:
        row = con.execute("""
            SELECT
              (SELECT COUNT(*) FROM recipients) recipients,
              (SELECT COUNT(*) FROM hosts) hosts,
              (SELECT COUNT(*) FROM videos) videos,
              (SELECT COUNT(*) FROM flow_segments) segments,
              (SELECT COUNT(*) FROM flow_segments
                 WHERE flow_status='已完成' OR TRIM(COALESCE(flow_output_path,''))<>'' OR TRIM(COALESCE(flow_output_url,''))<>'') flow_completed,
              (SELECT COUNT(*) FROM flow_segments WHERE flow_status='失败') flow_failed,
              (SELECT COUNT(*) FROM flow_segments
                 WHERE COALESCE(qc_status,'待质检')='通过') qc_passed,
              (SELECT COUNT(*) FROM flow_segments
                 WHERE COALESCE(qc_status,'待质检')='退回') qc_rejected,
              (SELECT COUNT(*) FROM videos
                 WHERE COALESCE(edit_status,'等待片段') IN ('已剪辑','已导出')) edited,
              (SELECT COUNT(*) FROM videos
                 WHERE COALESCE(upload_status,'未上传')='已上传') uploaded,
              (SELECT COALESCE(SUM(cost_usd),0) FROM api_usage_log) api_cost
        """).fetchone()
        return row


# ---------------------------------------------------------------------------
# V0.12.5 downstream workflow helpers
# ---------------------------------------------------------------------------

def get_qc_segment(segment_id):
    with connect() as con:
        return con.execute("""
            SELECT
                fs.id segment_id, fs.seg_seq, fs.foreign_text, fs.prompt,
                fs.flow_status, fs.flow_output_path,
                COALESCE(fs.flow_output_url,'') flow_output_url,
                COALESCE(fs.flow_error,'') flow_error,
                COALESCE(fs.qc_status,'待质检') qc_status,
                COALESCE(fs.qc_note,'') qc_note,
                v.id video_id, v.seq video_seq, v.image_path,
                h.id host_id, h.name host_name,
                r.id recipient_id, r.name recipient_name
            FROM flow_segments fs
            JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id
            JOIN recipients r ON r.id=h.recipient_id
            WHERE fs.id=?
        """, (int(segment_id),)).fetchone()


def save_flow_output_url(segment_id, output_url):
    with connect() as con:
        con.execute("UPDATE flow_segments SET flow_output_url=? WHERE id=?", (output_url or "", int(segment_id)))


def set_video_edit_output(video_id, path, status="已导出"):
    with connect() as con:
        con.execute(
            "UPDATE videos SET edit_output_path=?, edit_status=? WHERE id=?",
            (path or "", status or "已导出", int(video_id))
        )

        con.execute("UPDATE editing_history SET status=?,output_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=(SELECT MAX(id) FROM editing_history WHERE video_id=?)",(status,path or '',int(video_id)))


def set_recipient_drive_folder(recipient_id, url):
    with connect() as con:
        con.execute("UPDATE recipients SET drive_folder_url=? WHERE id=?", (url or "", int(recipient_id)))


def set_video_drive_result(video_id, file_url="", folder_url="", status="已上传"):
    with connect() as con:
        con.execute("""
            UPDATE videos
            SET upload_status=?, upload_target='Google Drive', upload_url=?,
                drive_file_url=?, drive_folder_url=?
            WHERE id=?
        """, (status, file_url or folder_url or "", file_url or "", folder_url or "", int(video_id)))


def list_recipient_drive_links(*, work_date=None):
    with read_connection(work_date) as con:
        return con.execute("""
            SELECT r.id recipient_id, r.name recipient_name,
                   COALESCE(r.drive_folder_url,'') drive_folder_url,
                   COUNT(v.id) video_count,
                   SUM(CASE WHEN COALESCE(v.upload_status,'未上传') IN ('已上传','已交付') THEN 1 ELSE 0 END) uploaded_count
            FROM recipients r
            LEFT JOIN hosts h ON h.recipient_id=r.id
            LEFT JOIN videos v ON v.host_id=h.id
            GROUP BY r.id
            ORDER BY r.id DESC
        """).fetchall()



def build_drive_archive_rows(*, work_date=None):
    with read_connection(work_date) as con:
        return con.execute("""
            SELECT v.id video_id, v.seq video_seq,
                   COALESCE(v.edit_output_path,'') edit_output_path,
                   COALESCE(v.edit_status,'等待片段') edit_status,
                   COALESCE(v.upload_status,'未上传') upload_status,
                   r.id recipient_id, r.name recipient_name, r.work_date,
                   h.id host_id, h.name host_name
            FROM videos v
            JOIN hosts h ON h.id=v.host_id
            JOIN recipients r ON r.id=h.recipient_id
            WHERE TRIM(COALESCE(v.edit_output_path,''))<>''
              AND COALESCE(v.upload_status,'未上传') NOT IN ('已上传','已交付','已交给Drive同步')
            ORDER BY r.id, h.id, v.seq
        """).fetchall()



def get_qc_output(output_id):
    with connect() as con:
        output = con.execute('SELECT * FROM flow_outputs WHERE id=?',(int(output_id),)).fetchone()
    if not output:
        return None
    segment = get_qc_segment(output['segment_id'])
    if not segment:
        return None
    data = dict(segment)
    data.update(flow_output_path=output['output_path'], qc_status=output['qc_status'], output_id=output['id'])
    return data


# ===== V0.13.0 multi-channel helpers =====
def ensure_flow_channels(host_id, normal_count=1, include_rework=False):
    host_id=int(host_id); normal_count=max(1,int(normal_count or 1))
    with connect() as con:
        host=con.execute("SELECT flow_collection_url,flow_upload_state,flow_upload_command_id,flow_upload_fingerprint,flow_images_uploaded,flow_images_total,flow_upload_verified_at,flow_upload_error,flow_task_command_id FROM hosts WHERE id=?",(host_id,)).fetchone()
        for i in range(1,normal_count+1):
            key=f"CH{i}"
            con.execute("INSERT OR IGNORE INTO flow_channels(host_id,channel_key,role) VALUES(?,?, 'normal')",(host_id,key))
        if include_rework:
            con.execute("INSERT OR IGNORE INTO flow_channels(host_id,channel_key,role,max_inflight) VALUES(?,?, 'rework',2)",(host_id,'R1'))
        con.execute("UPDATE flow_channels SET enabled=CASE WHEN role='normal' AND CAST(SUBSTR(channel_key,3) AS INTEGER)<=? THEN 1 WHEN role='rework' AND ? THEN 1 ELSE 0 END WHERE host_id=?",(normal_count,1 if include_rework else 0,host_id))
        # One-time migration of the legacy CH1 binding/proof.
        if host:
            ch1=con.execute("SELECT * FROM flow_channels WHERE host_id=? AND channel_key='CH1'",(host_id,)).fetchone()
            if ch1 and not (ch1['collection_url'] or '') and (host['flow_collection_url'] or ''):
                con.execute("""UPDATE flow_channels SET collection_url=?,upload_state=?,upload_command_id=?,upload_fingerprint=?,images_uploaded=?,images_total=?,upload_verified_at=?,upload_error=?,task_command_id=? WHERE id=?""",
                    (host['flow_collection_url'],host['flow_upload_state'],host['flow_upload_command_id'],host['flow_upload_fingerprint'],host['flow_images_uploaded'],host['flow_images_total'],host['flow_upload_verified_at'],host['flow_upload_error'],host['flow_task_command_id'],ch1['id']))

def configure_flow_channels(host_id, normal_count, include_rework=True):
    ensure_flow_channels(host_id, normal_count, include_rework)
    set_setting(f"flow_channel_count_{int(host_id)}", str(max(1,int(normal_count or 1))))
    set_setting(f"flow_rework_enabled_{int(host_id)}", '1' if include_rework else '0')

def flow_channel_count(host_id):
    try: return max(1,int(get_setting(f"flow_channel_count_{int(host_id)}",'1') or 1))
    except Exception: return 1

def flow_rework_enabled(host_id):
    return get_setting(f"flow_rework_enabled_{int(host_id)}",'0')=='1'

def list_flow_channels(host_id=None, recipient_id=None, enabled_only=False):
    where=[]; args=[]
    if host_id is not None: where.append('fc.host_id=?'); args.append(int(host_id))
    if recipient_id is not None: where.append('r.id=?'); args.append(int(recipient_id))
    if enabled_only: where.append('fc.enabled=1')
    clause=(' WHERE '+' AND '.join(where)) if where else ''
    with connect() as con:
        return con.execute(f"""SELECT fc.*,h.name host_name,r.id recipient_id,r.name recipient_name,r.work_date
            FROM flow_channels fc JOIN hosts h ON h.id=fc.host_id JOIN recipients r ON r.id=h.recipient_id
            {clause} ORDER BY r.id,h.id,CASE WHEN fc.role='normal' THEN 0 ELSE 1 END,fc.channel_key""",args).fetchall()

def set_flow_channel_url(channel_id, url):
    url=(url or '').strip(); cid=int(channel_id)
    with connect() as con:
        row=con.execute('SELECT * FROM flow_channels WHERE id=?',(cid,)).fetchone()
        if not row: return
        changed=(row['collection_url'] or '')!=url
        con.execute("""UPDATE flow_channels SET collection_url=?,upload_state=CASE WHEN ? THEN 'idle' ELSE upload_state END,
            upload_command_id=CASE WHEN ? THEN '' ELSE upload_command_id END,upload_fingerprint=CASE WHEN ? THEN '' ELSE upload_fingerprint END,
            images_uploaded=CASE WHEN ? THEN 0 ELSE images_uploaded END,images_total=CASE WHEN ? THEN 0 ELSE images_total END,
            upload_verified_at=CASE WHEN ? THEN '' ELSE upload_verified_at END,upload_error=CASE WHEN ? THEN '' ELSE upload_error END,
            task_command_id=CASE WHEN ? THEN '' ELSE task_command_id END WHERE id=?""",
            (url,changed,changed,changed,changed,changed,changed,changed,changed,cid))
        if row['channel_key']=='CH1':
            con.execute("UPDATE hosts SET flow_collection_url=?,flow_link_status=CASE WHEN ?<>'' THEN '已绑定' ELSE '未绑定' END WHERE id=?",(url,url,row['host_id']))

def set_flow_channel_runtime(channel_id,state,*,command_id=None,fingerprint=None,uploaded=None,total=None,error=None,verified=False,status=None):
    fields=['upload_state=?']; args=[state or 'idle']
    for val,name in [(command_id,'upload_command_id'),(fingerprint,'upload_fingerprint'),(uploaded,'images_uploaded'),(total,'images_total'),(error,'upload_error'),(status,'last_status')]:
        if val is not None:
            fields.append(f'{name}=?'); args.append(int(val) if name in ('images_uploaded','images_total') else (val or ''))
    if state=='queued': fields.append("upload_verified_at=''")
    if verified: fields.append('upload_verified_at=CURRENT_TIMESTAMP')
    args.append(int(channel_id))
    with connect() as con: con.execute(f"UPDATE flow_channels SET {','.join(fields)} WHERE id=?",args)

def get_flow_channel(channel_id):
    with connect() as con: return con.execute('SELECT * FROM flow_channels WHERE id=?',(int(channel_id),)).fetchone()

def set_flow_channel_task_command(channel_id, command_id):
    with connect() as con: con.execute('UPDATE flow_channels SET task_command_id=? WHERE id=?',(command_id or '',int(channel_id)))

def get_flow_channel_task_command(channel_id):
    row=get_flow_channel(channel_id); return str(row['task_command_id'] or '') if row else ''

def touch_flow_channel(channel_id,status=''):
    with connect() as con: con.execute('UPDATE flow_channels SET last_seen=?,last_status=CASE WHEN ?<>\'\' THEN ? ELSE last_status END WHERE id=?',(time.time(),status,status,int(channel_id)))

def assign_flow_channel(segment_id, channel_key, retry=False):
    with connect() as con:
        con.execute("UPDATE flow_segments SET flow_channel_key=?,flow_retry_count=flow_retry_count+? WHERE id=?",(channel_key or '',1 if retry else 0,int(segment_id)))

def channel_summary(host_id=None, recipient_id=None):
    channels=list_flow_channels(host_id,recipient_id,True)
    now=time.time(); online=sum(1 for c in channels if c['last_seen'] and now-float(c['last_seen'])<8)
    return {'total':len(channels),'online':online,'normal':sum(1 for c in channels if c['role']=='normal'),'rework':sum(1 for c in channels if c['role']=='rework')}

# ===== V0.13.2 global multi-browser channel pool =====
def channel_browser_group(channel_key):
    return 'B' if str(channel_key or '').startswith('B-') else 'A'


def ensure_channel_pool(normal_count=7, include_fast=False, *, browser_b_enabled=None, browser_b_normal_count=None, browser_b_fast_enabled=None):
    """
    Browser A keeps legacy keys CH1..CHn + R1 for compatibility.
    Browser B uses B-CH1..B-CHn + B-R1.
    There is intentionally no software channel-count ceiling.
    """
    try:
        normal_count=max(1,int(normal_count or 7))
    except Exception:
        normal_count=7
    if browser_b_enabled is None:
        browser_b_enabled=get_setting('flow_browser_b_enabled','0')=='1'
    if browser_b_normal_count is None:
        try: browser_b_normal_count=max(0,int(get_setting('flow_pool_b_normal_count','0') or 0))
        except Exception: browser_b_normal_count=0
    else:
        browser_b_normal_count=max(0,int(browser_b_normal_count or 0))
    if browser_b_fast_enabled is None:
        browser_b_fast_enabled=get_setting('flow_pool_b_fast_enabled','0')=='1'

    with connect() as con:
        # Disable only managed pool rows first; re-enable exactly the desired layout below.
        con.execute("""UPDATE flow_channel_pool SET enabled=0
                       WHERE channel_key='R1' OR channel_key='B-R1'
                          OR channel_key GLOB 'CH[0-9]*'
                          OR channel_key GLOB 'B-CH[0-9]*'""")
        for i in range(1,normal_count+1):
            key=f'CH{i}'
            con.execute("""INSERT OR IGNORE INTO flow_channel_pool
                (channel_key,role,download_subdir,sort_order,enabled) VALUES(?,?,?,?,1)""",
                (key,'normal',key,i))
            con.execute("UPDATE flow_channel_pool SET role='normal',download_subdir=CASE WHEN download_subdir='' THEN ? ELSE download_subdir END,sort_order=?,enabled=1 WHERE channel_key=?",
                        (key,i,key))
        con.execute("""INSERT OR IGNORE INTO flow_channel_pool
            (channel_key,role,download_subdir,sort_order,enabled) VALUES('R1','fast','R1',900000,?)""",
            (1 if include_fast else 0,))
        con.execute("UPDATE flow_channel_pool SET role='fast',enabled=? WHERE channel_key='R1'",(1 if include_fast else 0,))

        # Browser B is optional and starts with zero channels.
        if browser_b_enabled:
            for i in range(1,browser_b_normal_count+1):
                key=f'B-CH{i}'
                con.execute("""INSERT OR IGNORE INTO flow_channel_pool
                    (channel_key,role,download_subdir,sort_order,enabled) VALUES(?,?,?,?,1)""",
                    (key,'normal',key,100000+i))
                con.execute("UPDATE flow_channel_pool SET role='normal',download_subdir=CASE WHEN download_subdir='' THEN ? ELSE download_subdir END,sort_order=?,enabled=1 WHERE channel_key=?",
                            (key,100000+i,key))
            con.execute("""INSERT OR IGNORE INTO flow_channel_pool
                (channel_key,role,download_subdir,sort_order,enabled) VALUES('B-R1','fast','B-R1',990000,?)""",
                (1 if browser_b_fast_enabled else 0,))
            con.execute("UPDATE flow_channel_pool SET role='fast',enabled=? WHERE channel_key='B-R1'",
                        (1 if browser_b_fast_enabled else 0,))

    set_setting('flow_pool_normal_count',str(normal_count))
    set_setting('flow_pool_fast_enabled','1' if include_fast else '0')
    set_setting('flow_browser_b_enabled','1' if browser_b_enabled else '0')
    set_setting('flow_pool_b_normal_count',str(browser_b_normal_count))
    set_setting('flow_pool_b_fast_enabled','1' if browser_b_fast_enabled else '0')


def channel_pool_normal_count():
    try:return max(1,int(get_setting('flow_pool_normal_count','7') or 7))
    except Exception:return 7


def browser_b_enabled():
    return get_setting('flow_browser_b_enabled','0')=='1'


def browser_b_normal_count():
    try:return max(0,int(get_setting('flow_pool_b_normal_count','0') or 0))
    except Exception:return 0


def browser_b_fast_enabled():
    return get_setting('flow_pool_b_fast_enabled','0')=='1'


def list_channel_pool(enabled_only=False):
    ensure_channel_pool(
        channel_pool_normal_count(),
        get_setting('flow_pool_fast_enabled','1')!='0',
        browser_b_enabled=browser_b_enabled(),
        browser_b_normal_count=browser_b_normal_count(),
        browser_b_fast_enabled=browser_b_fast_enabled(),
    )
    clause=' WHERE enabled=1' if enabled_only else ''
    with connect() as con:
        return con.execute(f"""SELECT * FROM flow_channel_pool{clause}
            ORDER BY
              CASE WHEN channel_key LIKE 'B-%' THEN 1 ELSE 0 END,
              CASE WHEN role='normal' THEN 0 ELSE 1 END,
              sort_order, channel_key""").fetchall()


def get_channel_pool(channel_key=None, channel_id=None):
    with connect() as con:
        if channel_id is not None:return con.execute('SELECT * FROM flow_channel_pool WHERE id=?',(int(channel_id),)).fetchone()
        return con.execute('SELECT * FROM flow_channel_pool WHERE channel_key=?',(str(channel_key),)).fetchone()


def save_channel_pool(channel_key, *, collection_url=None, download_subdir=None, enabled=None):
    fields=[];args=[]
    if collection_url is not None: fields.append('collection_url=?');args.append((collection_url or '').strip())
    if download_subdir is not None: fields.append('download_subdir=?');args.append((download_subdir or '').strip() or str(channel_key))
    if enabled is not None: fields.append('enabled=?');args.append(1 if enabled else 0)
    if not fields:return
    args.append(str(channel_key))
    with connect() as con: con.execute(f"UPDATE flow_channel_pool SET {','.join(fields)} WHERE channel_key=?",args)


def add_pool_channel(browser='A', role='normal'):
    browser='B' if str(browser).upper()=='B' else 'A'
    role='fast' if str(role)=='fast' else 'normal'
    if browser=='A':
        if role=='fast':
            set_setting('flow_pool_fast_enabled','1')
        else:
            set_setting('flow_pool_normal_count',str(channel_pool_normal_count()+1))
    else:
        set_setting('flow_browser_b_enabled','1')
        if role=='fast':
            set_setting('flow_pool_b_fast_enabled','1')
        else:
            set_setting('flow_pool_b_normal_count',str(browser_b_normal_count()+1))
    ensure_channel_pool(
        channel_pool_normal_count(),
        get_setting('flow_pool_fast_enabled','1')!='0',
        browser_b_enabled=browser_b_enabled(),
        browser_b_normal_count=browser_b_normal_count(),
        browser_b_fast_enabled=browser_b_fast_enabled(),
    )


def set_browser_b_enabled(enabled):
    set_setting('flow_browser_b_enabled','1' if enabled else '0')
    ensure_channel_pool(
        channel_pool_normal_count(),
        get_setting('flow_pool_fast_enabled','1')!='0',
        browser_b_enabled=bool(enabled),
        browser_b_normal_count=browser_b_normal_count(),
        browser_b_fast_enabled=browser_b_fast_enabled(),
    )


def set_browser_b_fast_enabled(enabled):
    set_setting('flow_browser_b_enabled','1')
    set_setting('flow_pool_b_fast_enabled','1' if enabled else '0')
    ensure_channel_pool(
        channel_pool_normal_count(),
        get_setting('flow_pool_fast_enabled','1')!='0',
        browser_b_enabled=True,
        browser_b_normal_count=browser_b_normal_count(),
        browser_b_fast_enabled=bool(enabled),
    )

def set_channel_pool_runtime(channel_key, state=None, *, command_id=None, fingerprint=None, uploaded=None, total=None, error=None, verified=False, status=None, seen=False):
    fields=[];args=[]
    if state is not None: fields.append('upload_state=?');args.append(state)
    for val,name in [(command_id,'upload_command_id'),(fingerprint,'upload_fingerprint'),(uploaded,'images_uploaded'),(total,'images_total'),(error,'upload_error'),(status,'last_status')]:
        if val is not None:
            fields.append(f'{name}=?');args.append(int(val) if name in ('images_uploaded','images_total') else (val or ''))
    if verified: fields.append('upload_verified_at=CURRENT_TIMESTAMP')
    if seen: fields.append('last_seen=?');args.append(__import__('time').time())
    if error is not None: fields.append('last_error=?');args.append(error or '')
    if not fields:return
    args.append(str(channel_key))
    with connect() as con: con.execute(f"UPDATE flow_channel_pool SET {','.join(fields)} WHERE channel_key=?",args)


def set_channel_pool_task_command(channel_key, command_id):
    with connect() as con: con.execute('UPDATE flow_channel_pool SET task_command_id=? WHERE channel_key=?',(command_id or '',str(channel_key)))


def release_channel_pool_submission_command(channel_key, command_id):
    """Release the channel's submission slot without touching active render/download ownership.

    A channel may accept the next submission wave once every task in the current wave
    has a confirmed submit/terminal failure. flow_segments.generation_command and
    flow_dispatches remain intact so late renders/downloads still map to the old task.
    The command comparison prevents a delayed completion event from clearing a newer wave.
    """
    key=str(channel_key or '')
    cmd=str(command_id or '')
    if not key or not cmd:
        return 0
    with connect() as con:
        cur=con.execute(
            "UPDATE flow_channel_pool SET task_command_id='', last_status='空闲 · 等待新任务' WHERE channel_key=? AND task_command_id=?",
            (key,cmd)
        )
        return int(cur.rowcount or 0)


def _published_generation_commands(con):
    """Commands that are still exposed by the local Bridge as executable waves."""
    try:
        row=con.execute("SELECT value FROM app_settings WHERE key='flow_host_jobs_v124'").fetchone()
        jobs=_json.loads(row[0] if row else '[]')
    except Exception:
        jobs=[]
    return {str(j.get('command_id') or '') for j in jobs
            if str(j.get('command_id') or '') and bool(j.get('dispatch_tasks')) and bool(j.get('auto_execute', True))
            and bool(j.get('tasks'))}


def heal_recent_online_channels(now=None, heartbeat_window=20):
    """A currently heartbeating, idle tab must not remain quarantined/stale.

    The visual monitor already treats a recent heartbeat as online. Keeping the same
    channel excluded from scheduling because of an old quarantine made it look ``空闲``
    while the dispatcher saw zero available channels.  Only idle submission slots are
    healed; an active task_command_id is never cleared here.
    """
    now=float(now or _time.time())
    healed=[]
    with connect() as con:
        rows=con.execute("""SELECT channel_key,last_seen,task_command_id,health_status,quarantine_until
                              FROM flow_channel_pool WHERE enabled=1""").fetchall()
        for row in rows:
            age=now-float(row['last_seen'] or 0) if row['last_seen'] else 10**9
            if age>float(heartbeat_window) or str(row['task_command_id'] or ''):
                continue
            if float(row['quarantine_until'] or 0)>now or str(row['health_status'] or '') in ('quarantined','stale','recovering','degraded'):
                con.execute("""UPDATE flow_channel_pool SET quarantine_until=0,health_status='healthy',
                                consecutive_failures=0,page_status=CASE WHEN page_status='heartbeat_stale' THEN 'complete' ELSE page_status END
                                WHERE channel_key=?""",(str(row['channel_key']),))
                healed.append(str(row['channel_key']))
    return healed



def reconcile_selected_date_unfinished_tasks(*, work_date):
    """Repair *safe* stranded Flow state for one explicitly selected work date.

    The auto scheduler must be able to rediscover unfinished work after restarts or
    partial upgrades, but it must never duplicate a generation that Flow may already
    have accepted.  This routine therefore resets a segment to ``待生成`` only when
    there is no durable evidence that its current command was published, claimed,
    submitted, downloading, detected, or completed.

    It is intentionally date-scoped.  Rows from every other date are read/written by
    neither the audit nor the repair path.
    """
    day=work_date
    with read_connection(day) as scoped:
        scoped_rows=[dict(r) for r in scoped.execute("""
            SELECT fs.id,COALESCE(NULLIF(fs.flow_status,''),'待生成') flow_status,
                   COALESCE(fs.generation_command,'') generation_command,
                   COALESCE(fs.flow_channel_key,'') flow_channel_key,
                   COALESCE(fs.flow_output_path,'') flow_output_path
              FROM flow_segments fs
             WHERE TRIM(COALESCE(fs.prompt,''))<>''
               AND COALESCE(fs.prompt_review_status,'待检查')='已提交'
               AND COALESCE(NULLIF(fs.flow_status,''),'待生成')<>'已完成'
        """).fetchall()]
    if not scoped_rows:
        return {'work_date':day,'unfinished':0,'requeued':[],'restored':[],
                'dispatchable':0,'active':0,'failed':0,'download_failed':0,'protected':0}

    allowed={int(r['id']) for r in scoped_rows}
    requeued=[];restored=[]
    # Plain waiting rows without a command_id cannot be stranded or missing command identity;
    # only inspect rows that carry a command_id or claim an active submission state.
    inspect_rows=[
        base for base in scoped_rows
        if str(base.get('generation_command') or '').strip()
        or str(base.get('flow_status') or '待生成') in ('已提交','生成中','下载中')
    ]
    if inspect_rows:
        with connect() as con:
            published=_published_generation_commands(con)
            owner_table=bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='browser_command_owners'").fetchone())
            receipt_table=bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='flow_receipts'").fetchone())
            for base in inspect_rows:
                sid=int(base['id'])
                # Re-read under the write connection so a receipt arriving between the
                # scoped snapshot and this repair cannot be overwritten.
                row=con.execute("""SELECT id,COALESCE(NULLIF(flow_status,''),'待生成') flow_status,
                                          COALESCE(generation_command,'') generation_command,
                                          COALESCE(flow_channel_key,'') flow_channel_key,
                                          COALESCE(flow_output_path,'') flow_output_path
                                     FROM flow_segments WHERE id=?""",(sid,)).fetchone()
                if not row or sid not in allowed or str(row['flow_status'])=='已完成' or str(row['flow_output_path'] or '').strip():
                    continue
                status=str(row['flow_status'] or '待生成')
                cmd=str(row['generation_command'] or '').strip()

                # Inconsistent legacy rows can lose generation_command while a dispatch
                # still carries the immutable command identity.  Restore that identity
                # instead of generating a duplicate.
                if not cmd and status in ('已提交','生成中','下载中'):
                    candidates=con.execute("""SELECT command_id,status,submitted_at,created_at
                        FROM flow_dispatches WHERE segment_id=? AND
                        (status IN ('submitted','downloading','detected') OR TRIM(COALESCE(submitted_at,''))<>'')
                        ORDER BY id DESC""",(sid,)).fetchall()
                    unique=[]
                    for d in candidates:
                        c=str(d['command_id'] or '').strip()
                        if c and c not in unique:unique.append(c)
                    if len(unique)==1:
                        con.execute("UPDATE flow_segments SET generation_command=? WHERE id=? AND TRIM(COALESCE(generation_command,''))=''",(unique[0],sid))
                        restored.append(sid)
                        continue

                if not cmd or status not in ('待生成','已准备'):
                    # Unknown submitted/running ownership or non-waiting statuses must never be reset here.
                    continue

                # Short-circuit from cheapest to most expensive check so active/submitted commands
                # never trigger a full-table LIKE scan of flow_receipts on every 2s tick.
                protected = (
                    (cmd in published)
                    or bool(owner_table and con.execute("SELECT 1 FROM browser_command_owners WHERE command_id=? LIMIT 1",(cmd,)).fetchone())
                    or bool(con.execute("""SELECT 1 FROM flow_dispatches WHERE segment_id=? AND command_id=? AND
                        (status IN ('submitted','downloading','detected') OR TRIM(COALESCE(submitted_at,''))<>'') LIMIT 1""",(sid,cmd)).fetchone())
                    or bool(con.execute("SELECT 1 FROM flow_outputs WHERE segment_id=? AND command_id=? LIMIT 1",(sid,cmd)).fetchone())
                    or bool(receipt_table and con.execute("SELECT 1 FROM flow_receipts WHERE payload LIKE ? AND payload LIKE ? LIMIT 1",
                        (f'%{cmd}%',f'%\"segment_id\": {sid}%')).fetchone())
                )

                if not protected:
                    con.execute("""UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',
                        error=CASE WHEN TRIM(COALESCE(error,''))='' THEN '自动恢复：当前日期未完成任务无提交证据' ELSE error END,
                        last_update_at=?
                        WHERE segment_id=? AND command_id=? AND status IN ('planned','queued')""",(_time.time(),sid,cmd))
                    con.execute("""UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_channel_key='',flow_error=''
                        WHERE id=? AND generation_command=? AND flow_status IN ('待生成','已准备')""",(sid,cmd))
                    # Release only this obsolete command's submission slot; another newer
                    # command on the same channel cannot be cleared by this statement.
                    con.execute("""UPDATE flow_channel_pool SET task_command_id='',last_status='空闲 · 已恢复当前日期等待任务'
                        WHERE task_command_id=?""",(cmd,))
                    requeued.append(sid)

    if requeued or restored:
        with read_connection(day) as scoped:
            rows=[dict(r) for r in scoped.execute("""
                SELECT fs.id,COALESCE(NULLIF(fs.flow_status,''),'待生成') flow_status,
                       COALESCE(fs.generation_command,'') generation_command,
                       COALESCE(fs.flow_output_path,'') flow_output_path
                  FROM flow_segments fs
                 WHERE TRIM(COALESCE(fs.prompt,''))<>''
                   AND COALESCE(fs.prompt_review_status,'待检查')='已提交'
                   AND COALESCE(NULLIF(fs.flow_status,''),'待生成')<>'已完成'
            """).fetchall()]
    else:
        rows = scoped_rows
    return {
        'work_date':day,
        'unfinished':len(rows),
        'requeued':requeued,
        'restored':restored,
        'dispatchable':sum(1 for r in rows if str(r['flow_status'] or '待生成') in ('待生成','已准备') and not str(r['generation_command'] or '').strip()),
        'active':sum(1 for r in rows if str(r['flow_status'] or '') in ('已提交','生成中','下载中')),
        'failed':sum(1 for r in rows if str(r['flow_status'] or '')=='失败'),
        'download_failed':sum(1 for r in rows if str(r['flow_status'] or '')=='下载失败'),
        'protected':sum(1 for r in rows if bool(str(r['generation_command'] or '').strip())),
    }


def recover_orphaned_waiting_commands(*, work_date=None):
    """Return provably orphaned, never-submitted waiting rows to the central pool.

    This intentionally does *not* touch submitted/generating/downloading work.  Recovery
    is allowed only when the command is no longer published by Bridge, has no browser
    command owner, has no output, and has no submitted/downloaded dispatch receipt.
    That closes the restart/partial-registration hole where the UI shows every channel
    as idle but ``generation_command`` still makes the remaining segments invisible to
    the automatic dispatcher.
    """
    recovered=[]
    released_channels=[]
    with connect() as con:
        if work_date is not None:
            rows=con.execute("""SELECT fs.id,fs.generation_command,fs.flow_status,fs.flow_channel_key,
                                       COALESCE(fs.flow_output_path,'') flow_output_path
                                  FROM flow_segments fs
                                  JOIN videos v ON v.id=fs.video_id
                                  JOIN hosts h ON h.id=v.host_id
                                  JOIN recipients r ON r.id=h.recipient_id
                                 WHERE r.work_date=?
                                   AND fs.flow_status IN ('待生成','已准备')
                                   AND TRIM(COALESCE(fs.generation_command,''))<>''""",
                             (str(work_date),)).fetchall()
        else:
            rows=con.execute("""SELECT id,generation_command,flow_status,flow_channel_key,COALESCE(flow_output_path,'') flow_output_path
                                  FROM flow_segments
                                 WHERE flow_status IN ('待生成','已准备')
                                   AND TRIM(COALESCE(generation_command,''))<>''""").fetchall()
        if not rows:
            return {'segments':[], 'channels':[]}
        published=_published_generation_commands(con)
        owner_table=bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='browser_command_owners'").fetchone())
        orphan_cmds=set()
        for row in rows:
            sid=int(row['id']); cmd=str(row['generation_command'] or '')
            if cmd in published or row['flow_output_path']:
                continue
            if owner_table and con.execute("SELECT 1 FROM browser_command_owners WHERE command_id=? LIMIT 1",(cmd,)).fetchone():
                continue
            submitted=con.execute("""SELECT 1 FROM flow_dispatches
                                      WHERE segment_id=? AND command_id=?
                                        AND (status IN ('submitted','downloading','detected')
                                             OR TRIM(COALESCE(submitted_at,''))<>'') LIMIT 1""",(sid,cmd)).fetchone()
            if submitted:
                continue
            statuses=[str(x[0] or '') for x in con.execute("SELECT status FROM flow_dispatches WHERE segment_id=? AND command_id=?",(sid,cmd)).fetchall()]
            # A real failed dispatch remains manual-only.  Empty / queued / cancelled
            # local plans are safe to return because there is no publish/owner/submit proof.
            if any(st=='failed' for st in statuses):
                continue
            con.execute("""UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',
                            error=CASE WHEN TRIM(COALESCE(error,''))='' THEN '自动恢复：本地派发命令已失联且从未提交' ELSE error END,
                            last_update_at=?
                            WHERE segment_id=? AND command_id=? AND status IN ('planned','queued')""",(_time.time(),sid,cmd))
            con.execute("""UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_channel_key='',flow_error=''
                            WHERE id=? AND generation_command=? AND flow_status IN ('待生成','已准备')""",(sid,cmd))
            recovered.append(sid); orphan_cmds.add(cmd)
        if orphan_cmds:
            for cmd in orphan_cmds:
                # Command-guarded release: never clear a newer wave on the same channel.
                rows2=con.execute("SELECT channel_key FROM flow_channel_pool WHERE task_command_id=?",(cmd,)).fetchall()
                for ch in rows2:
                    cur=con.execute("""UPDATE flow_channel_pool SET task_command_id='',last_status='空闲 · 已恢复遗留任务'
                                        WHERE channel_key=? AND task_command_id=?""",(str(ch['channel_key']),cmd))
                    if int(cur.rowcount or 0): released_channels.append(str(ch['channel_key']))
    return {'segments':recovered,'channels':released_channels}



def recover_unconfirmed_preclick_dispatches(*, work_date=None, grace_seconds=12):
    """Repair the V84-era false ``已提交`` race without touching real submissions.

    Affected old builds emitted ``preparing/running`` before Flow had accepted a
    generation, while Studio incorrectly persisted those receipts as dispatch
    ``submitted``.  Once the channel slot was released, the Bridge job could be
    replaced and the segment became an orphan that looked submitted forever.

    Recovery is deliberately narrow and date-scoped:
    - the command must no longer be published by Bridge;
    - the current segment must still be only ``已准备/已提交``;
    - the dispatch was incorrectly marked ``submitted``;
    - receipts may contain only pre-confirm states (``preparing/running``), never
      ``success`` or ``uncertain`` and never any download receipt;
    - a short grace period avoids racing an event still being committed.
    """
    now=float(_time.time())
    grace=max(3.0,float(grace_seconds or 0))
    recovered=[];released=[];commands=set()
    with connect() as con:
        args=[]; date_sql=''
        if work_date is not None:
            date_sql=' AND r.work_date=?'; args.append(str(work_date))
        rows=con.execute("""SELECT d.id dispatch_id,d.segment_id,d.command_id,d.channel_key,d.last_update_at,
                    fs.flow_status,fs.generation_command
                FROM flow_dispatches d
                JOIN flow_segments fs ON fs.id=d.segment_id
                JOIN videos v ON v.id=fs.video_id
                JOIN hosts h ON h.id=v.host_id
                JOIN recipients r ON r.id=h.recipient_id
                WHERE d.status='submitted' AND fs.generation_command=d.command_id
                  AND fs.flow_status IN ('已准备','已提交')"""+date_sql,args).fetchall()
        if not rows:
            return {'segments':[],'channels':[],'commands':[]}
        published=_published_generation_commands(con)
        candidates=[]
        for row in rows:
            cmd=str(row['command_id'] or ''); sid=int(row['segment_id'])
            if not cmd or cmd in published:
                continue
            last=float(row['last_update_at'] or 0)
            if last and now-last < grace:
                continue
            candidates.append(row)
        if not candidates:
            return {'segments':[],'channels':[],'commands':[]}
        cand_cmds=sorted({str(r['command_id']) for r in candidates})
        like_clauses=' OR '.join(['payload LIKE ?']*len(cand_cmds))
        like_args=[f'%{c}%' for c in cand_cmds]
        receipt_states={}; terminal_commands=set()
        for rr in con.execute(f"SELECT payload FROM flow_receipts WHERE {like_clauses}", like_args):
            try: event=_json.loads(rr['payload'] or '{}')
            except Exception: continue
            cmd=str(event.get('command_id') or '')
            sid=int(event.get('segment_id') or 0)
            if not cmd or not sid: continue
            typ=str(event.get('type') or '')
            state=str(event.get('state') or '')
            receipt_states.setdefault((cmd,sid),set()).add((typ,state))
            if typ.startswith('video_download_') or (typ=='generation_task_status' and state in ('success','uncertain','failed')):
                terminal_commands.add((cmd,sid))
        for row in candidates:
            cmd=str(row['command_id'] or ''); sid=int(row['segment_id'])
            if (cmd,sid) in terminal_commands:
                continue
            events=receipt_states.get((cmd,sid),set())
            states={state for typ,state in events if typ=='generation_task_status'}
            # No evidence means we cannot prove whether another build submitted it.
            # Only the known pre-click receipts are safe to repair automatically.
            if not states or not states.issubset({'preparing','running'}):
                continue
            seg_cur=con.execute("""UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_channel_key='',
                        flow_error='已自动修复旧版假提交状态' WHERE id=? AND generation_command=?
                        AND flow_status IN ('已准备','已提交')""",(sid,cmd))
            if not int(seg_cur.rowcount or 0):
                continue
            con.execute("""UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',
                        error='已修复：旧版在 Flow 确认前误标为已提交',last_update_at=? WHERE id=?""",(now,int(row['dispatch_id'])))
            recovered.append(sid); commands.add(cmd)
        for cmd in sorted(commands):
            for ch in con.execute("SELECT channel_key FROM flow_channel_pool WHERE task_command_id=?",(cmd,)).fetchall():
                cur=con.execute("""UPDATE flow_channel_pool SET task_command_id='',last_status='空闲 · 已修复假提交'
                                  WHERE channel_key=? AND task_command_id=?""",(str(ch['channel_key']),cmd))
                if int(cur.rowcount or 0): released.append(str(ch['channel_key']))
    return {'segments':sorted(set(recovered)),'channels':sorted(set(released)),'commands':sorted(commands)}


def list_timed_out_active_commands(*, work_date=None, now=None, timeout_seconds=300, max_retries=3):
    """Return current-date Flow commands that exceeded the hard download-success SLA.

    Unlike the safe QUEUED reclaim path, this is an explicit production policy: once a
    command has remained unfinished beyond ``timeout_seconds`` with no durable local
    download/output, Studio is allowed to invalidate it and retry.  Only the command
    currently owned by each segment is considered; stale historical dispatch rows can
    never trigger a retry.  QC redo rows are excluded here and keep their dedicated R1/R2
    routing semantics.
    """
    now=float(now or _time.time())
    timeout=max(60,int(timeout_seconds or 300))
    retry_cap=max(1,int(max_retries or 3))
    with read_connection(work_date) as con:
        rows=con.execute("""
            SELECT d.command_id,
                   MIN(d.channel_key) channel_key,
                   MIN(CASE WHEN COALESCE(d.release_at,0)>0 THEN d.release_at
                            ELSE CAST(strftime('%s',d.created_at) AS REAL) END) started_at,
                   MAX(COALESCE(d.last_update_at,0)) last_update_at,
                   COUNT(DISTINCT fs.id) segment_count,
                   MAX(COALESCE(fs.flow_retry_count,0)) retry_count,
                   GROUP_CONCAT(DISTINCT COALESCE(fs.flow_status,'')) statuses
              FROM flow_dispatches d
              JOIN flow_segments fs ON fs.id=d.segment_id AND fs.generation_command=d.command_id
             WHERE TRIM(COALESCE(d.command_id,''))<>''
               AND COALESCE(fs.flow_status,'待生成') IN ('待生成','已准备','已提交','生成中','下载中','失败','下载失败')
               AND TRIM(COALESCE(fs.flow_output_path,''))=''
               AND NOT EXISTS (SELECT 1 FROM flow_outputs fo WHERE fo.segment_id=fs.id AND fo.command_id=d.command_id)
               AND NOT EXISTS (SELECT 1 FROM flow_redo rr WHERE rr.segment_id=fs.id)
               AND NOT (COALESCE(fs.flow_status,'')='失败' AND COALESCE(fs.flow_error,'') LIKE '%图片上传失败%' AND COALESCE(fs.flow_error,'') LIKE '%跳过%')
             GROUP BY d.command_id
        """).fetchall()
    out=[]
    for row in rows:
        started=float(row['started_at'] or 0)
        if not started:
            continue
        age=max(0.0,now-started)
        if age < timeout:
            continue
        out.append({
            'command_id':str(row['command_id'] or ''),
            'channel_key':str(row['channel_key'] or ''),
            'started_at':started,
            'last_update_at':float(row['last_update_at'] or 0),
            'age_seconds':age,
            'segment_count':int(row['segment_count'] or 0),
            'retry_count':int(row['retry_count'] or 0),
            'retry_exhausted':int(row['retry_count'] or 0)>=retry_cap,
            'statuses':str(row['statuses'] or ''),
        })
    return out


def requeue_timed_out_active_command(command_id, *, work_date=None, reason='生成超时，已自动重新派发', max_retries=3):
    """Invalidate one timed-out current command and return unfinished normal tasks to WAITING.

    The obsolete-command tombstone is essential: if Flow later finishes the old paid
    render, its delayed browser/download receipt cannot revive or overwrite the retried
    segment.  Completed/output-owning rows are never reset.
    """
    cmd=str(command_id or '').strip()
    if not cmd:
        return {'requeued':[], 'failed':[], 'channels':[]}
    retry_cap=max(1,int(max_retries or 3))
    allowed=None
    if work_date is not None:
        with read_connection(work_date) as scoped:
            allowed={int(r[0]) for r in scoped.execute('SELECT id FROM flow_segments').fetchall()}
        if not allowed:
            return {'requeued':[], 'failed':[], 'channels':[]}
    now=_time.time(); requeued=[]; failed=[]; channels=[]
    with connect() as con:
        rows=con.execute("""SELECT fs.id,fs.flow_status,fs.flow_retry_count,fs.flow_channel_key,
                                   fs.flow_output_path,v.host_id
                              FROM flow_segments fs
                              JOIN videos v ON v.id=fs.video_id
                             WHERE fs.generation_command=?
                               AND fs.flow_status IN ('待生成','已准备','已提交','生成中','下载中','失败','下载失败')
                               -- upload-failed images skipped in the plugin are manual-retry only
                               AND NOT (fs.flow_status='失败' AND COALESCE(fs.flow_error,'') LIKE '%图片上传失败%' AND COALESCE(fs.flow_error,'') LIKE '%跳过%')""",(cmd,)).fetchall()
        rows=[r for r in rows if allowed is None or int(r['id']) in allowed]
        rows=[r for r in rows if not str(r['flow_output_path'] or '').strip() and not con.execute(
            'SELECT 1 FROM flow_outputs WHERE segment_id=? AND command_id=? LIMIT 1',(int(r['id']),cmd)).fetchone()]
        if not rows:
            return {'requeued':[], 'failed':[], 'channels':[]}
        host_id=int(rows[0]['host_id'] or 0)
        con.execute("INSERT OR REPLACE INTO flow_obsolete_commands(command_id,host_id,reason,invalidated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
                    (cmd,host_id,str(reason or '生成超时自动重试')))
        # Drop unresolved browser download bindings from the invalidated command.
        for pending in con.execute('SELECT event_id,payload FROM flow_pending_downloads').fetchall():
            try:
                ev=_json.loads(pending['payload'] or '{}')
            except Exception:
                continue
            if str(ev.get('command_id') or '')==cmd:
                con.execute('DELETE FROM flow_pending_downloads WHERE event_id=?',(pending['event_id'],))
        for row in rows:
            sid=int(row['id']); next_retry=int(row['flow_retry_count'] or 0)+1
            con.execute("""UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',
                        error=?,last_update_at=? WHERE segment_id=? AND command_id=? AND status<>'detected'""",
                        (str(reason or '生成超时自动重试'),now,sid,cmd))
            if next_retry>retry_cap:
                con.execute("""UPDATE flow_segments SET generation_command='',flow_status='失败',flow_channel_key='',
                            flow_error=?,flow_retry_count=? WHERE id=? AND generation_command=?""",
                            (f'连续 {retry_cap} 次生成超时，已停止自动重试',next_retry,sid,cmd))
                failed.append(sid)
            else:
                con.execute("""UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_channel_key='',
                            flow_error='',flow_retry_count=? WHERE id=? AND generation_command=?""",
                            (next_retry,sid,cmd))
                requeued.append(sid)
        for ch in con.execute('SELECT channel_key FROM flow_channel_pool WHERE task_command_id=?',(cmd,)).fetchall():
            key=str(ch['channel_key'] or '')
            cur=con.execute("""UPDATE flow_channel_pool SET task_command_id='',last_status='空闲 · 超时任务已回收'
                              WHERE channel_key=? AND task_command_id=?""",(key,cmd))
            if int(cur.rowcount or 0): channels.append(key)
        # Persisted Bridge snapshot is also scrubbed so an old browser pull cannot
        # resurrect the invalidated command after an app restart.
        setting=con.execute("SELECT value FROM app_settings WHERE key='flow_host_jobs_v124'").fetchone()
        if setting:
            try:
                jobs=_json.loads(setting['value'] or '[]')
                if isinstance(jobs,list):
                    jobs=[j for j in jobs if str((j or {}).get('command_id') or '')!=cmd]
                    con.execute("UPDATE app_settings SET value=? WHERE key='flow_host_jobs_v124'",(_json.dumps(jobs,ensure_ascii=False),))
            except Exception:
                pass
    return {'requeued':requeued,'failed':failed,'channels':channels}

def release_submitted_channel_commands():
    """Release channel *submission* slots after every dispatch was handed to Flow.

    Render/download ownership intentionally remains on ``generation_command`` and the
    dispatch rows.  In addition to the normal submitted-wave path, an empty command is
    released when it is no longer published by Bridge.  This is safe because the Bridge
    publication is the authority for executable local waves and fixes the otherwise
    permanent ``UI空闲 / 调度器占用`` state after a partial registration/restart.
    """
    released=[]
    with connect() as con:
        published=_published_generation_commands(con)
        rows=con.execute("SELECT channel_key,task_command_id FROM flow_channel_pool WHERE enabled=1 AND task_command_id<>''").fetchall()
        for row in rows:
            key=str(row['channel_key'] or '')
            cmd=str(row['task_command_id'] or '')
            if not key or not cmd:
                continue
            exists=con.execute("SELECT 1 FROM flow_dispatches WHERE command_id=? LIMIT 1",(cmd,)).fetchone()
            if not exists:
                if cmd in published:
                    continue
                cur=con.execute("""UPDATE flow_channel_pool
                    SET task_command_id='',last_status='空闲 · 已释放遗留占用'
                    WHERE channel_key=? AND task_command_id=?""",(key,cmd))
                if int(cur.rowcount or 0):
                    released.append(key)
                continue
            if cmd not in published:
                uploading=con.execute("""SELECT 1 FROM flow_channel_pool
                    WHERE channel_key=? AND upload_command_id=? AND upload_state IN ('queued','uploading')
                    LIMIT 1""",(key,cmd)).fetchone()
                if not uploading:
                    cur=con.execute("""UPDATE flow_channel_pool
                        SET task_command_id='',last_status='空闲 · 等待新任务'
                        WHERE channel_key=? AND task_command_id=?""",(key,cmd))
                    if int(cur.rowcount or 0):
                        released.append(key)
                    continue
            pending=con.execute("""SELECT 1 FROM flow_dispatches d
                JOIN flow_segments fs ON fs.id=d.segment_id
                WHERE d.command_id=? AND fs.generation_command=?
                  AND fs.flow_status NOT IN ('已完成','失败','下载失败','已放弃')
                  AND (d.status IN ('planned','queued') OR (fs.flow_status IN ('待生成','已准备','已提交') AND d.status NOT IN ('submitted','downloading','detected')))
                LIMIT 1""",(cmd,cmd)).fetchone()
            if pending:
                continue
            cur=con.execute("""UPDATE flow_channel_pool
                SET task_command_id='',last_status='空闲 · 等待新任务'
                WHERE channel_key=? AND task_command_id=?""",(key,cmd))
            if int(cur.rowcount or 0):
                released.append(key)
    return released


def self_heal_stalled_scheduler_state(
    *,
    work_date=None,
    now=None,
    idle_heartbeat_channels=None,
    uncertain_grace_seconds=120,
    zombie_generating_seconds=1200,
    max_auto_retries=2,
):
    """Self-heal three non-recovering scheduler deadlocks without duplicating active renders:
    1) Channel idle-heartbeat reconciliation: unlock channels whose live tab continuously
       reports `command_id=''` (or whose command is no longer published as executable).
    2) Uncertain/unconfirmed pre-submit closure: close `planned/queued` (`已准备`) dispatches
       whose wave already finished and produced no output within `uncertain_grace_seconds`.
    3) Zombie `生成中/已提交` closure: reclaim segments stuck > `zombie_generating_seconds`
       with no output file and no active recent download, capped at `max_auto_retries`.
    """
    now = float(now or _time.time())
    idle_map = {str(k): float(v) for k, v in dict(idle_heartbeat_channels or {}).items() if k}
    uncertain_grace = max(45.0, float(uncertain_grace_seconds or 120))
    zombie_timeout = max(300.0, float(zombie_generating_seconds or 1200))
    retry_cap = max(1, int(max_auto_retries or 2))

    released_channels = []
    retired_commands = []
    uncertain_requeued = []
    uncertain_failed = []
    zombie_requeued = []
    zombie_failed = []

    with connect() as con:
        published = set(_published_generation_commands(con))
        has_pending_dl = bool(
            con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='flow_pending_downloads'").fetchone()
        )
        has_redo = bool(
            con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='flow_redo'").fetchone()
        )

        # --- Guardrail 1: Channel idle-heartbeat & non-executable slot reconciliation ---
        ch_rows = con.execute(
            "SELECT channel_key,task_command_id,upload_state,upload_command_id FROM flow_channel_pool WHERE enabled=1 AND task_command_id<>''"
        ).fetchall()
        for ch in ch_rows:
            key = str(ch['channel_key'] or '')
            cmd = str(ch['task_command_id'] or '')
            if not key or not cmd:
                continue
            if str(ch['upload_command_id'] or '') == cmd and str(ch['upload_state'] or '') in ('queued', 'uploading'):
                continue
            if cmd not in published:
                cur = con.execute(
                    "UPDATE flow_channel_pool SET task_command_id='',last_status='空闲 · 已自动释放已完成波次' WHERE channel_key=? AND task_command_id=?",
                    (key, cmd),
                )
                if int(cur.rowcount or 0):
                    released_channels.append(key)
                continue
            if key in idle_map:
                stat = con.execute(
                    """SELECT MIN(CASE WHEN COALESCE(release_at,0)>0 THEN release_at ELSE COALESCE(last_update_at,0) END) started_at,
                              MAX(COALESCE(last_update_at,0)) last_update_at
                         FROM flow_dispatches WHERE command_id=?""",
                    (cmd,),
                ).fetchone()
                started_at = float((stat['started_at'] if stat else 0) or 0)
                last_upd = float((stat['last_update_at'] if stat else 0) or 0)
                if (not started_at or (now - started_at) >= 30.0) and (not last_upd or (now - last_upd) >= 25.0):
                    cur = con.execute(
                        "UPDATE flow_channel_pool SET task_command_id='',last_status='空闲 · 心跳对账已释放通道' WHERE channel_key=? AND task_command_id=?",
                        (key, cmd),
                    )
                    if int(cur.rowcount or 0):
                        released_channels.append(key)
                    retired_commands.append(cmd)
                    published.discard(cmd)

        date_sql = ''
        date_args = []
        if work_date is not None:
            date_sql = ' AND r.work_date=?'
            date_args.append(str(work_date))

        def _drop_pending_dl(target_cmd, target_sid):
            if not has_pending_dl:
                return
            for p_row in con.execute("SELECT event_id,payload FROM flow_pending_downloads").fetchall():
                try:
                    ev = _json.loads(p_row['payload'] or '{}')
                except Exception:
                    continue
                if str(ev.get('command_id') or '') == target_cmd and int(ev.get('segment_id') or 0) == int(target_sid):
                    con.execute("DELETE FROM flow_pending_downloads WHERE event_id=?", (p_row['event_id'],))

        def _apply_segment_recovery(sid, cmd, qc_status, tag_reason, fail_label):
            prior_auto = int(
                con.execute(
                    "SELECT COUNT(DISTINCT command_id) FROM flow_dispatches WHERE segment_id=? AND status='cancelled' AND error LIKE '自动恢复:%'",
                    (int(sid),),
                ).fetchone()[0]
                or 0
            )
            con.execute(
                """UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',error=?,last_update_at=?
                   WHERE segment_id=? AND command_id=? AND status<>'detected'""",
                (f"自动恢复: {tag_reason}", now, int(sid), str(cmd)),
            )
            _drop_pending_dl(str(cmd), int(sid))
            if prior_auto >= retry_cap:
                con.execute(
                    """UPDATE flow_segments SET generation_command='',flow_status='失败',flow_channel_key='',
                              flow_error=? WHERE id=? AND generation_command=?""",
                    (f"连续 {retry_cap} 次生成超时，已停止自动重试（{fail_label}）", int(sid), str(cmd)),
                )
                return False
            con.execute(
                """UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_channel_key='',
                          flow_error='' WHERE id=? AND generation_command=?""",
                (int(sid), str(cmd)),
            )
            if has_redo and str(qc_status or '') == '退回':
                con.execute("INSERT OR IGNORE INTO flow_redo(segment_id) VALUES(?)", (int(sid),))
            return True

        # --- Guardrail 2: Uncertain / unconfirmed `planned`/`queued` dispatches past grace window ---
        uncertain_rows = con.execute(
            """SELECT d.id dispatch_id,d.segment_id,d.command_id,d.release_at,d.last_update_at,
                      fs.qc_status,
                      CAST(strftime('%s', NULLIF(TRIM(COALESCE(fs.flow_submitted_at,'')),'')) AS REAL) submitted_epoch,
                      CAST(strftime('%s', NULLIF(TRIM(COALESCE(d.created_at,'')),'')) AS REAL) dispatch_epoch
                 FROM flow_dispatches d
                 JOIN flow_segments fs ON fs.id=d.segment_id AND fs.generation_command=d.command_id
                 JOIN videos v ON v.id=fs.video_id
                 JOIN hosts h ON h.id=v.host_id
                 JOIN recipients r ON r.id=h.recipient_id
                WHERE d.status IN ('planned','queued')
                  AND fs.flow_status IN ('待生成','已准备')
                  AND TRIM(COALESCE(fs.flow_output_path,''))=''
                  AND NOT EXISTS (SELECT 1 FROM flow_outputs fo WHERE fo.segment_id=fs.id AND fo.command_id=d.command_id)"""
            + date_sql,
            date_args,
        ).fetchall()
        seen_uncertain = set()
        for row in uncertain_rows:
            sid = int(row['segment_id'])
            cmd = str(row['command_id'] or '')
            if not cmd or cmd in published or (sid, cmd) in seen_uncertain:
                continue
            # V-timeout: a row whose current command already reached a real submit attempt
            # (flow_submitted_at written by a running/success receipt) is handled only by the
            # fixed per-video timeout in Guardrail 3, never by this short grace window.
            _sub = float(row['submitted_epoch'] or 0)
            _dsp = float(row['dispatch_epoch'] or 0)
            if _sub and (not _dsp or _sub + 1 >= _dsp):
                continue
            ref_ts = max(float(row['last_update_at'] or 0), float(row['release_at'] or 0))
            if ref_ts > 0 and (now - ref_ts) < uncertain_grace:
                continue
            seen_uncertain.add((sid, cmd))
            if _apply_segment_recovery(sid, cmd, row['qc_status'], '提交待确认超时未生成', '提交状态未确认，请手动检查'):
                uncertain_requeued.append(sid)
            else:
                uncertain_failed.append(sid)

        # --- Guardrail 3 (V-timeout): fixed per-video timeout, all dates ---
        # 每个视频从插件真实点击生成（flow_submitted_at）开始固定计时；之后的任何回执都不会重置计时，
        # 也不再因为命令仍在 Bridge 发布列表 / 仍占着通道而跳过。
        # 超时且本地没有扫描到视频：第一次自动重新提交；再次超时就标记「失败」进入异常，不再自动重做。
        # 最终失败保留 generation_command，迟到的视频仍可被下载回执或文件夹扫描收下并转为「已完成」。
        timeout_minutes = max(1, int(round(zombie_timeout / 60.0)))
        timeout_rows = con.execute(
            """SELECT fs.id segment_id,fs.generation_command command_id,fs.qc_status,
                      CAST(strftime('%s', NULLIF(TRIM(COALESCE(fs.flow_submitted_at,'')),'')) AS REAL) submitted_epoch,
                      (SELECT MAX(CAST(strftime('%s', NULLIF(TRIM(COALESCE(d.created_at,'')),'')) AS REAL)) FROM flow_dispatches d
                         WHERE d.segment_id=fs.id AND d.command_id=fs.generation_command) dispatch_epoch,
                      (SELECT MAX(CASE WHEN d.status='downloading' THEN COALESCE(d.last_update_at,0) ELSE 0 END) FROM flow_dispatches d
                         WHERE d.segment_id=fs.id AND d.command_id=fs.generation_command) downloading_ts
                 FROM flow_segments fs
                WHERE TRIM(COALESCE(fs.generation_command,''))<>''
                  AND fs.flow_status IN ('已准备','已提交','生成中')
                  AND TRIM(COALESCE(fs.flow_output_path,''))=''
                  AND NOT EXISTS (SELECT 1 FROM flow_outputs fo WHERE fo.segment_id=fs.id AND fo.command_id=fs.generation_command)"""
        ).fetchall()
        for row in timeout_rows:
            sid = int(row['segment_id'])
            cmd = str(row['command_id'] or '')
            submitted = float(row['submitted_epoch'] or 0)
            dispatched = float(row['dispatch_epoch'] or 0)
            if not cmd or not submitted:
                continue   # 还没真正点击生成（仍在插件队列里），不计时
            if dispatched and submitted + 1 < dispatched:
                continue   # flow_submitted_at 是上一次尝试留下的，当前命令还没点击生成
            if (now - submitted) < zombie_timeout:
                continue
            dl_ts = float(row['downloading_ts'] or 0)
            if dl_ts > 0 and (now - dl_ts) < 120.0:
                continue   # 正在下载中，给下载收尾留一点时间
            prior_timeouts = int(
                con.execute(
                    "SELECT COUNT(DISTINCT command_id) FROM flow_dispatches WHERE segment_id=? AND status='cancelled' AND error LIKE '自动恢复: 生成超时%'",
                    (sid,),
                ).fetchone()[0]
                or 0
            )
            if prior_timeouts >= retry_cap:
                msg = (f"连续 {prior_timeouts + 1} 次生成超时，已停止自动重试"
                       f"（每次等待 {timeout_minutes} 分钟仍未下载到视频；视频若稍后下载完成会自动转为已完成）")
                con.execute(
                    """UPDATE flow_dispatches SET error=?,last_update_at=?
                       WHERE segment_id=? AND command_id=? AND status NOT IN ('detected','cancelled')""",
                    (f"生成超时：{timeout_minutes} 分钟未下载到视频", now, sid, cmd),
                )
                cur = con.execute(
                    """UPDATE flow_segments SET flow_status='失败',flow_error=?
                       WHERE id=? AND generation_command=? AND flow_status IN ('已准备','已提交','生成中')""",
                    (msg, sid, cmd),
                )
                if int(cur.rowcount or 0):
                    zombie_failed.append(sid)
                continue
            con.execute(
                """UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',error=?,last_update_at=?
                   WHERE segment_id=? AND command_id=? AND status<>'detected'""",
                (f"自动恢复: 生成超时 {timeout_minutes} 分钟未下载到视频，自动重新提交", now, sid, cmd),
            )
            _drop_pending_dl(cmd, sid)
            cur = con.execute(
                """UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_channel_key='',
                          flow_error='' WHERE id=? AND generation_command=?""",
                (sid, cmd),
            )
            if int(cur.rowcount or 0):
                if has_redo and str(row['qc_status'] or '') == '退回':
                    con.execute("INSERT OR IGNORE INTO flow_redo(segment_id) VALUES(?)", (sid,))
                zombie_requeued.append(sid)

        if retired_commands:
            setting = con.execute("SELECT value FROM app_settings WHERE key='flow_host_jobs_v124'").fetchone()
            if setting:
                try:
                    jobs = _json.loads(setting['value'] or '[]')
                    if isinstance(jobs, list):
                        retired_set = set(retired_commands)
                        jobs = [j for j in jobs if str((j or {}).get('command_id') or '') not in retired_set]
                        con.execute(
                            "UPDATE app_settings SET value=? WHERE key='flow_host_jobs_v124'",
                            (_json.dumps(jobs, ensure_ascii=False),),
                        )
                except Exception:
                    pass

    return {
        'released_channels': sorted(set(released_channels)),
        'retired_commands': sorted(set(retired_commands)),
        'uncertain_requeued': sorted(set(uncertain_requeued)),
        'uncertain_failed': sorted(set(uncertain_failed)),
        'zombie_requeued': sorted(set(zombie_requeued)),
        'zombie_failed': sorted(set(zombie_failed)),
    }


def channel_pool_load(channel_key):
    with connect() as con:
        row=con.execute("SELECT COUNT(*) n FROM flow_dispatches d JOIN flow_segments fs ON fs.id=d.segment_id AND fs.generation_command=d.command_id WHERE d.channel_key=? AND d.status IN ('planned','queued','submitted','downloading')",(str(channel_key),)).fetchone()
    return int(row['n'] or 0)


def clear_planned_dispatches(segment_ids=None):
    with connect() as con:
        if segment_ids:
            ids=[int(x) for x in segment_ids]; q=','.join('?' for _ in ids)
            con.execute(f"DELETE FROM flow_dispatches WHERE status='planned' AND segment_id IN ({q})",ids)
        else: con.execute("DELETE FROM flow_dispatches WHERE status='planned'")


def create_dispatch(segment_id, channel_key, command_id, dispatch_order, round_no, task_name, expected_filename, status='planned'):
    with connect() as con:
        con.execute("""INSERT OR REPLACE INTO flow_dispatches(segment_id,channel_key,command_id,dispatch_order,round_no,task_name,expected_filename,status,download_path,error,created_at,submitted_at,detected_at)
            VALUES(?,?,?,?,?,?,?,?, '', '', CURRENT_TIMESTAMP, '', '')""",
            (int(segment_id),str(channel_key),str(command_id),int(dispatch_order),int(round_no),str(task_name),str(expected_filename),str(status)))


def list_dispatches(channel_key=None, statuses=None, command_id=None, *, work_date=None):
    where=[];args=[]
    if channel_key: where.append('d.channel_key=?');args.append(str(channel_key))
    if command_id: where.append('d.command_id=?');args.append(str(command_id))
    if statuses:
        sts=list(statuses);where.append('d.status IN (%s)'%','.join('?' for _ in sts));args.extend(sts)
    clause=(' WHERE '+' AND '.join(where)) if where else ''
    with read_connection(work_date) as con:
        return con.execute(f"""SELECT d.*,fs.generation_command,fs.seg_seq,fs.flow_status,fs.flow_retry_count,v.seq video_seq,v.image_path,
            h.id host_id,h.name host_name,r.id recipient_id,r.name recipient_name
            FROM flow_dispatches d JOIN flow_segments fs ON fs.id=d.segment_id JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            {clause} ORDER BY d.channel_key,d.dispatch_order,d.round_no""",args).fetchall()




def list_live_flow_dispatches(*, work_date=None, max_age_minutes=30):
    """Return display-only, genuinely active Flow dispatches.

    Historical ``submitted`` rows can survive a browser/plugin restart.  They must not
    keep the dashboard/channel cards looking busy forever.  Scheduler ownership is not
    changed here; this helper is deliberately read-only and is only a runtime UI truth
    source.  A dispatch is visible as live only when it still owns the segment's current
    generation_command and has had activity within the freshness window.
    """
    minutes=max(5,int(max_age_minutes or 30))
    with read_connection(work_date) as con:
        return con.execute("""SELECT d.*,fs.generation_command,fs.seg_seq,fs.flow_status,fs.flow_retry_count,
            v.seq video_seq,v.image_path,h.id host_id,h.name host_name,r.id recipient_id,r.name recipient_name
            FROM flow_dispatches d
            JOIN flow_segments fs ON fs.id=d.segment_id
            JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id
            JOIN recipients r ON r.id=h.recipient_id
            WHERE d.command_id=fs.generation_command
              AND d.status IN ('submitted','downloading')
              AND datetime(COALESCE(NULLIF(d.submitted_at,''),NULLIF(d.detected_at,''),d.created_at))
                    >= datetime('now', ?)
            ORDER BY d.channel_key,d.dispatch_order,d.round_no""",(f'-{minutes} minutes',)).fetchall()

def get_dispatch_by_filename(channel_key, filename):
    name=str(filename)
    with connect() as con:
        return con.execute("""SELECT d.*,fs.generation_command,fs.flow_retry_count,fs.seg_seq,v.seq video_seq,v.id video_id,
            h.id host_id,h.name host_name,r.id recipient_id,r.name recipient_name,r.work_date
            FROM flow_dispatches d JOIN flow_segments fs ON fs.id=d.segment_id JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            WHERE d.channel_key=? AND d.expected_filename=? ORDER BY d.id DESC LIMIT 1""",(str(channel_key),name)).fetchone()


def update_dispatch(dispatch_id, *, status=None, download_path=None, error=None, submitted=False, detected=False):
    fields=[];args=[]
    for val,name in [(status,'status'),(download_path,'download_path'),(error,'error')]:
        if val is not None: fields.append(f'{name}=?');args.append(val)
    if submitted: fields.append('submitted_at=CURRENT_TIMESTAMP')
    if detected: fields.append('detected_at=CURRENT_TIMESTAMP')
    if not fields:return
    args.append(int(dispatch_id))
    with connect() as con: con.execute(f"UPDATE flow_dispatches SET {','.join(fields)} WHERE id=?",args)


def mark_dispatch_status(segment_id, command_id, round_no, status, error=''):
    with connect() as con:
        con.execute("UPDATE flow_dispatches SET status=?,error=?,submitted_at=CASE WHEN ?='submitted' THEN CURRENT_TIMESTAMP ELSE submitted_at END WHERE segment_id=? AND command_id=? AND round_no=?",
                    (status,error or '',status,int(segment_id),str(command_id),int(round_no or 1)))


def channel_dispatch_summary(channel_key, *, work_date=None):
    with read_connection(work_date) as con:
        rows=con.execute("SELECT status,COUNT(*) n FROM flow_dispatches WHERE channel_key=? GROUP BY status",(str(channel_key),)).fetchall()
    d={r['status']:int(r['n']) for r in rows}
    return {'active':sum(d.get(x,0) for x in ('planned','queued','submitted','downloading')),'done':d.get('detected',0),'failed':d.get('failed',0),'counts':d}


# ===== V0.13.3 production pipeline / dynamic browser pool / QC cache =====
import json as _json
import re as _re
import time as _time


def _browser_pool_default_config():
    try:
        a_count=max(1,int(get_setting('flow_pool_normal_count','7') or 7))
    except Exception:
        a_count=7
    groups=[{
        'id':'A','enabled':True,'normal_count':a_count,
        'fast_enabled':get_setting('flow_pool_fast_enabled','0')=='1',
        'profile':get_setting('flow_browser_a_profile',get_setting('chrome_profile_directory','Default')) or 'Default',
    }]
    if get_setting('flow_browser_b_enabled','0')=='1' or int(get_setting('flow_pool_b_normal_count','0') or 0)>0:
        groups.append({
            'id':'B','enabled':get_setting('flow_browser_b_enabled','0')=='1',
            'normal_count':max(0,int(get_setting('flow_pool_b_normal_count','0') or 0)),
            'fast_enabled':get_setting('flow_pool_b_fast_enabled','0')=='1',
            'profile':get_setting('flow_browser_b_profile','Default') or 'Default',
        })
    return groups


def list_browser_groups(include_disabled=True):
    raw=get_setting('flow_browser_pool_json','').strip()
    groups=[]
    if raw:
        try:
            groups=_json.loads(raw)
        except Exception:
            groups=[]
    if not isinstance(groups,list) or not groups:
        groups=_browser_pool_default_config()
        set_setting('flow_browser_pool_json',_json.dumps(groups,ensure_ascii=False))
    out=[]
    seen=set()
    for g in groups:
        if not isinstance(g,dict):
            continue
        gid=str(g.get('id') or '').strip().upper()
        if not gid or gid in seen:
            continue
        seen.add(gid)
        row={
            'id':gid,
            'enabled':bool(g.get('enabled',True)),
            'normal_count':max(0,int(g.get('normal_count') or 0)),
            'fast_enabled':bool(g.get('fast_enabled',False)),
            'fast_count':max(0,int(g.get('fast_count',1 if g.get('fast_enabled') else 0) or 0)),
            'profile':str(g.get('profile') or 'Default'),
        }
        if include_disabled or row['enabled']:
            out.append(row)
    # Stable natural-ish order A,B,C... then custom names.
    out.sort(key=lambda x:(len(x['id']),x['id']))
    return out


def save_browser_groups(groups):
    clean=[]
    for g in groups:
        clean.append({
            'id':str(g['id']).strip().upper(),
            'enabled':bool(g.get('enabled',True)),
            'normal_count':max(0,int(g.get('normal_count') or 0)),
            'fast_enabled':bool(g.get('fast_enabled',False)),
            'fast_count':max(0,int(g.get('fast_count',1 if g.get('fast_enabled') else 0) or 0)),
            'profile':str(g.get('profile') or 'Default'),
        })
    set_setting('flow_browser_pool_json',_json.dumps(clean,ensure_ascii=False))
    # legacy mirrors keep old code/settings readable
    a=next((g for g in clean if g['id']=='A'),None)
    if a:
        set_setting('flow_pool_normal_count',str(max(1,a['normal_count'])))
        set_setting('flow_pool_fast_enabled','1' if a['fast_enabled'] else '0')
        set_setting('flow_browser_a_profile',a['profile'])
        set_setting('chrome_profile_directory',a['profile'])
    b=next((g for g in clean if g['id']=='B'),None)
    set_setting('flow_browser_b_enabled','1' if b and b['enabled'] else '0')
    set_setting('flow_pool_b_normal_count',str(b['normal_count'] if b else 0))
    set_setting('flow_pool_b_fast_enabled','1' if b and b['fast_enabled'] else '0')
    if b: set_setting('flow_browser_b_profile',b['profile'])


def _next_browser_id(existing):
    # A..Z, then AA..AZ, BA... no practical software cap.
    used=set(existing)
    n=1
    while True:
        x=n; chars=[]
        while x:
            x,rem=divmod(x-1,26); chars.append(chr(65+rem))
        gid=''.join(reversed(chars))
        if gid not in used: return gid
        n+=1


def add_browser_group(profile='Default', normal_count=0, fast_enabled=False):
    groups=list_browser_groups(True)
    gid=_next_browser_id([g['id'] for g in groups])
    groups.append({'id':gid,'enabled':True,'normal_count':max(0,int(normal_count or 0)),'fast_enabled':bool(fast_enabled),'profile':profile or 'Default'})
    save_browser_groups(groups); ensure_channel_pool()
    return gid


def update_browser_group(group_id, **changes):
    gid=str(group_id).upper(); groups=list_browser_groups(True); found=False
    for g in groups:
        if g['id']==gid:
            for k in ('enabled','normal_count','fast_enabled','fast_count','profile'):
                if k in changes:
                    g[k]=changes[k]
            found=True; break
    if not found: raise ValueError(f'找不到浏览器 {gid}')
    save_browser_groups(groups); ensure_channel_pool()


def remove_browser_group(group_id):
    gid=str(group_id).upper()
    if gid=='A': raise ValueError('浏览器A是兼容主浏览器，不能删除；可以关闭其额外通道。')
    groups=[g for g in list_browser_groups(True) if g['id']!=gid]
    save_browser_groups(groups)
    with connect() as con:
        con.execute("UPDATE flow_channel_pool SET enabled=0 WHERE browser_group=?",(gid,))
    ensure_channel_pool()


def channel_browser_group(channel_key):
    key=str(channel_key or '').strip().upper()
    if _re.match(r'^(CH\d+|R\d+)$',key): return 'A'
    m=_re.match(r'^([A-Z]+)-(?:CH|R)\d+$',key)
    return m.group(1) if m else 'A'


def browser_profile(group_id):
    gid=str(group_id).upper()
    g=next((x for x in list_browser_groups(True) if x['id']==gid),None)
    return (g or {}).get('profile','Default')


def ensure_channel_pool(normal_count=None, include_fast=None, *, browser_b_enabled=None, browser_b_normal_count=None, browser_b_fast_enabled=None):
    # Apply legacy caller changes to A/B, then materialize arbitrary browser groups.
    groups=list_browser_groups(True)
    a=next((g for g in groups if g['id']=='A'),None)
    if not a:
        a={'id':'A','enabled':True,'normal_count':7,'fast_enabled':False,'profile':'Default'}; groups.append(a)
    if normal_count is not None:
        try: a['normal_count']=max(1,int(normal_count))
        except Exception: pass
    if include_fast is not None: a['fast_enabled']=bool(include_fast)
    b=next((g for g in groups if g['id']=='B'),None)
    if any(v is not None for v in (browser_b_enabled,browser_b_normal_count,browser_b_fast_enabled)):
        if not b:
            b={'id':'B','enabled':False,'normal_count':0,'fast_enabled':False,'profile':get_setting('flow_browser_b_profile','Default') or 'Default'}; groups.append(b)
        if browser_b_enabled is not None: b['enabled']=bool(browser_b_enabled)
        if browser_b_normal_count is not None: b['normal_count']=max(0,int(browser_b_normal_count or 0))
        if browser_b_fast_enabled is not None: b['fast_enabled']=bool(browser_b_fast_enabled)
    save_browser_groups(groups)

    removed=set(json.loads(get_setting('flow_removed_channels','[]') or '[]'))
    desired={}
    order=0
    for g in list_browser_groups(True):
        gid=g['id']; enabled=bool(g['enabled'])
        if not enabled: continue
        for i in range(1,max(0,int(g['normal_count']))+1):
            key=f'CH{i}' if gid=='A' else f'{gid}-CH{i}'
            order+=1; desired[key]=(gid,'normal',order)
        if g['fast_enabled']:
            for i in range(1,max(1,int(g.get('fast_count') or 0))+1):
                key=f'R{i}' if gid=='A' else f'{gid}-R{i}'
                order+=1; desired[key]=(gid,'fast',900000+order)
    with connect() as con:
        # Disable managed generated channel keys before re-enabling desired set.
        rows=con.execute("SELECT channel_key FROM flow_channel_pool").fetchall()
        for r in rows:
            key=str(r['channel_key'])
            if _re.match(r'^(?:[A-Z]+-)?(?:CH|R)\d+$',key,_re.I):
                con.execute("UPDATE flow_channel_pool SET enabled=0 WHERE channel_key=?",(key,))
        for key,(gid,role,sort_order) in desired.items():
            if key in removed: continue
            con.execute("""INSERT OR IGNORE INTO flow_channel_pool(channel_key,role,browser_group,download_subdir,sort_order,enabled)
                           VALUES(?,?,?,?,?,1)""",(key,role,gid,key,sort_order))
            con.execute("""UPDATE flow_channel_pool SET role=?,browser_group=?,download_subdir=CASE WHEN download_subdir='' THEN ? ELSE download_subdir END,
                           sort_order=?,enabled=1 WHERE channel_key=?""",(role,gid,key,sort_order,key))


def list_channel_pool(enabled_only=False):
    ensure_channel_pool()
    clause=' WHERE enabled=1' if enabled_only else ''
    with connect() as con:
        return con.execute(f"""SELECT * FROM flow_channel_pool{clause}
            ORDER BY browser_group, CASE WHEN role='normal' THEN 0 ELSE 1 END, sort_order, channel_key""").fetchall()


def channel_pool_normal_count():
    a=next((g for g in list_browser_groups(True) if g['id']=='A'),None)
    return max(1,int((a or {}).get('normal_count',7)))


def browser_b_enabled():
    b=next((g for g in list_browser_groups(True) if g['id']=='B'),None); return bool(b and b['enabled'])

def browser_b_normal_count():
    b=next((g for g in list_browser_groups(True) if g['id']=='B'),None); return int((b or {}).get('normal_count',0))

def browser_b_fast_enabled():
    b=next((g for g in list_browser_groups(True) if g['id']=='B'),None); return bool(b and b['fast_enabled'])


def add_pool_channel(browser='A', role='normal'):
    gid=str(browser or 'A').upper(); groups=list_browser_groups(True)
    g=next((x for x in groups if x['id']==gid),None)
    if not g:
        groups.append({'id':gid,'enabled':True,'normal_count':0,'fast_enabled':False,'profile':'Default'}); g=groups[-1]
    g['enabled']=True

    # Reuse the smallest channel number that the user previously removed.
    # This keeps existing channel keys stable while making newly added channels
    # fill holes (for example CH1, CH2, CH4 -> new channel CH3). If all
    # channels were removed, the next new one starts again at CH1.
    try:
        removed=set(json.loads(get_setting('flow_removed_channels','[]') or '[]'))
    except Exception:
        removed=set()
    prefix='' if gid=='A' else f'{gid}-'

    if str(role)=='fast':
        current=max(int(g.get('fast_count') or 0),1 if g.get('fast_enabled') else 0)
        reusable=next((i for i in range(1,current+1) if f'{prefix}R{i}' in removed),None)
        if reusable is not None:
            key=f'{prefix}R{reusable}'
            removed.discard(key)
            set_setting('flow_removed_channels',json.dumps(sorted(removed)))
            g['fast_enabled']=True
            suffix=f'R{reusable}'
        else:
            g['fast_count']=current+1
            g['fast_enabled']=True
            suffix=f"R{g['fast_count']}"
    else:
        current=max(0,int(g.get('normal_count') or 0))
        reusable=next((i for i in range(1,current+1) if f'{prefix}CH{i}' in removed),None)
        if reusable is not None:
            key=f'{prefix}CH{reusable}'
            removed.discard(key)
            set_setting('flow_removed_channels',json.dumps(sorted(removed)))
            suffix=f'CH{reusable}'
        else:
            g['normal_count']=current+1
            suffix=f"CH{g['normal_count']}"

    save_browser_groups(groups); ensure_channel_pool()
    return suffix if gid=='A' else f'{gid}-{suffix}'


def set_browser_b_enabled(enabled):
    groups=list_browser_groups(True); b=next((g for g in groups if g['id']=='B'),None)
    if not b:
        groups.append({'id':'B','enabled':bool(enabled),'normal_count':0,'fast_enabled':False,'profile':'Default'})
    else: b['enabled']=bool(enabled)
    save_browser_groups(groups); ensure_channel_pool()


def set_browser_b_fast_enabled(enabled):
    groups=list_browser_groups(True); b=next((g for g in groups if g['id']=='B'),None)
    if not b:
        b={'id':'B','enabled':True,'normal_count':0,'fast_enabled':bool(enabled),'profile':'Default'}; groups.append(b)
    else:
        b['enabled']=True; b['fast_enabled']=bool(enabled)
    save_browser_groups(groups); ensure_channel_pool()


def set_channel_health(channel_key, *, health=None, page_status=None, failure_delta=0, reset_failures=False, quarantine_until=None, success=False):
    fields=[]; args=[]
    if health is not None: fields.append('health_status=?'); args.append(health)
    if page_status is not None: fields.append('page_status=?'); args.append(page_status)
    if reset_failures: fields.append('consecutive_failures=0')
    elif failure_delta: fields.append('consecutive_failures=MAX(0,consecutive_failures+?)'); args.append(int(failure_delta))
    if quarantine_until is not None: fields.append('quarantine_until=?'); args.append(float(quarantine_until))
    if success: fields.append('last_success_at=?'); args.append(_time.time())
    if not fields:return
    args.append(str(channel_key))
    with connect() as con: con.execute(f"UPDATE flow_channel_pool SET {','.join(fields)} WHERE channel_key=?",args)


def channel_is_usable(row, now=None):
    now=float(now or _time.time())
    return bool(row and row['enabled'] and float(row['quarantine_until'] or 0)<=now)


CHANNEL_DEAD_AFTER_SECONDS=120
DEAD_QUEUE_GRACE_SECONDS=180
STALE_QUEUE_SECONDS=300


def retire_ancient_submitted(max_age_seconds=6*3600):
    """Mark days-old 'submitted' dispatches as stale so UI counters stop showing them as generating.

    Only the dispatch rows change (never the segments), so no regeneration is triggered.
    Returns the number of retired rows.
    """
    limit=_time.time()-float(max_age_seconds)
    with connect() as con:
        cur=con.execute("""UPDATE flow_dispatches SET status='stale',stage='STALE',last_update_at=?,
                    error=CASE WHEN COALESCE(error,'')='' THEN '超过6小时无结果，已标记为过期' ELSE error END
                    WHERE status='submitted' AND COALESCE(last_update_at,0)>0 AND last_update_at<?""",(_time.time(),limit))
        return int(cur.rowcount or 0)


def adopt_orphan_outputs():
    """Apply downloaded outputs that were recorded but never reached the segment.

    Symptom this repairs: ``flow_outputs`` holds a readable file for the segment's *current*
    command and the dispatch is ``detected``, yet the segment still says 待生成/生成中 with no
    output path.  Such a segment is skipped by the scheduler (it has a command) and counted as
    unfinished forever.  Only readable files of the current, non-obsolete command are adopted;
    already completed/QC-passed segments and superseded commands are never touched.
    Returns the adopted segment ids.
    """
    import os
    adopted=[]
    with connect() as con:
        rows=con.execute("""SELECT fs.id sid,fs.generation_command cmd,fs.qc_status qc,fo.output_path path
                FROM flow_segments fs
                JOIN flow_outputs fo ON fo.segment_id=fs.id AND fo.command_id=fs.generation_command
               WHERE COALESCE(fs.generation_command,'')<>''
                 AND fs.flow_status IN ('待生成','已准备','已提交','生成中','下载中','失败','下载失败')
                 AND COALESCE(fs.flow_output_path,'')=''
                 AND COALESCE(fo.qc_status,'')<>'旧版本失效'
                 AND NOT EXISTS(SELECT 1 FROM flow_obsolete_commands oc WHERE oc.command_id=fs.generation_command)
                 AND NOT EXISTS(SELECT 1 FROM flow_redo rr WHERE rr.segment_id=fs.id AND COALESCE(fs.qc_status,'')='退回')
               ORDER BY fo.id""").fetchall()
        done=set()
        for r in rows:
            sid=int(r['sid']); path=str(r['path'] or '')
            if sid in done or not path: continue
            try:
                if not (os.path.isfile(path) and os.path.getsize(path)>0): continue
            except OSError:
                continue
            con.execute("""UPDATE flow_segments SET flow_status='已完成',flow_output_path=?,flow_output_url='',
                        flow_error='',flow_completed_at=CURRENT_TIMESTAMP,
                        qc_status=CASE WHEN COALESCE(qc_status,'')='通过' THEN '通过' ELSE '待质检' END
                        WHERE id=? AND COALESCE(flow_output_path,'')=''""",(path,sid))
            con.execute("""UPDATE flow_dispatches SET status='detected',stage='QC_PENDING',download_path=CASE WHEN COALESCE(download_path,'')='' THEN ? ELSE download_path END,
                        last_update_at=? WHERE segment_id=? AND command_id=? AND status NOT IN ('detected')""",(path,_time.time(),sid,str(r['cmd'])))
            done.add(sid); adopted.append(sid)
    return adopted



def channel_is_alive(row, now=None, max_age=CHANNEL_DEAD_AFTER_SECONDS):
    """True only when the channel's browser tab heartbeat is recent."""
    now=float(now or _time.time())
    try: seen=float(row['last_seen'] or 0)
    except Exception: seen=0.0
    return bool(seen and now-seen<=float(max_age))


def failover_dead_channel_queues(now=None, max_age=CHANNEL_DEAD_AFTER_SECONDS, grace=DEAD_QUEUE_GRACE_SECONDS):
    """Take never-submitted queued work away from channels whose tab stopped heartbeating.

    Only ``queued/planned`` dispatches older than ``grace`` seconds are touched; anything
    already submitted to Flow stays with its channel. Returns the cancelled command ids so
    the caller can also drop them from the live Bridge job list.
    """
    now=float(now or _time.time())
    cancelled=[]
    with connect() as con:
        published=_published_generation_commands(con)
        cmds_by_channel={}
        for r in con.execute("SELECT channel_key,last_seen,task_command_id FROM flow_channel_pool WHERE enabled=1").fetchall():
            key=str(r['channel_key'])
            alive=channel_is_alive(r,now,max_age)
            limit=now-float(grace if not alive else STALE_QUEUE_SECONDS)
            rows=con.execute("""SELECT DISTINCT command_id FROM flow_dispatches
                    WHERE channel_key=? AND status IN ('planned','queued') AND COALESCE(last_update_at,0)<?""",(key,limit)).fetchall()
            cmds=[str(x[0]) for x in rows]
            if alive:
                # An online channel keeps commands that Bridge still publishes or that it currently owns.
                cmds=[c for c in cmds if c not in published and c!=str(r['task_command_id'] or '')]
            if cmds: cmds_by_channel[key]=cmds
        for key,cmds in cmds_by_channel.items():
            for cmd in cmds:
                segs=[int(r[0]) for r in con.execute("SELECT DISTINCT segment_id FROM flow_dispatches WHERE command_id=? AND status IN ('planned','queued')",(cmd,)).fetchall()]
                con.execute("""UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',last_update_at=?,
                            error='排队超时/通道失联，任务改派给其他通道' WHERE command_id=? AND status IN ('planned','queued')""",(now,cmd))
                for sid in segs:
                    con.execute("""UPDATE flow_segments SET generation_command='',flow_channel_key='',flow_error=''
                                WHERE id=? AND flow_status IN ('待生成','已准备') AND COALESCE(flow_output_path,'')=''
                                  AND (generation_command=? OR generation_command='')""",(sid,cmd))
                con.execute("""UPDATE flow_channel_pool SET task_command_id='',last_status='未连接 · 排队任务已改派'
                            WHERE channel_key=? AND task_command_id=?""",(key,cmd))
                con.execute("""UPDATE flow_channel_pool SET upload_state='idle',upload_command_id=''
                            WHERE channel_key=? AND upload_command_id=? AND upload_state IN ('queued','uploading')""",(key,cmd))
                cancelled.append(cmd)
    return cancelled


def create_dispatch(segment_id, channel_key, command_id, dispatch_order, round_no, task_name, expected_filename, status='planned', release_at=0):
    dispatch_uid=f"S{int(segment_id)}:{command_id}:{int(round_no)}"
    with connect() as con:
        con.execute("""INSERT OR REPLACE INTO flow_dispatches(segment_id,channel_key,command_id,dispatch_order,round_no,task_name,expected_filename,status,download_path,error,created_at,submitted_at,detected_at,dispatch_uid,stage,release_at,last_update_at)
            VALUES(?,?,?,?,?,?,?,?, '', '', CURRENT_TIMESTAMP, '', '', ?, ?, ?, ?)""",
            (int(segment_id),str(channel_key),str(command_id),int(dispatch_order),int(round_no),str(task_name),str(expected_filename),str(status),dispatch_uid,'QUEUED',float(release_at or 0),_time.time()))


def mark_dispatch_status(segment_id, command_id, round_no, status, error=''):
    stage={'planned':'QUEUED','queued':'QUEUED','submitted':'SUBMITTED','downloading':'DOWNLOADING','detected':'QC_PENDING','failed':'FAILED'}.get(str(status),str(status).upper())
    with connect() as con:
        con.execute("""UPDATE flow_dispatches SET status=?,error=?,stage=?,last_update_at=?,
                    submitted_at=CASE WHEN ?='submitted' THEN CURRENT_TIMESTAMP ELSE submitted_at END
                    WHERE segment_id=? AND command_id=? AND round_no=?""",
                    (status,error or '',stage,_time.time(),status,int(segment_id),str(command_id),int(round_no or 1)))


def update_dispatch(dispatch_id, *, status=None, download_path=None, error=None, submitted=False, detected=False, stage=None, release_at=None):
    fields=[];args=[]
    for val,name in [(status,'status'),(download_path,'download_path'),(error,'error'),(stage,'stage'),(release_at,'release_at')]:
        if val is not None: fields.append(f'{name}=?');args.append(val)
    if submitted: fields.append('submitted_at=CURRENT_TIMESTAMP')
    if detected: fields.append('detected_at=CURRENT_TIMESTAMP')
    fields.append('last_update_at=?'); args.append(_time.time())
    args.append(int(dispatch_id))
    with connect() as con: con.execute(f"UPDATE flow_dispatches SET {','.join(fields)} WHERE id=?",args)


def dispatch_seen(dispatch_uid):
    with connect() as con:
        r=con.execute("SELECT id,status,stage FROM flow_dispatches WHERE dispatch_uid=?",(dispatch_uid,)).fetchone()
    return r


# ----- Task source / default creator -----
def default_creator():
    return get_setting('default_creator', get_setting('creator','')) or ''


def set_default_creator(name):
    set_setting('default_creator',(name or '').strip())
    set_setting('creator',(name or '').strip())


def source_task_exists(source_task_id,source_row):
    with connect() as con:
        return bool(con.execute("SELECT 1 FROM source_tasks WHERE source_task_id=? AND source_row=?",(source_task_id or '',source_row or '')).fetchone())


def mark_source_task(source_task_id,source_row,video_id,status):
    with connect() as con:
        con.execute("""INSERT INTO source_tasks(source_task_id,source_row,video_id,status) VALUES(?,?,?,?)
                       ON CONFLICT(source_task_id,source_row) DO UPDATE SET video_id=excluded.video_id,status=excluded.status""",
                    (source_task_id or '',source_row or '',int(video_id),status or '已导入'))


def find_or_create_recipient(name,fixed_code,creator,work_date):
    with connect() as con:
        r=con.execute("SELECT id FROM recipients WHERE name=? AND work_date=? ORDER BY id DESC LIMIT 1",(name.strip(),work_date)).fetchone()
        if r:return int(r['id'])
        cur=con.execute("INSERT INTO recipients(name,fixed_code,creator,work_date) VALUES(?,?,?,?)",(name.strip(),fixed_code or 'ZB',creator or '',work_date))
        return int(cur.lastrowid)


def find_or_create_host(recipient_id,name):
    with connect() as con:
        r=con.execute("SELECT id FROM hosts WHERE recipient_id=? AND name=? ORDER BY id LIMIT 1",(int(recipient_id),name.strip())).fetchone()
        if r:return int(r['id'])
        cur=con.execute("INSERT INTO hosts(recipient_id,name,video_count,image_path) VALUES(?,?,0,'')",(int(recipient_id),name.strip()))
        return int(cur.lastrowid)


def add_video_to_host(host_id, *, original_script='', chinese='', source_task_id='', source_row='', drive_url=''):
    with connect() as con:
        seq=int(con.execute("SELECT COALESCE(MAX(seq),0)+1 n FROM videos WHERE host_id=?",(int(host_id),)).fetchone()['n'])
        cur=con.execute("""INSERT INTO videos(host_id,seq,script,chinese_script,image_path,original_script,production_script,source_task_id,source_row,source_drive_url)
                           VALUES(?,?,?,?, '',?,?,?,?,?)""",
                        (int(host_id),seq,original_script or '',chinese or '',original_script or '',original_script or '',source_task_id or '',source_row or '',drive_url or ''))
        con.execute("UPDATE hosts SET video_count=(SELECT COUNT(*) FROM videos WHERE host_id=?) WHERE id=?",(int(host_id),int(host_id)))
        return int(cur.lastrowid)


def video_seq(video_id):
    with connect() as con:
        r=con.execute("SELECT seq FROM videos WHERE id=?",(int(video_id),)).fetchone()
    return int(r['seq']) if r else 0


def update_video_source_text(video_id, original, production):
    with connect() as con:
        con.execute("UPDATE videos SET original_script=?,production_script=?,script=? WHERE id=?",(original or '',production or '',production or '',int(video_id)))


def update_video_production_text(video_id, production):
    """Update the user-confirmed spoken/production copy without overwriting the source original."""
    with connect() as con:
        con.execute("UPDATE videos SET production_script=?,script=? WHERE id=?",(production or '',production or '',int(video_id)))


def create_asset_job(video_id,source_url,asset_index,expected_name):
    with connect() as con:
        con.execute("""INSERT OR IGNORE INTO asset_jobs(video_id,source_url,asset_index,expected_name,status) VALUES(?,?,?,?, 'queued')""",
                    (int(video_id),source_url or '',int(asset_index),expected_name or ''))
        con.execute("UPDATE videos SET asset_status='待下载' WHERE id=?",(int(video_id),))


def list_asset_jobs(status=None):
    where=' WHERE a.status=?' if status else ''; args=(status,) if status else ()
    with connect() as con:
        return con.execute(f"""SELECT a.*,v.seq video_seq,h.name host_name,r.name recipient_name
            FROM asset_jobs a JOIN videos v ON v.id=a.video_id JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            {where} ORDER BY a.id""",args).fetchall()


def complete_asset_job(job_id,local_path,error=''):
    status='done' if local_path else 'failed'
    with connect() as con:
        r=con.execute("SELECT video_id FROM asset_jobs WHERE id=?",(int(job_id),)).fetchone()
        con.execute("UPDATE asset_jobs SET status=?,local_path=?,error=? WHERE id=?",(status,local_path or '',error or '',int(job_id)))
        if r and local_path:
            con.execute("UPDATE videos SET image_path=?,asset_status='已准备' WHERE id=?",(local_path,int(r['video_id'])))


def create_web_fetch_job(job_id,kind,url,meta):
    with connect() as con:
        con.execute("""INSERT OR REPLACE INTO web_fetch_jobs(job_id,kind,url,meta_json,status,result_json,error,updated_at)
                       VALUES(?,?,?,?, 'queued','{}','',CURRENT_TIMESTAMP)""",(job_id,kind,url,_json.dumps(meta or {},ensure_ascii=False)))


def list_web_fetch_jobs(status='queued'):
    with connect() as con:
        return con.execute("SELECT * FROM web_fetch_jobs WHERE status=? ORDER BY created_at",(status,)).fetchall()


def get_web_fetch_job(job_id):
    with connect() as con:return con.execute("SELECT * FROM web_fetch_jobs WHERE job_id=?",(job_id,)).fetchone()


def complete_web_fetch_job(job_id,result=None,error=''):
    with connect() as con:
        con.execute("UPDATE web_fetch_jobs SET status=?,result_json=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                    ('failed' if error else 'done',_json.dumps(result or {},ensure_ascii=False),error or '',job_id))


# ----- Whisper / local QC / AI QC shared cache -----
def get_speech_analysis(segment_id):
    with connect() as con:return con.execute("SELECT * FROM speech_analysis WHERE segment_id=?",(int(segment_id),)).fetchone()


def save_speech_analysis(segment_id,video_hash,sidecar_path,payload):
    with connect() as con:
        con.execute("""INSERT INTO speech_analysis(segment_id,video_hash,sidecar_path,analysis_json,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)
                       ON CONFLICT(segment_id) DO UPDATE SET video_hash=excluded.video_hash,sidecar_path=excluded.sidecar_path,analysis_json=excluded.analysis_json,updated_at=CURRENT_TIMESTAMP""",
                    (int(segment_id),video_hash or '',sidecar_path or '',_json.dumps(payload or {},ensure_ascii=False)))


def save_local_qc_result(segment_id,payload):
    pre=(payload or {}).get('precheck') or {}; speech=(payload or {}).get('speech')
    try: threshold=float(get_setting('whisper_match_threshold','0.82') or 0.82)
    except Exception: threshold=0.82
    if pre and not pre.get('ok',True): status='failed'
    elif not speech: status='needs_speech'
    elif float(speech.get('match_score') or 0) < threshold: status='speech_failed'
    else: status='ready'
    with connect() as con:
        con.execute("""INSERT INTO local_qc_results(segment_id,status,result_json,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)
                       ON CONFLICT(segment_id) DO UPDATE SET status=excluded.status,result_json=excluded.result_json,updated_at=CURRENT_TIMESTAMP""",
                    (int(segment_id),status,_json.dumps(payload or {},ensure_ascii=False)))


def get_local_qc_result(segment_id):
    with connect() as con:return con.execute("SELECT * FROM local_qc_results WHERE segment_id=?",(int(segment_id),)).fetchone()


def save_ai_qc_result(segment_id,payload):
    with connect() as con:
        con.execute("""INSERT INTO ai_qc_results(segment_id,light,summary,result_json,cost_usd,updated_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
                       ON CONFLICT(segment_id) DO UPDATE SET light=excluded.light,summary=excluded.summary,result_json=excluded.result_json,cost_usd=excluded.cost_usd,updated_at=CURRENT_TIMESTAMP""",
                    (int(segment_id),str((payload or {}).get('light') or ''),str((payload or {}).get('summary') or ''),_json.dumps(payload or {},ensure_ascii=False),float((payload or {}).get('cost_usd') or 0)))


def get_ai_qc_result(segment_id):
    with connect() as con:return con.execute("SELECT * FROM ai_qc_results WHERE segment_id=?",(int(segment_id),)).fetchone()


def log_api_usage(segment_id,model,input_tokens,cached_tokens,output_tokens,cost):
    with connect() as con:
        con.execute("INSERT INTO api_usage_log(flow_segment_id,model,input_tokens,cached_tokens,output_tokens,cost_usd) VALUES(?,?,?,?,?,?)",
                    (int(segment_id) if segment_id else None,model or '',int(input_tokens or 0),int(cached_tokens or 0),int(output_tokens or 0),float(cost or 0)))


def qc_bundle(segment_id):
    local=get_local_qc_result(segment_id); ai=get_ai_qc_result(segment_id); speech=get_speech_analysis(segment_id)
    def parse(row,key):
        if not row:return None
        try:return _json.loads(row[key] or '{}')
        except Exception:return None
    return {'local':parse(local,'result_json'),'ai':parse(ai,'result_json'),'speech':parse(speech,'analysis_json')}


def list_qc_segments(recipient_id=None, host_id=None, status_filter="全部", *, work_date=None):
    history=status_filter=='退回'
    output_join='fo.segment_id=fs.id' + ('' if history else ' AND fo.command_id=fs.generation_command')
    dedup_clause=(
        "NOT EXISTS (SELECT 1 FROM flow_outputs fo2 "
        "WHERE fo2.segment_id=fo.segment_id AND fo2.command_id=fo.command_id AND fo2.output_path=fo.output_path "
        "AND (((CASE WHEN fo2.media_id LIKE 'local:%' OR fo2.media_id LIKE 'plugin:%' THEN 1 ELSE 0 END) "
        "< (CASE WHEN fo.media_id LIKE 'local:%' OR fo.media_id LIKE 'plugin:%' THEN 1 ELSE 0 END)) "
        "OR ((CASE WHEN fo2.media_id LIKE 'local:%' OR fo2.media_id LIKE 'plugin:%' THEN 1 ELSE 0 END) "
        "= (CASE WHEN fo.media_id LIKE 'local:%' OR fo.media_id LIKE 'plugin:%' THEN 1 ELSE 0 END) AND fo2.id < fo.id)))"
    )
    where=(["TRIM(fo.output_path)<>''", dedup_clause] if history else ["fs.flow_status='已完成'","TRIM(fo.output_path)<>''", dedup_clause])
    args=[]
    if recipient_id:where.append('r.id=?');args.append(recipient_id)
    if host_id:where.append('h.id=?');args.append(host_id)
    if status_filter and status_filter not in ('全部','AI绿灯','AI黄灯','AI红灯'):
        where.append("COALESCE(fo.qc_status,'待质检')=?");args.append(status_filter)
    if status_filter=='AI绿灯':where.append("COALESCE(aq.light,'')='green'")
    elif status_filter=='AI黄灯':where.append("COALESCE(aq.light,'')='yellow'")
    elif status_filter=='AI红灯':where.append("COALESCE(aq.light,'')='red'")
    clause=' WHERE '+' AND '.join(where)
    with read_connection(work_date) as con:
        return con.execute(f"""SELECT fs.id segment_id,fo.id output_id,r.id recipient_id,r.name recipient_name,h.id host_id,h.name host_name,
            v.id video_id,v.seq video_seq,v.image_path,v.chinese_script,v.script full_foreign_text,fs.seg_seq,fs.foreign_text,fs.prompt,COALESCE(fs.generation_mode,'FRAME') generation_mode,COALESCE(fs.video_model,'') video_model,fs.flow_status,fs.flow_error,
            fo.output_path flow_output_path,COALESCE(fs.flow_output_url,'') flow_output_url,COALESCE(fo.qc_status,'待质检') qc_status,COALESCE(fs.qc_note,'') qc_note,
            COALESCE(lq.status,'pending') local_qc_status,COALESCE(aq.light,'') ai_qc_light,COALESCE(aq.summary,'') ai_qc_summary,
            COALESCE(sa.analysis_json,'') speech_analysis_json,COALESCE(lq.result_json,'') local_qc_json,COALESCE(aq.result_json,'') ai_qc_json
            FROM flow_segments fs JOIN flow_outputs fo ON {output_join}
            JOIN videos v ON v.id=fs.video_id JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            LEFT JOIN speech_analysis sa ON sa.segment_id=fs.id LEFT JOIN local_qc_results lq ON lq.segment_id=fs.id LEFT JOIN ai_qc_results aq ON aq.segment_id=fs.id
            {clause} ORDER BY r.id DESC,h.id,v.seq,fs.seg_seq""",args).fetchall()



def get_qc_output(output_id):
    with connect() as con:
        return con.execute("""SELECT fs.id segment_id,fo.id output_id,r.id recipient_id,r.name recipient_name,h.id host_id,h.name host_name,
            v.id video_id,v.seq video_seq,v.image_path,v.chinese_script,v.script full_foreign_text,fs.seg_seq,fs.foreign_text,fs.prompt,COALESCE(fs.generation_mode,'FRAME') generation_mode,COALESCE(fs.video_model,'') video_model,fs.flow_status,fs.flow_error,
            fo.output_path flow_output_path,COALESCE(fs.flow_output_url,'') flow_output_url,COALESCE(fo.qc_status,'待质检') qc_status,COALESCE(fs.qc_note,'') qc_note,
            COALESCE(lq.status,'pending') local_qc_status,COALESCE(aq.light,'') ai_qc_light,COALESCE(aq.summary,'') ai_qc_summary,
            COALESCE(sa.analysis_json,'') speech_analysis_json,COALESCE(lq.result_json,'') local_qc_json,COALESCE(aq.result_json,'') ai_qc_json
            FROM flow_outputs fo JOIN flow_segments fs ON fs.id=fo.segment_id JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            LEFT JOIN speech_analysis sa ON sa.segment_id=fs.id LEFT JOIN local_qc_results lq ON lq.segment_id=fs.id LEFT JOIN ai_qc_results aq ON aq.segment_id=fs.id
            WHERE fo.id=?""",(int(output_id),)).fetchone()


def pipeline_queue_counts(*, work_date=None):
    with read_connection(work_date) as con:
        row=con.execute("""SELECT
            (SELECT COUNT(*) FROM flow_segments WHERE flow_status IN ('待生成','已准备')) flow_waiting,
            (SELECT COUNT(*) FROM flow_segments WHERE flow_status IN ('已提交','生成中','下载中')) flow_active,
            (SELECT COUNT(*) FROM flow_segments WHERE flow_status='已完成' AND COALESCE(qc_status,'待质检')='待质检' AND NOT (seg_seq>=1000 AND foreign_text LIKE '[LEGACY_AUX]%')) qc_waiting,
            (SELECT COUNT(*) FROM videos v WHERE edit_status IN ('待导入DaVinci','等待片段')
                AND EXISTS(SELECT 1 FROM flow_segments fs WHERE fs.video_id=v.id)
                AND NOT EXISTS(SELECT 1 FROM flow_segments fs WHERE fs.video_id=v.id AND NOT (fs.seg_seq>=1000 AND fs.foreign_text LIKE '[LEGACY_AUX]%')
                    AND (COALESCE(fs.qc_status,'待质检')<>'通过' OR fs.flow_status<>'已完成'))) edit_waiting,
            (SELECT COUNT(*) FROM videos WHERE edit_status IN ('已剪辑','已导出') AND upload_status<>'已上传') upload_waiting
        """).fetchone()
    return dict(row)



def browser_throughput_stats():
    with connect() as con:
        rows=con.execute("""SELECT COALESCE(NULLIF(c.browser_group,''),'A') browser_group,
            COUNT(d.id) submitted,
            SUM(CASE WHEN d.status='failed' THEN 1 ELSE 0 END) failed,
            SUM(CASE WHEN d.status='detected' THEN 1 ELSE 0 END) completed,
            COUNT(DISTINCT c.channel_key) channels
            FROM flow_channel_pool c LEFT JOIN flow_dispatches d ON d.channel_key=c.channel_key
            WHERE c.enabled=1 GROUP BY COALESCE(NULLIF(c.browser_group,''),'A') ORDER BY browser_group""").fetchall()
    return [dict(r) for r in rows]


def daily_production_report(day=None, *, work_date=None):
    day=day or _time.strftime('%Y-%m-%d')
    with read_connection(work_date) as con:
        r=con.execute("""SELECT
          (SELECT COUNT(*) FROM flow_dispatches WHERE (? IS NOT NULL OR substr(created_at,1,10)=?)) dispatched,
          (SELECT COUNT(*) FROM flow_dispatches WHERE (? IS NOT NULL OR substr(created_at,1,10)=?) AND status='detected') downloaded,
          (SELECT COUNT(*) FROM flow_dispatches WHERE (? IS NOT NULL OR substr(created_at,1,10)=?) AND status='failed') flow_failed,
          (SELECT COUNT(*) FROM ai_qc_results WHERE (? IS NOT NULL OR substr(updated_at,1,10)=?) AND light='green') ai_green,
          (SELECT COUNT(*) FROM ai_qc_results WHERE (? IS NOT NULL OR substr(updated_at,1,10)=?) AND light='yellow') ai_yellow,
          (SELECT COUNT(*) FROM ai_qc_results WHERE (? IS NOT NULL OR substr(updated_at,1,10)=?) AND light='red') ai_red,
          (SELECT COALESCE(SUM(cost_usd),0) FROM api_usage_log WHERE (? IS NOT NULL OR substr(created_at,1,10)=?)) api_cost
        """,(work_date,day)*7).fetchone()
    return {'day':day,**dict(r)}



def set_dispatch_release_for_command(command_id, release_at):
    with connect() as con:
        con.execute("UPDATE flow_dispatches SET release_at=?,last_update_at=? WHERE command_id=?",
                    (float(release_at or 0),_time.time(),str(command_id)))


def list_stale_unsubmitted_dispatches(now=None, threshold_seconds=300):
    """Dispatches never acknowledged by the plugin after their release time.

    These are the only dispatches eligible for safe reclaim. SUBMITTED/DOWNLOADING are never
    returned here because moving those could duplicate a Flow generation.
    """
    now=float(now or _time.time()); cutoff=now-float(threshold_seconds)
    with connect() as con:
        return con.execute("""SELECT d.*,c.last_seen,c.health_status,c.page_status
            FROM flow_dispatches d LEFT JOIN flow_channel_pool c ON c.channel_key=d.channel_key
            WHERE d.stage='QUEUED' AND d.release_at>0 AND d.release_at<? AND d.last_update_at<?
            ORDER BY d.release_at""",(now,cutoff)).fetchall()


def list_auto_reclaimable_unsubmitted_dispatches(now=None, threshold_seconds=60, *, work_date=None):
    """Safely reclaim a released wave that the browser never claimed.

    Automatic refill may only take rows that are still QUEUED, have no browser command
    owner, have no submitted/download receipt anywhere in the same command, and are not
    in an active image-upload state.  This closes the gap where every channel looks idle
    but a never-claimed local command keeps task_command_id occupied forever.
    """
    now=float(now or _time.time()); cutoff=now-float(threshold_seconds)
    with read_connection(work_date) as con:
        owner_table=bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='browser_command_owners'").fetchone())
        owner_clause=("AND NOT EXISTS (SELECT 1 FROM browser_command_owners o WHERE o.command_id=d.command_id)" if owner_table else "")
        sql=f"""SELECT d.*,c.last_seen,c.health_status,c.page_status,c.upload_state
            FROM flow_dispatches d
            LEFT JOIN flow_channel_pool c ON c.channel_key=d.channel_key
            WHERE d.stage='QUEUED' AND d.status IN ('planned','queued')
              AND EXISTS (SELECT 1 FROM flow_segments fs WHERE fs.id=d.segment_id AND fs.generation_command=d.command_id AND fs.flow_status IN ('待生成','已准备'))
              AND d.release_at>0 AND d.release_at<? AND d.last_update_at<?
              AND COALESCE(c.upload_state,'idle') NOT IN ('queued','precheck','uploading')
              {owner_clause}
              AND NOT EXISTS (
                    SELECT 1 FROM flow_dispatches x
                    WHERE x.command_id=d.command_id
                      AND (x.status IN ('submitted','downloading','detected')
                           OR TRIM(COALESCE(x.submitted_at,''))<>'')
              )
            ORDER BY d.release_at,d.id"""
        return con.execute(sql,(now,cutoff)).fetchall()


def requeue_unsubmitted_dispatches(dispatch_ids, *, work_date=None):
    ids=[int(x) for x in dispatch_ids]
    if not ids:return 0
    if work_date is not None:
        wanted=set(ids)
        with read_connection(work_date) as scoped:
            allowed={int(r[0]) for r in scoped.execute("SELECT id FROM flow_dispatches").fetchall()}
        ids=[x for x in ids if x in allowed and x in wanted]
        if not ids:return 0
    count=0
    with connect() as con:
        for did in ids:
            d=con.execute("SELECT * FROM flow_dispatches WHERE id=? AND stage='QUEUED'",(did,)).fetchone()
            if not d or d['status'] not in ('planned','queued'):continue
            if con.execute("SELECT 1 FROM flow_dispatches WHERE command_id=? AND (status IN ('submitted','downloading','detected') OR TRIM(COALESCE(submitted_at,''))<>'')",(d['command_id'],)).fetchone():continue
            fs=con.execute("SELECT generation_command,flow_status FROM flow_segments WHERE id=?",(int(d['segment_id']),)).fetchone()
            if not fs or fs['flow_status'] not in ('待生成','已准备') or str(fs['generation_command'] or '')!=str(d['command_id']):continue
            con.execute("""UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_error='已回收未提交任务',flow_channel_key=''
                         WHERE id=?""",(int(d['segment_id']),))
            con.execute("UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',error='未提交任务已回收',last_update_at=? WHERE id=?",(_time.time(),did))
            count+=1
    return count


# ---------------------------------------------------------------------------
# V0.13.5 human-gate + QC statistics helpers
# ---------------------------------------------------------------------------

def host_downstream_replacement_info(host_id, *, work_date=None):
    """Describe whether a host already owns production state below the GPT gate.

    This is intentionally read-only.  It is used by the Prompt Center to decide
    whether a repeated host submission needs the explicit overwrite warning.
    """
    hid=int(host_id)
    if work_date is not None:
        from app.core import work_dates
        host=get_host_with_recipient(hid)
        if not host:
            return {'exists':False,'has_downstream':False,'segments':0}
        work_dates.require_recipient_work_date(int(host['recipient_id']), work_date)
    with connect() as con:
        row=con.execute("""SELECT
            COUNT(DISTINCT fs.id) segments,
            SUM(CASE WHEN COALESCE(fs.prompt_review_status,'待检查')='已提交' THEN 1 ELSE 0 END) submitted,
            SUM(CASE WHEN TRIM(COALESCE(fs.generation_command,''))<>'' OR COALESCE(fs.flow_status,'待生成') NOT IN ('','待生成') THEN 1 ELSE 0 END) flow_touched,
            SUM(CASE WHEN COALESCE(fs.qc_status,'待质检')<>'待质检' THEN 1 ELSE 0 END) qc_touched
            FROM flow_segments fs JOIN videos v ON v.id=fs.video_id WHERE v.host_id=?""",(hid,)).fetchone()
        outputs=con.execute("""SELECT COUNT(*) FROM flow_outputs fo JOIN flow_segments fs ON fs.id=fo.segment_id
            JOIN videos v ON v.id=fs.video_id WHERE v.host_id=?""",(hid,)).fetchone()[0]
        dispatches=con.execute("""SELECT COUNT(*) FROM flow_dispatches d JOIN flow_segments fs ON fs.id=d.segment_id
            JOIN videos v ON v.id=fs.video_id WHERE v.host_id=?""",(hid,)).fetchone()[0]
        redo=con.execute("""SELECT COUNT(*) FROM flow_redo x JOIN flow_segments fs ON fs.id=x.segment_id
            JOIN videos v ON v.id=fs.video_id WHERE v.host_id=?""",(hid,)).fetchone()[0]
        edits=con.execute("SELECT COUNT(*) FROM editing_history e JOIN videos v ON v.id=e.video_id WHERE v.host_id=?",(hid,)).fetchone()[0]
        has=bool(int(row['submitted'] or 0) or int(row['flow_touched'] or 0) or int(row['qc_touched'] or 0) or outputs or dispatches or redo or edits)
        return {'exists':True,'has_downstream':has,'segments':int(row['segments'] or 0),
                'submitted':int(row['submitted'] or 0),'outputs':int(outputs or 0),
                'dispatches':int(dispatches or 0),'redo':int(redo or 0),'editing_history':int(edits or 0)}


def is_obsolete_flow_command(command_id):
    cmd=str(command_id or '').strip()
    if not cmd:return False
    with connect() as con:
        return bool(con.execute("SELECT 1 FROM flow_obsolete_commands WHERE command_id=?",(cmd,)).fetchone())


def _safe_remove_exact_files(paths, protected_paths=()):
    """Move only exact recorded production files that are not referenced elsewhere to Trash (or recovery dir), never permanently unlinking them."""
    import shutil as _shutil
    from .database import DB_PATH
    try:
        from PySide6.QtCore import QFile as _QFile
    except Exception:
        _QFile = None
    protected=set()
    for value in protected_paths:
        try: protected.add(str(Path(str(value)).expanduser().resolve()))
        except Exception: protected.add(str(value))
    deleted=[]; failed=[]
    video_ext={'.mp4','.mov','.m4v','.webm','.mkv','.avi'}
    recovery_dir=None
    for value in dict.fromkeys(str(x or '').strip() for x in paths if str(x or '').strip()):
        try:
            path=Path(value).expanduser()
            resolved=str(path.resolve())
            if resolved in protected or path.suffix.lower() not in video_ext:
                continue
            if path.is_file():
                trashed=False
                if _QFile is not None:
                    try:
                        res=_QFile.moveToTrash(str(path))
                        trashed=bool(res[0]) if isinstance(res,tuple) else bool(res)
                    except Exception:
                        trashed=False
                if not trashed and path.is_file():
                    if recovery_dir is None:
                        recovery_dir=DB_PATH.parent/'deleted_host_recovery'/f'overwrite_{int(_time.time())}_{_uuid.uuid4().hex[:8]}'
                        recovery_dir.mkdir(parents=True,exist_ok=True)
                    dest=recovery_dir/path.name
                    if dest.exists():
                        dest=recovery_dir/f'{path.stem}_{_uuid.uuid4().hex[:6]}{path.suffix}'
                    _shutil.move(str(path),str(dest))
                deleted.append(str(path))
        except Exception as exc:
            failed.append({'path':value,'error':str(exc)})
    return deleted,failed


def replace_host_prompt_submission(host_id, *, work_date=None):
    """Replace one host's production chain after GPT prompts were regenerated.

    The source task, copy, image, numbering, persona and newly generated prompt stay
    intact.  Everything below the GPT gate is removed/reset in one transaction:
    Flow dispatch/output/rework state, QC rows and edit queue/history.  Existing
    local Flow render files are deleted after commit.  Old command ids are recorded
    as obsolete so late browser receipts can never revive the old revision.
    """
    hid=int(host_id)
    host=get_host_with_recipient(hid)
    if not host: raise ValueError('当前 AI 主播已经不存在。')
    if work_date is not None:
        from app.core import work_dates
        work_dates.require_recipient_work_date(int(host['recipient_id']), work_date)

    candidates=[]; job_files=[]; protected=[]; old_commands=set(); submitted=0
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        videos=con.execute("SELECT id FROM videos WHERE host_id=? ORDER BY seq",(hid,)).fetchall()
        vids=[int(r['id']) for r in videos]
        if not vids:
            return {'submitted':0,'segments':0,'deleted_files':0,'delete_failures':[],'old_commands':0}
        qv=','.join('?' for _ in vids)
        segments=con.execute(f"SELECT * FROM flow_segments WHERE video_id IN ({qv}) ORDER BY video_id,seg_seq",vids).fetchall()
        sids=[int(r['id']) for r in segments]
        if not sids:
            return {'submitted':0,'segments':0,'deleted_files':0,'delete_failures':[],'old_commands':0}
        qs=','.join('?' for _ in sids)

        for row in segments:
            if str(row['generation_command'] or '').strip(): old_commands.add(str(row['generation_command']).strip())
            if str(row['flow_output_path'] or '').strip(): candidates.append(str(row['flow_output_path']))
        for row in con.execute(f"SELECT command_id,output_path FROM flow_outputs WHERE segment_id IN ({qs})",sids):
            if str(row['command_id'] or '').strip(): old_commands.add(str(row['command_id']).strip())
            if str(row['output_path'] or '').strip(): candidates.append(str(row['output_path']))
        for row in con.execute(f"SELECT command_id,download_path FROM flow_dispatches WHERE segment_id IN ({qs})",sids):
            if str(row['command_id'] or '').strip(): old_commands.add(str(row['command_id']).strip())
            if str(row['download_path'] or '').strip(): candidates.append(str(row['download_path']))

        # Never delete a path still owned by another host/segment.
        for row in con.execute(f"SELECT flow_output_path p FROM flow_segments WHERE id NOT IN ({qs}) AND TRIM(COALESCE(flow_output_path,''))<>''",sids):
            protected.append(str(row['p']))
        for row in con.execute(f"SELECT output_path p FROM flow_outputs WHERE segment_id NOT IN ({qs}) AND TRIM(COALESCE(output_path,''))<>''",sids):
            protected.append(str(row['p']))

        for row in con.execute(f"SELECT job_path FROM editing_history WHERE video_id IN ({qv})",vids):
            if str(row['job_path'] or '').strip(): job_files.append(str(row['job_path']))

        for cmd in old_commands:
            con.execute("INSERT OR REPLACE INTO flow_obsolete_commands(command_id,host_id,reason,invalidated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
                        (cmd,hid,'GPT重复提交覆盖旧主播任务'))

        # Remove queued browser download receipts for the invalidated segments/commands.
        pending=con.execute("SELECT event_id,payload FROM flow_pending_downloads").fetchall()
        sid_set=set(sids)
        for row in pending:
            try:
                payload=_json.loads(row['payload'] or '{}')
                if int(payload.get('segment_id') or 0) in sid_set or str(payload.get('command_id') or '') in old_commands:
                    con.execute("DELETE FROM flow_pending_downloads WHERE event_id=?",(row['event_id'],))
            except Exception:
                continue

        # Remove invalidated commands from the persisted browser job snapshot as well.
        setting=con.execute("SELECT value FROM app_settings WHERE key='flow_host_jobs_v124'").fetchone()
        if setting and old_commands:
            try:
                jobs=_json.loads(setting['value'] or '[]')
                if isinstance(jobs,list):
                    jobs=[j for j in jobs if str((j or {}).get('command_id') or '') not in old_commands]
                    con.execute("UPDATE app_settings SET value=? WHERE key='flow_host_jobs_v124'",(_json.dumps(jobs,ensure_ascii=False),))
            except Exception:
                pass

        # Downstream production state only.  API billing logs and prompt audit are kept.
        for table in ('flow_outputs','flow_redo','flow_failure_attempts','flow_recovery','flow_dispatches',
                      'speech_analysis','local_qc_results','ai_qc_results','qc_decisions'):
            con.execute(f"DELETE FROM {table} WHERE segment_id IN ({qs})",sids)
        con.execute(f"DELETE FROM editing_history WHERE video_id IN ({qv})",vids)
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='davinci_video_state'").fetchone():
            con.execute(f"DELETE FROM davinci_video_state WHERE video_id IN ({qv})",vids)

        con.execute(f"""UPDATE videos SET edit_status='等待片段',edit_output_path='',
            upload_status='未上传',upload_target='',upload_url='',upload_confirm_mode='',upload_confirmed_at='',drive_file_url=''
            WHERE id IN ({qv})""",vids)
        con.execute("UPDATE hosts SET flow_task_command_id='' WHERE id=?",(hid,))
        con.execute("UPDATE flow_channels SET task_command_id='' WHERE host_id=?",(hid,))

        con.execute(f"""UPDATE flow_segments SET
            generation_command='',flow_status='待生成',flow_output_path='',flow_output_url='',flow_error='',
            flow_attempts=0,flow_submitted_at='',flow_completed_at='',flow_channel_key='',flow_retry_count=0,
            qc_status='待质检',qc_note='',qc_reject_reason='',qc_decided_at='',
            prompt_review_status='待检查',prompt_submitted_at=''
            WHERE id IN ({qs})""",sids)

        # Release only pool commands no longer referenced by any current segment.
        for cmd in old_commands:
            if not con.execute("SELECT 1 FROM flow_segments WHERE generation_command=? LIMIT 1",(cmd,)).fetchone():
                con.execute("UPDATE flow_channel_pool SET task_command_id='',last_status='已释放：主播提示词已覆盖' WHERE task_command_id=?",(cmd,))

        # The replacement is a full-host submission: every newly generated prompt for
        # this host becomes the new Flow waiting queue; blank/failed prompts stay at GPT.
        fresh=con.execute(f"SELECT id,prompt FROM flow_segments WHERE id IN ({qs}) ORDER BY id",sids).fetchall()
        for row in fresh:
            prompt=str(row['prompt'] or '').strip()
            if not prompt: continue
            sid=int(row['id'])
            con.execute("INSERT INTO prompt_submission_history(segment_id,prompt_snapshot) VALUES(?,?)",(sid,prompt))
            con.execute("UPDATE flow_segments SET prompt_review_status='已提交',prompt_submitted_at=CURRENT_TIMESTAMP,flow_status='待生成' WHERE id=?",(sid,))
            submitted+=1

    deleted,failed=_safe_remove_exact_files(candidates,protected)
    # Editing job manifests are disposable queue artifacts, not exported user videos.
    for value in dict.fromkeys(job_files):
        try:
            p=Path(value).expanduser()
            if p.is_file() and p.suffix.lower() in ('.json','.job','.txt'):
                p.unlink()
        except Exception:
            pass
    return {'submitted':submitted,'segments':len(sids),'deleted_files':len(deleted),
            'deleted_paths':deleted,'delete_failures':failed,'old_commands':len(old_commands),
            'old_command_ids':sorted(old_commands)}

def submit_prompt_segments_to_flow(segment_ids):
    ids=[int(x) for x in segment_ids if str(x).strip()]
    if not ids: return {'submitted':0,'skipped':0}
    submitted=skipped=0
    with connect() as con:
        for sid in ids:
            row=con.execute("SELECT video_id,prompt,prompt_review_status,flow_status FROM flow_segments WHERE id=?",(sid,)).fetchone()
            if not row or not str(row['prompt'] or '').strip():
                skipped+=1; continue
            if str(row['prompt_review_status'] or '')=='已提交':
                skipped+=1; continue
            con.execute("INSERT INTO prompt_submission_history(segment_id,prompt_snapshot) VALUES(?,?)",(sid,str(row['prompt'] or '')))
            con.execute("UPDATE flow_segments SET prompt_review_status='已提交',prompt_submitted_at=CURRENT_TIMESTAMP,flow_status=CASE WHEN flow_status IN ('','失败','已放弃') THEN '待生成' ELSE flow_status END WHERE id=?",(sid,))
            con.execute("UPDATE videos SET edit_status='等待片段' WHERE id=? AND COALESCE(edit_status,'')='已放弃'",(int(row['video_id']),))
            submitted+=1
    return {'submitted':submitted,'skipped':skipped}

def withdraw_prompt_segments_from_flow(segment_ids):
    ids=[int(x) for x in segment_ids if str(x).strip()]
    withdrawn=blocked=0
    with connect() as con:
        for sid in ids:
            active=con.execute("SELECT 1 FROM flow_dispatches WHERE segment_id=? AND status IN ('queued','planned','submitted','downloading','detected') LIMIT 1",(sid,)).fetchone()
            row=con.execute("SELECT flow_status FROM flow_segments WHERE id=?",(sid,)).fetchone()
            if active or (row and str(row['flow_status'] or '') not in ('待生成','失败','已准备','')):
                blocked+=1; continue
            con.execute("UPDATE flow_segments SET prompt_review_status='待检查',prompt_submitted_at='' WHERE id=?",(sid,))
            withdrawn+=1
    return {'withdrawn':withdrawn,'blocked':blocked}

def prompt_gate_counts(*, work_date=None):
    with read_connection(work_date) as con:
        rows=con.execute("SELECT COALESCE(prompt_review_status,'待检查') s,COUNT(*) n FROM flow_segments WHERE TRIM(COALESCE(prompt,''))<>'' GROUP BY s").fetchall()
    d={str(r['s']):int(r['n']) for r in rows}
    return {'pending':d.get('待检查',0),'submitted':d.get('已提交',0)}


def set_segment_qc_decision(segment_id, decision, reason=''):
    sid=int(segment_id); decision=str(decision or '')
    reason=str(reason or '')
    with connect() as con:
        row=con.execute("""SELECT fs.id,fs.prompt,v.performance_mode,h.name host_name,r.name recipient_name,v.id video_id
                           FROM flow_segments fs JOIN videos v ON v.id=fs.video_id JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id WHERE fs.id=?""",(sid,)).fetchone()
        if not row: return False
        qc_status='通过' if decision=='通过' else '退回'
        con.execute("UPDATE flow_segments SET qc_status=?,qc_note=?,qc_reject_reason=?,qc_decided_at=CURRENT_TIMESTAMP WHERE id=?",(qc_status,reason,reason,sid))
        con.execute("INSERT INTO qc_decisions(segment_id,decision,reason,recipient_name,host_name,performance_mode,prompt_snapshot) VALUES(?,?,?,?,?,?,?)",
                    (sid,decision,reason,row['recipient_name'] or '',row['host_name'] or '',row['performance_mode'] or 'TALKING',row['prompt'] or ''))
        if qc_status=='退回':
            con.execute("INSERT OR REPLACE INTO flow_redo(segment_id,created_at) VALUES(?,CURRENT_TIMESTAMP)",(sid,))
            con.execute("UPDATE flow_segments SET flow_retry_count=COALESCE(flow_retry_count,0)+1,generation_command='',flow_status='待生成' WHERE id=?",(sid,))
        else:
            con.execute("DELETE FROM flow_redo WHERE segment_id=?",(sid,))
        video_id=int(row['video_id'])
        counts=con.execute("SELECT COUNT(*) total,SUM(CASE WHEN qc_status='通过' THEN 1 ELSE 0 END) passed FROM flow_segments WHERE video_id=?",(video_id,)).fetchone()
        if counts and int(counts['total'] or 0)>0 and int(counts['passed'] or 0)==int(counts['total'] or 0):
            con.execute("UPDATE videos SET edit_status='等待剪辑' WHERE id=? AND COALESCE(edit_status,'')<>'已放弃'",(video_id,))
        else:
            con.execute("UPDATE videos SET edit_status='等待片段' WHERE id=? AND COALESCE(edit_status,'')<>'已放弃'",(video_id,))
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='davinci_video_state'").fetchone():
                con.execute("DELETE FROM davinci_video_state WHERE video_id=?",(video_id,))
    return True

def update_qc_segment_prompt(segment_id, prompt):
    """QC-side prompt edit only. It does not submit, requeue, or change Flow/QC state."""
    sid=int(segment_id); prompt=str(prompt or '').strip()
    if not prompt: raise ValueError('提示词不能为空')
    with connect() as con:
        row=con.execute("SELECT id FROM flow_segments WHERE id=?",(sid,)).fetchone()
        if not row: raise ValueError('质检片段不存在')
        con.execute("UPDATE flow_segments SET prompt=? WHERE id=?",(prompt,sid))
    return True


def undo_qc_output_decision(output_id, expected_decision, previous_status='待质检', previous_note=''):
    """Safely undo the most recent QC decision for one exact rendered output.

    This intentionally refuses to roll back once a redo has entered a live Flow dispatch or
    once DaVinci/editing has actually started. Pending edit-ready state may be returned to
    waiting-material so the existing downstream chain remains coherent.
    """
    oid=int(output_id); expected=str(expected_decision or '')
    previous_status=str(previous_status or '待质检'); previous_note=str(previous_note or '')
    if previous_status not in ('待质检','通过','退回','画面处理'):
        previous_status='待质检'
    with connect() as con:
        row=con.execute("""SELECT fo.id output_id,fo.segment_id,fo.command_id,fo.output_path,fo.qc_status output_qc,
            fs.qc_status segment_qc,fs.flow_status,fs.generation_command,fs.video_id,
            COALESCE(v.edit_status,'等待片段') edit_status
            FROM flow_outputs fo JOIN flow_segments fs ON fs.id=fo.segment_id JOIN videos v ON v.id=fs.video_id
            WHERE fo.id=?""",(oid,)).fetchone()
        if not row: return {'ok':False,'message':'原质检结果已经不存在，无法撤销。'}
        sid=int(row['segment_id']); vid=int(row['video_id'])
        if expected=='退回':
            active=con.execute("""SELECT 1 FROM flow_dispatches WHERE segment_id=? AND
                (status IN ('queued','planned','submitted','downloading','detected') OR stage IN ('QUEUED','SUBMITTED','DOWNLOADING')) LIMIT 1""",(sid,)).fetchone()
            if active:
                return {'ok':False,'message':'该返工任务已经进入 Flow 调度/提交阶段，为避免重复生成，不能强制撤销。'}
            # Restore the exact rejected render as the current QC candidate.
            con.execute("UPDATE flow_outputs SET qc_status=? WHERE id=?",(previous_status,oid))
            con.execute("""UPDATE flow_segments SET generation_command=?,flow_status='已完成',flow_output_path=?,flow_output_url='',
                flow_error='',flow_channel_key='',qc_status=?,qc_note=?,qc_reject_reason='',qc_decided_at=''
                WHERE id=?""",(str(row['command_id'] or ''),str(row['output_path'] or ''),previous_status,previous_note,sid))
            con.execute("DELETE FROM flow_redo WHERE segment_id=?",(sid,))
        elif expected=='通过':
            editing=str(row['edit_status'] or '')
            unsafe={'剪辑中','自动剪辑中','已导入DaVinci','已剪辑','待人工检查','待导出','导出中','已导出'}
            if editing in unsafe:
                return {'ok':False,'message':f'该完整视频已经进入“{editing}”，为保护 DaVinci/导出链路，不能强制撤销。'}
            con.execute("UPDATE flow_outputs SET qc_status=? WHERE id=?",(previous_status,oid))
            con.execute("UPDATE flow_segments SET qc_status=?,qc_note=?,qc_reject_reason='',qc_decided_at='' WHERE id=?",(previous_status,previous_note,sid))
        else:
            return {'ok':False,'message':'最近一次操作不是可撤销的通过/退回决定。'}
        # Remove only the newest matching decision generated by the action being undone.
        dec=con.execute("SELECT id FROM qc_decisions WHERE segment_id=? AND decision=? ORDER BY id DESC LIMIT 1",(sid,expected)).fetchone()
        if dec: con.execute("DELETE FROM qc_decisions WHERE id=?",(int(dec['id']),))
        # Delegate reconciliation to the single unified logic.
        from app.services.workflow import reconcile_video_qc
        reconcile_video_qc(vid, con)
    return {'ok':True,'segment_id':sid,'video_id':vid}


def qc_reason_stats(days=30, *, work_date=None):
    """QC reasons from the real segment state, including data created before qc_decisions existed."""
    with read_connection(work_date) as con:
        rows=con.execute("""SELECT COALESCE(NULLIF(TRIM(qc_reject_reason),''),NULLIF(TRIM(qc_note),''),'未分类') reason,COUNT(*) n
                            FROM flow_segments
                            WHERE COALESCE(qc_status,'待质检')='退回'
                              AND (TRIM(COALESCE(qc_decided_at,''))='' OR (? IS NOT NULL OR qc_decided_at>=datetime('now',?)))
                            GROUP BY reason ORDER BY n DESC""",(work_date,f'-{int(days)} days')).fetchall()
    return [dict(r) for r in rows]


def recipient_output_stats(days=30, *, work_date=None):
    # Older projects do not have a reliable upload timestamp.  Count the actual
    # current delivered/uploaded records instead of filtering by recipient creation date.
    with read_connection(work_date) as con:
        rows=con.execute("""SELECT r.name recipient_name,COUNT(v.id) n
                            FROM videos v JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
                            WHERE v.upload_status IN ('已上传','已交付')
                            GROUP BY r.id,r.name ORDER BY n DESC""").fetchall()
    return [dict(r) for r in rows]


def record_sync_history(imported=0,updated=0,unchanged=0,source='manual',detail=None):
    with connect() as con:
        con.execute("INSERT INTO sync_history(imported,updated,unchanged,source,detail_json) VALUES(?,?,?,?,?)",
                    (int(imported),int(updated),int(unchanged),str(source),_json.dumps(detail or {},ensure_ascii=False)))

def latest_sync_history(limit=20):
    with connect() as con:
        return con.execute("SELECT * FROM sync_history ORDER BY id DESC LIMIT ?",(int(limit),)).fetchall()

def quality_summary(days=30, *, work_date=None):
    """Pipeline statistics sourced from the tables that drive Flow/QC/Edit UI.

    Legacy rows with no timestamp remain visible, so the statistics page immediately
    reflects work already completed before this statistics module was added.
    """
    with read_connection(work_date) as con:
        row=con.execute("""SELECT
            SUM(CASE WHEN COALESCE(qc_status,'待质检')='通过' THEN 1 ELSE 0 END) passed,
            SUM(CASE WHEN COALESCE(qc_status,'待质检')='退回' THEN 1 ELSE 0 END) rejected,
            SUM(CASE WHEN COALESCE(qc_status,'待质检') IN ('通过','退回') THEN 1 ELSE 0 END) decisions
            FROM flow_segments
            WHERE (TRIM(COALESCE(qc_decided_at,''))='' OR (? IS NOT NULL OR qc_decided_at>=datetime('now',?)))""",(work_date,f'-{int(days)} days')).fetchone()
        flow=con.execute("""SELECT COUNT(*) total,
            SUM(CASE WHEN flow_status='已完成' OR TRIM(COALESCE(flow_output_path,''))<>'' THEN 1 ELSE 0 END) completed,
            SUM(CASE WHEN flow_status IN ('失败','下载失败') THEN 1 ELSE 0 END) failed
            FROM flow_segments""").fetchone()
        outputs=con.execute("""SELECT COUNT(*) n FROM videos
            WHERE upload_status IN ('已上传','已交付')""").fetchone()
    return {
        'passed':int(row['passed'] or 0),'rejected':int(row['rejected'] or 0),'decisions':int(row['decisions'] or 0),
        'flow_total':int(flow['total'] or 0),'flow_completed':int(flow['completed'] or 0),'flow_failed':int(flow['failed'] or 0),
        'final_outputs':int(outputs['n'] or 0),
    }


# ===== V0.13.5.1 delivery helpers =====
def mark_recipient_delivered(recipient_id):
    """Mark all already-uploaded finished videos for one recipient as delivered."""
    rid=int(recipient_id)
    with connect() as con:
        cur=con.execute("""UPDATE videos SET upload_status='已交付'
            WHERE host_id IN (SELECT id FROM hosts WHERE recipient_id=?)
              AND upload_status='已上传'""",(rid,))
        return int(cur.rowcount or 0)


def release_finished_channel_commands():
    """Release only terminal batches; queued/unsubmitted work keeps its channel."""
    with connect() as con:
        con.execute("""UPDATE flow_channel_pool SET task_command_id=''
            WHERE task_command_id<>'' AND NOT EXISTS (
                SELECT 1 FROM flow_segments fs WHERE fs.generation_command=flow_channel_pool.task_command_id
                AND fs.flow_status NOT IN ('已完成','失败','下载失败'))
            AND NOT EXISTS (
                SELECT 1 FROM flow_dispatches d JOIN flow_segments fs ON fs.id=d.segment_id
                WHERE d.command_id=flow_channel_pool.task_command_id AND fs.generation_command=d.command_id
                AND d.status IN ('planned','queued','submitted','downloading'))""")


def qc_rework_counts(*, work_date=None):
    with read_connection(work_date) as con:
        total=con.execute("SELECT COUNT(*) FROM qc_decisions WHERE decision='退回'").fetchone()[0]
        legacy=con.execute("""SELECT COUNT(*) FROM flow_outputs fo WHERE fo.qc_status='退回'
            AND NOT EXISTS (SELECT 1 FROM qc_decisions q WHERE q.segment_id=fo.segment_id AND q.decision='退回')""").fetchone()[0]
        active=con.execute("""SELECT COUNT(*) FROM flow_segments WHERE flow_retry_count>0
            AND qc_status<>'通过'""").fetchone()[0]
    return {'total':int(total+legacy),'active':int(active)}



def anchor_thumbnail_candidates(host_id):
    """Only ID-bound local assets; never infer ownership from names/directories."""
    with connect() as con:
        host=con.execute('SELECT image_path FROM hosts WHERE id=?',(host_id,)).fetchone()
        if not host: return []
        videos=con.execute("SELECT image_path FROM videos WHERE host_id=? ORDER BY CASE UPPER(performance_mode) WHEN 'TALKING' THEN 0 WHEN 'PRAYING' THEN 1 ELSE 2 END,seq,id",(host_id,)).fetchall()
        assets=con.execute('SELECT a.local_path FROM asset_jobs a JOIN videos v ON v.id=a.video_id WHERE v.host_id=? ORDER BY a.id',(host_id,)).fetchall()
    return list(dict.fromkeys([host['image_path']]+[r[0] for r in videos]+[r[0] for r in assets]))


def save_host_personas(host_id, talking, praying):
    """Commit both modes and the legacy summary together, preserving schema."""
    from .persona import rule_text
    summary='TALKING：'+rule_text(talking,'TALKING')+'\nPRAYING：'+rule_text(praying,'PRAYING')
    with connect() as con:
        for mode,data in (('talking',talking),('praying',praying)):
            con.execute('INSERT OR REPLACE INTO app_settings(key,value) VALUES(?,?)',
                        (f'host_persona_{int(host_id)}_{mode}',_json.dumps(data,ensure_ascii=False)))
        con.execute('UPDATE hosts SET prompt_rule=? WHERE id=?',(summary,host_id))


def save_host_persona_mode(host_id, mode, data):
    """Persist one host persona namespace without touching the other mode.

    Used by the persona editor's “设为预设” action so the current host starts
    using the exact same settings immediately, while TALKING/PRAYING remain
    independent.  The legacy hosts.prompt_rule summary is refreshed for older
    callers, but GPT generation continues to read the mode-specific settings.
    """
    from .persona import normalize, rule_text
    m = 'praying' if str(mode or '').upper() == 'PRAYING' else 'talking'
    current_mode = 'PRAYING' if m == 'praying' else 'TALKING'
    other_mode = 'TALKING' if current_mode == 'PRAYING' else 'PRAYING'
    clean = normalize(data, current_mode)
    with connect() as con:
        con.execute('INSERT OR REPLACE INTO app_settings(key,value) VALUES(?,?)',
                    (f'host_persona_{int(host_id)}_{m}', _json.dumps(clean, ensure_ascii=False)))
        other_key = f'host_persona_{int(host_id)}_{other_mode.lower()}'
        row = con.execute('SELECT value FROM app_settings WHERE key=?', (other_key,)).fetchone()
        try:
            other_raw = _json.loads(row['value'] or '{}') if row else {}
        except Exception:
            other_raw = {}
        other = normalize(other_raw, other_mode)
        talking = clean if current_mode == 'TALKING' else other
        praying = clean if current_mode == 'PRAYING' else other
        summary = 'TALKING：' + rule_text(talking, 'TALKING') + '\nPRAYING：' + rule_text(praying, 'PRAYING')
        con.execute('UPDATE hosts SET prompt_rule=? WHERE id=?', (summary, int(host_id)))
    return clean


def remove_pool_channel(key):
    """Remove a channel immediately and hand its unfinished tasks back to the pool.

    No "channel still has tasks" refusal any more. Every unfinished dispatch of the
    channel is cancelled and its segment returns to ``待生成`` (generation_command cleared)
    so the dispatcher gives it to another ONLINE channel on its next tick. Late receipts from
    the removed page stay stale because generation_command no longer matches.
    Returns ``{'commands': [...], 'segments': [...]}`` so the caller can also withdraw the
    commands from the Bridge.
    """
    key=str(key)
    commands=set(); moved=[]
    with connect() as con:
        row=con.execute('SELECT * FROM flow_channel_pool WHERE channel_key=?',(key,)).fetchone()
        if not row: return {'commands':[],'segments':[]}
        now=_time.time()
        chan_cmd=str(row['task_command_id'] or '').strip()
        if chan_cmd: commands.add(chan_cmd)
        rows=con.execute("""SELECT id,segment_id,command_id FROM flow_dispatches
                             WHERE channel_key=? AND status IN ('planned','queued','submitted','downloading','detected')""",(key,)).fetchall()
        for d in rows:
            sid=int(d['segment_id']); cmd=str(d['command_id'] or '')
            if cmd: commands.add(cmd)
            con.execute("""UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',
                            error='通道已移除，任务已转移到其他通道',last_update_at=? WHERE id=?""",(now,int(d['id'])))
            cur=con.execute("""UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_channel_key='',flow_error=''
                                WHERE id=? AND generation_command=? AND TRIM(COALESCE(flow_output_path,''))=''
                                  AND flow_status<>'已完成'""",(sid,cmd))
            if int(cur.rowcount or 0): moved.append(sid)
        if chan_cmd:
            # Segments that carry the channel's command but have no dispatch row yet.
            for r in con.execute("""SELECT id FROM flow_segments WHERE generation_command=? AND TRIM(COALESCE(flow_output_path,''))=''
                                       AND flow_status<>'已完成'""",(chan_cmd,)).fetchall():
                con.execute("""UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_channel_key='',flow_error='' WHERE id=?""",(int(r['id']),))
                if int(r['id']) not in moved: moved.append(int(r['id']))
        saved=con.execute("SELECT value FROM app_settings WHERE key='flow_removed_channels'").fetchone()
        removed=set(json.loads(saved[0]) if saved else []);removed.add(key)
        con.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('flow_removed_channels',?)",(json.dumps(sorted(removed)),))
        con.execute("""UPDATE flow_channel_pool SET enabled=0,task_command_id='',upload_state='idle',upload_command_id='',
                        last_status='已移除' WHERE channel_key=?""",(key,))
    return {'commands':sorted(commands),'segments':moved}


# ---------------------------------------------------------------------------
# V0.13.5 generation mode + prompt-copy editing helpers
# ---------------------------------------------------------------------------
def normalize_generation_mode(value):
    raw=str(value or '').strip().upper()
    return 'MATERIAL' if raw in ('MATERIAL','VIDEO_REFERENCES','素材') else 'FRAME'


def normalize_segment_video_model(value):
    raw=str(value or '').strip()
    if raw.lower() in ('flow_omni','omni','omini','abra','gemini_omni'):
        return 'flow_omni'
    return raw


def _set_segment_generation_mode_in_con(con, sid, mode, *, allow_active_rework=False, force_silent=False, reason='切换生成模式', clear_video_model=False):
    row=con.execute("SELECT * FROM flow_segments WHERE id=?",(sid,)).fetchone()
    if not row: raise ValueError('任务片段不存在')
    old=normalize_generation_mode(row['generation_mode'] if 'generation_mode' in row.keys() else 'FRAME')
    old_vmodel=normalize_segment_video_model(row['video_model'] if 'video_model' in row.keys() else '')
    if old==mode and (not clear_video_model or not old_vmodel):
        return {'changed':False,'rework':False,'mode':mode}
    active=bool(str(row['generation_command'] or '').strip()) or str(row['flow_status'] or '') in ('已提交','生成中','下载中','已完成')
    if active and not (allow_active_rework or force_silent):
        raise ValueError('当前片段已进入 Flow 执行；请从质检/返工入口切换模式，或勾选后点击【重新提交】。')
    if active and not force_silent:
        cmd=str(row['generation_command'] or '')
        out=str(row['flow_output_path'] or '')
        if cmd:
            con.execute("UPDATE flow_outputs SET qc_status='旧版本失效' WHERE segment_id=? AND command_id=?",(sid,cmd))
        elif out:
            con.execute("UPDATE flow_outputs SET qc_status='旧版本失效' WHERE segment_id=? AND output_path=?",(sid,out))
        if clear_video_model:
            con.execute("""UPDATE flow_segments SET generation_mode=?,video_model='',generation_command='',flow_status='待生成',
                flow_output_path='',flow_output_url='',flow_error='',flow_channel_key='R1',
                flow_retry_count=COALESCE(flow_retry_count,0)+1,flow_submitted_at='',flow_completed_at='',
                qc_status='退回',qc_note=?,qc_reject_reason=?,qc_decided_at=CURRENT_TIMESTAMP WHERE id=?""",
                (mode,reason,reason,sid))
        else:
            con.execute("""UPDATE flow_segments SET generation_mode=?,generation_command='',flow_status='待生成',
                flow_output_path='',flow_output_url='',flow_error='',flow_channel_key='R1',
                flow_retry_count=COALESCE(flow_retry_count,0)+1,flow_submitted_at='',flow_completed_at='',
                qc_status='退回',qc_note=?,qc_reject_reason=?,qc_decided_at=CURRENT_TIMESTAMP WHERE id=?""",
                (mode,reason,reason,sid))
        con.execute("INSERT OR REPLACE INTO flow_redo(segment_id,created_at) VALUES(?,CURRENT_TIMESTAMP)",(sid,))
        con.execute("DELETE FROM flow_recovery WHERE segment_id=?",(sid,))
        meta=con.execute("""SELECT r.name recipient_name,h.name host_name,v.performance_mode,fs.prompt
            FROM flow_segments fs JOIN videos v ON v.id=fs.video_id JOIN hosts h ON h.id=v.host_id
            JOIN recipients r ON r.id=h.recipient_id WHERE fs.id=?""",(sid,)).fetchone()
        if meta:
            con.execute("""INSERT INTO qc_decisions(segment_id,decision,reason,recipient_name,host_name,performance_mode,prompt_snapshot)
                VALUES(?,?,?,?,?,?,?)""",(sid,'退回',reason,meta['recipient_name'] or '',meta['host_name'] or '',meta['performance_mode'] or 'TALKING',meta['prompt'] or ''))
        from app.services.workflow import reconcile_video_qc
        reconcile_video_qc(int(row['video_id']), con)
        return {'changed':True,'rework':True,'mode':mode}
    if clear_video_model:
        con.execute("UPDATE flow_segments SET generation_mode=?,video_model='' WHERE id=?",(mode,sid))
    else:
        con.execute("UPDATE flow_segments SET generation_mode=? WHERE id=?",(mode,sid))
    return {'changed':True,'rework':False,'mode':mode}


def set_segment_generation_mode(segment_id, mode, *, allow_active_rework=False, force_silent=False, reason='切换生成模式', clear_video_model=False):
    """Write the single authoritative segment mode.

    Pre-execution changes only update the shared field. If the current revision has already
    entered Flow and ``allow_active_rework`` is true, supersede that revision through the
    existing redo queue so delayed old receipts remain stale by generation_command.
    """
    sid=int(segment_id); mode=normalize_generation_mode(mode)
    with connect() as con:
        return _set_segment_generation_mode_in_con(
            con, sid, mode, allow_active_rework=allow_active_rework, force_silent=force_silent, reason=reason, clear_video_model=clear_video_model
        )


def set_generation_mode_for_segments(segment_ids, mode, force_silent=False, clear_video_model=False):
    mode=normalize_generation_mode(mode); changed=blocked=0; changed_ids=[]
    ids=[int(x) for x in segment_ids]
    if not ids:
        return {'changed':0,'blocked':0,'mode':mode,'changed_ids':[]}
    with connect() as con:
        for sid in ids:
            try:
                result=_set_segment_generation_mode_in_con(
                    con, sid, mode, allow_active_rework=False, force_silent=force_silent, clear_video_model=clear_video_model
                )
                if result.get('changed'):
                    changed += 1
                    changed_ids.append(sid)
            except ValueError:
                blocked += 1
    return {'changed':changed,'blocked':blocked,'mode':mode,'changed_ids':changed_ids}


def set_segment_video_model(segment_id, video_model='flow_omni', *, duration_seconds=8, allow_active_rework=False, force_silent=False, reason='切换模型'):
    sid=int(segment_id)
    vmodel=normalize_segment_video_model(video_model)
    dur=int(duration_seconds or 8) if int(duration_seconds or 8) in (4,6,8) else 8
    with connect() as con:
        row=con.execute("SELECT * FROM flow_segments WHERE id=?",(sid,)).fetchone()
        if not row: raise ValueError('任务片段不存在')
        old_vmodel=normalize_segment_video_model(row['video_model'] if 'video_model' in row.keys() else '')
        if old_vmodel==vmodel:
            return {'changed':False,'rework':False,'video_model':vmodel}
        active=bool(str(row['generation_command'] or '').strip()) or str(row['flow_status'] or '') in ('已提交','生成中','下载中','已完成')
        if active and not (allow_active_rework or force_silent):
            raise ValueError('当前片段已进入 Flow 执行；请从质检/返工入口切换模型，或勾选后点击【重新提交】。')
        text=str(row['foreign_text'] or '')
        if vmodel == 'flow_omni':
            con.execute(
                """INSERT INTO flow_duration_choices(segment_id,dialogue,force_submit,duration,locked)
                   VALUES(?,?,1,?,1)
                   ON CONFLICT(segment_id) DO UPDATE SET dialogue=excluded.dialogue,force_submit=1,duration=excluded.duration,locked=1""",
                (sid, text, dur),
            )
            con.execute("UPDATE flow_segments SET video_model=?, flow_duration_seconds=? WHERE id=?", (vmodel, dur, sid))
        else:
            con.execute("UPDATE flow_segments SET video_model=? WHERE id=?", (vmodel, sid))
        if active and allow_active_rework and not force_silent:
            cmd=str(row['generation_command'] or '')
            out=str(row['flow_output_path'] or '')
            if cmd:
                con.execute("UPDATE flow_outputs SET qc_status='旧版本失效' WHERE segment_id=? AND command_id=?",(sid,cmd))
            elif out:
                con.execute("UPDATE flow_outputs SET qc_status='旧版本失效' WHERE segment_id=? AND output_path=?",(sid,out))
            con.execute("""UPDATE flow_segments SET video_model=?,generation_command='',flow_status='待生成',
                flow_output_path='',flow_output_url='',flow_error='',flow_channel_key='R1',
                flow_retry_count=COALESCE(flow_retry_count,0)+1,flow_submitted_at='',flow_completed_at='',
                qc_status='退回',qc_note=?,qc_reject_reason=?,qc_decided_at=CURRENT_TIMESTAMP WHERE id=?""",
                (vmodel,reason,reason,sid))
            con.execute("INSERT OR REPLACE INTO flow_redo(segment_id,created_at) VALUES(?,CURRENT_TIMESTAMP)",(sid,))
            con.execute("DELETE FROM flow_recovery WHERE segment_id=?",(sid,))
            meta=con.execute("""SELECT r.name recipient_name,h.name host_name,v.performance_mode,fs.prompt
                FROM flow_segments fs JOIN videos v ON v.id=fs.video_id JOIN hosts h ON h.id=v.host_id
                JOIN recipients r ON r.id=h.recipient_id WHERE fs.id=?""",(sid,)).fetchone()
            if meta:
                con.execute("""INSERT INTO qc_decisions(segment_id,decision,reason,recipient_name,host_name,performance_mode,prompt_snapshot)
                    VALUES(?,?,?,?,?,?,?)""",(sid,'退回',reason,meta['recipient_name'] or '',meta['host_name'] or '',meta['performance_mode'] or 'TALKING',meta['prompt'] or ''))
            from app.services.workflow import reconcile_video_qc
            reconcile_video_qc(int(row['video_id']), con)
            return {'changed':True,'rework':True,'video_model':vmodel}
        return {'changed':True,'rework':False,'video_model':vmodel}


def set_video_model_for_segments(segment_ids, video_model='flow_omni', duration_seconds=8, force_silent=True):
    vmodel=normalize_segment_video_model(video_model)
    dur=int(duration_seconds or 8) if int(duration_seconds or 8) in (4,6,8) else 8
    ids=[int(x) for x in segment_ids]
    if not ids:
        return {'changed':0,'blocked':0,'video_model':vmodel,'duration':dur,'changed_ids':[]}
    changed=blocked=0
    changed_ids=[]
    with connect() as con:
        for sid in ids:
            row=con.execute("SELECT * FROM flow_segments WHERE id=?",(sid,)).fetchone()
            if not row:
                blocked += 1
                continue
            active=bool(str(row['generation_command'] or '').strip()) or str(row['flow_status'] or '') in ('已提交','生成中','下载中','已完成')
            if active and not force_silent:
                blocked += 1
                continue
            text=str(row['foreign_text'] or '')
            con.execute(
                "UPDATE flow_segments SET video_model=?, flow_duration_seconds=? WHERE id=?",
                (vmodel, dur, sid),
            )
            if vmodel == 'flow_omni':
                con.execute(
                    """INSERT INTO flow_duration_choices(segment_id,dialogue,force_submit,duration,locked)
                       VALUES(?,?,1,?,1)
                       ON CONFLICT(segment_id) DO UPDATE SET dialogue=excluded.dialogue,force_submit=1,duration=excluded.duration,locked=1""",
                    (sid, text, dur),
                )
            changed += 1
            changed_ids.append(sid)
    return {'changed':changed,'blocked':blocked,'video_model':vmodel,'duration':dur,'changed_ids':changed_ids}


def set_first_segment_mode_for_videos(video_ids, mode='MATERIAL', force_silent=False):
    vids=sorted({int(x) for x in video_ids}); ids=[]
    if not vids: return {'changed':0,'blocked':0,'mode':normalize_generation_mode(mode),'changed_ids':[]}
    q=','.join('?' for _ in vids)
    with connect() as con:
        rows=con.execute(f"""SELECT fs.id FROM flow_segments fs
            JOIN (SELECT video_id,MIN(seg_seq) first_seq FROM flow_segments WHERE video_id IN ({q}) GROUP BY video_id) x
              ON x.video_id=fs.video_id AND x.first_seq=fs.seg_seq
            ORDER BY fs.video_id,fs.id""",vids).fetchall()
        ids=[int(r['id']) for r in rows]
    return set_generation_mode_for_segments(ids,mode,force_silent=force_silent)


def sync_dialogue_into_prompt(prompt_text, old_dialogue='', new_dialogue=''):
    import re as _re
    prompt_str = str(prompt_text or '').strip()
    new_clean = ' '.join(str(new_dialogue or '').split())
    old_clean = ' '.join(str(old_dialogue or '').split())
    if not prompt_str or not new_clean:
        return prompt_str
    if _re.search(r'(?m)^(文案\s*[:：]\s*).*$', prompt_str):
        return _re.sub(
            r'(?m)^(文案\s*[:：]\s*).*$',
            lambda m: f"{m.group(1)}{new_clean}",
            prompt_str,
            count=1,
        )
    if _re.search(r'(文案\s*[:：]\s*)([^\n\r]*)', prompt_str):
        return _re.sub(
            r'(文案\s*[:：]\s*)([^\n\r]*)',
            lambda m: f"{m.group(1)}{new_clean}",
            prompt_str,
            count=1,
        )
    if old_clean and old_clean in prompt_str:
        return prompt_str.replace(old_clean, new_clean, 1)
    return prompt_str


def _cleanup_deleted_segment_downstream(con, sid):
    sid = int(sid)
    row = con.execute("SELECT generation_command, flow_output_path FROM flow_segments WHERE id=?", (sid,)).fetchone()
    commands = set()
    paths = []
    if row:
        if str(row["generation_command"] or "").strip():
            commands.add(str(row["generation_command"]).strip())
        if str(row["flow_output_path"] or "").strip():
            paths.append(str(row["flow_output_path"]).strip())
    for old in con.execute("SELECT command_id, output_path FROM flow_outputs WHERE segment_id=?", (sid,)):
        if str(old[0] or "").strip():
            commands.add(str(old[0]).strip())
        if str(old[1] or "").strip():
            paths.append(str(old[1]).strip())
    for old in con.execute("SELECT command_id, download_path FROM flow_dispatches WHERE segment_id=?", (sid,)):
        if str(old[0] or "").strip():
            commands.add(str(old[0]).strip())
        if str(old[1] or "").strip():
            paths.append(str(old[1]).strip())
    for cmd in commands:
        con.execute("INSERT OR IGNORE INTO flow_obsolete_segments(segment_id,command_id) VALUES(?,?)", (sid, cmd))
    for table in (
        "flow_dispatches", "flow_outputs", "flow_redo", "flow_failure_attempts",
        "flow_recovery", "speech_analysis", "local_qc_results", "ai_qc_results",
        "qc_decisions", "flow_duration_choices", "prompt_submission_history",
    ):
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            con.execute(f"DELETE FROM {table} WHERE segment_id=?", (sid,))
    return paths


def _assert_prompt_copy_editable(con, video_id, *, allow_submitted=True):
    rows=con.execute("SELECT * FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id",(int(video_id),)).fetchall()
    if allow_submitted:
        return rows
    for row in rows:
        active=bool(str(row['generation_command'] or '').strip()) or str(row['prompt_review_status'] or '')=='已提交' or str(row['flow_status'] or '') not in ('','待生成','失败','已准备')
        if active:
            raise ValueError('当前完整视频已有片段进入 Flow，不能再调整文案结构。')
        for table in ('flow_outputs','flow_redo','flow_recovery','flow_dispatches'):
            if con.execute(f'SELECT 1 FROM {table} WHERE segment_id=? LIMIT 1',(int(row['id']),)).fetchone():
                raise ValueError('当前完整视频已有下游记录，不能再调整文案结构。')
    return rows


def _save_manual_segment_type(con, sid, text, mode=None, source=None):
    import json
    from app.services.performance_types import choices
    from app.core import work_dates
    row=con.execute('SELECT fs.video_id,v.performance_mode FROM flow_segments fs JOIN videos v ON v.id=fs.video_id WHERE fs.id=?',(sid,)).fetchone()
    saved=choices(con,row['video_id'])
    previous=saved.get(str(sid),{})
    mode=mode or previous.get('mode') or row['performance_mode']
    if mode not in ('TALKING','PRAYING'):raise ValueError('请选择睁眼或闭眼')
    src=source or previous.get('source') or 'manual'
    saved[str(sid)]={'text':text,'mode':mode,'source':src}
    valid={str(r[0]) for r in con.execute('SELECT id FROM flow_segments WHERE video_id=?',(row['video_id'],))}
    data={'work_date':work_dates.video_work_date(con,row['video_id']),'segments':{k:v for k,v in saved.items() if k in valid}}
    con.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
        (f"segment_eye_types:{row['video_id']}",json.dumps(data,ensure_ascii=False)))


def set_prompt_segment_type(segment_id, mode):
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT video_id,foreign_text FROM flow_segments WHERE id=?',(int(segment_id),)).fetchone()
        if not row:raise ValueError('任务片段不存在')
        _assert_prompt_copy_editable(con,row['video_id'])
        _reset_prompt_after_copy_change(con,int(segment_id),row['foreign_text'],preserve_and_sync_prompt=False)
        _save_manual_segment_type(con,int(segment_id),row['foreign_text'],mode,source='manual')


def _reset_prompt_after_copy_change(con, sid, text, mode=None, source=None, manual_lock_val=1, preserve_and_sync_prompt=True):
    from app.services.speech_preparation import timing_metadata
    meta=timing_metadata(text)
    cur_row=con.execute("SELECT foreign_text, prompt, video_model FROM flow_segments WHERE id=?", (int(sid),)).fetchone()
    old_text=str(cur_row["foreign_text"] or "") if cur_row else ""
    old_prompt=str(cur_row["prompt"] or "").strip() if cur_row else ""
    vmodel=str(cur_row["video_model"] or "") if cur_row else ""
    est_dur=float(meta.get('estimated_speech_duration') or 0)
    flow_dur=8 if vmodel=='flow_omni' else int(meta.get('flow_duration_seconds') or 0)
    t_status='MANUAL_DURATION_LOCK' if vmodel=='flow_omni' else str(meta.get('timing_status') or '')
    if preserve_and_sync_prompt and old_prompt:
        synced_prompt = sync_dialogue_into_prompt(old_prompt, old_text, text)
        con.execute("""UPDATE flow_segments SET foreign_text=?,prompt=?,status='文案已改',
            prompt_review_status='待检查',
            estimated_speech_duration=?,flow_duration_seconds=?,timing_status=?,manual_text_lock=? WHERE id=?""",
            (text,synced_prompt,est_dur,flow_dur,t_status,int(manual_lock_val),int(sid)))
    else:
        con.execute("""UPDATE flow_segments SET foreign_text=?,prompt='',ai_original_prompt='',status='待处理',model='',
            input_tokens=0,cached_tokens=0,output_tokens=0,cost_usd=0,prompt_review_status='待检查',prompt_submitted_at='',
            estimated_speech_duration=?,flow_duration_seconds=?,timing_status=?,manual_text_lock=? WHERE id=?""",
            (text,est_dur,flow_dur,t_status,int(manual_lock_val),int(sid)))
    _save_manual_segment_type(con,sid,text,mode=mode,source=source)


def edit_prompt_segment_text(segment_id, text):
    """Edit one segment (including already-submitted segments); blank text deletes it; multiline text splits into consecutive segments. Never touches video numbering."""
    sid=int(segment_id)
    parts=[' '.join(line.split()) for line in str(text or '').replace('\r\n','\n').replace('\r','\n').split('\n')]
    parts=[p for p in parts if p]
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT id,video_id,seg_seq,COALESCE(generation_mode,'FRAME') generation_mode,COALESCE(video_model,'') video_model,COALESCE(segment_rule,'') segment_rule FROM flow_segments WHERE id=?",(sid,)).fetchone()
        if not row: raise ValueError('任务片段不存在')
        vid=int(row['video_id'])
        rows=_assert_prompt_copy_editable(con,vid)
        from app.services.performance_types import choices
        from app.services.speech_preparation import timing_metadata
        saved_choices=choices(con,vid)
        prev_choice=saved_choices.get(str(sid),{})
        inherited_mode=prev_choice.get('mode')
        inherited_source=prev_choice.get('source')
        new_sids=[]
        if not parts:
            _cleanup_deleted_segment_downstream(con, sid)
            con.execute("DELETE FROM flow_segments WHERE id=?",(sid,))
        else:
            lock_val = 2 if len(parts) > 1 else 1
            _reset_prompt_after_copy_change(con,sid,parts[0],mode=inherited_mode,source=inherited_source,manual_lock_val=lock_val,preserve_and_sync_prompt=True)
            for idx,part in enumerate(parts[1:],1):
                meta=timing_metadata(part)
                gmode=str(row['generation_mode'] or 'FRAME')
                vmodel=str(row['video_model'] or '')
                est_dur=float(meta.get('estimated_speech_duration') or 0)
                flow_dur=8 if vmodel=='flow_omni' else int(meta.get('flow_duration_seconds') or 8)
                t_status='MANUAL_DURATION_LOCK' if vmodel=='flow_omni' else str(meta.get('timing_status') or '')
                cur=con.execute("""INSERT INTO flow_segments(
                    video_id,seg_seq,foreign_text,prompt,ai_original_prompt,status,model,
                    generation_mode,video_model,segment_rule,prompt_review_status,prompt_submitted_at,
                    estimated_speech_duration,flow_duration_seconds,timing_status,manual_text_lock
                ) VALUES(?,?,?,'','','待处理','',?,?,?,'待检查','',?,?,?,2)""",
                (vid,-1000-idx,part,gmode,vmodel,str(row['segment_rule'] or ''),est_dur,flow_dur,t_status))
                child_id=int(cur.lastrowid)
                new_sids.append(child_id)
                _save_manual_segment_type(con,child_id,part,mode=inherited_mode,source=inherited_source)
        # Compact only segment sequence inside the same complete video, inserting new_sids right after sid.
        ordered_ids=[]
        for r in rows:
            rid=int(r['id'])
            if rid==sid:
                if parts:
                    ordered_ids.append(sid)
                    ordered_ids.extend(new_sids)
            else:
                ordered_ids.append(rid)
        for i,rid in enumerate(ordered_ids,1): con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?",(-i,int(rid)))
        for i,rid in enumerate(ordered_ids,1): con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?",(i,int(rid)))
        script_rows=con.execute("SELECT foreign_text FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id",(vid,)).fetchall()
        production=' '.join(str(r['foreign_text'] or '').strip() for r in script_rows if str(r['foreign_text'] or '').strip())
        con.execute("UPDATE videos SET script=?,production_script=?,edit_status='等待片段' WHERE id=?",(production,production,vid))
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='davinci_video_state'").fetchone():
            con.execute("DELETE FROM davinci_video_state WHERE video_id=?",(vid,))
    return {'segment_ids': ([sid]+new_sids) if parts else [], 'next_segment_id': new_sids[0] if new_sids else (sid if parts else None)}


_AUTO_MERGE_SIG_CACHE = {}


def auto_merge_ungenerated_short_segments(work_date=None, max_words=24):
    """Automatically merge adjacent ungenerated (no prompt yet) segments within the same video
    and same eye/performance mode whenever their combined word count is <= max_words (default 24).
    """
    import json
    from app.core import work_dates
    from app.services.performance_types import choices
    from app.services.speech_preparation import timing_metadata
    from app.services.text_processing import _words

    limit = max(1, int(max_words or 24))
    day = work_dates.normalize_scope(work_date) if work_date else work_dates.active()
    with read_connection(day) as rcon:
        vrows = rcon.execute("""
            SELECT v.id, v.performance_mode, COUNT(fs.id) AS seg_cnt, MAX(fs.id) AS max_sid
            FROM videos v
            JOIN flow_segments fs ON fs.video_id = v.id
            WHERE TRIM(COALESCE(fs.prompt, '')) = ''
              AND COALESCE(fs.manual_text_lock, 0) < 2
              AND COALESCE(fs.prompt_review_status, '待检查') NOT IN ('已提交', '已放弃')
              AND COALESCE(fs.flow_status, '') != '已放弃'
              AND COALESCE(v.edit_status, '') != '已放弃'
            GROUP BY v.id
            HAVING COUNT(fs.id) >= 2
            ORDER BY v.id
        """).fetchall()
    if not vrows:
        return 0

    sig = tuple((int(r["id"]), int(r["seg_cnt"]), int(r["max_sid"])) for r in vrows)
    if _AUTO_MERGE_SIG_CACHE.get((day, limit)) == sig:
        return 0

    merged_videos = 0
    for vrow in vrows:
        vid = int(vrow["id"])
        v_mode = "PRAYING" if str(vrow["performance_mode"] or "").upper() == "PRAYING" else "TALKING"
        with connect() as con:
            try:
                con.execute("BEGIN IMMEDIATE")
                rows = _assert_prompt_copy_editable(con, vid, allow_submitted=False)
            except Exception:
                continue
            if len(rows) <= 1:
                continue
            saved = choices(con, vid)
            style_modes_by_sid = {}
            if v_mode == "PRAYING":
                try:
                    from app.services import eye_states
                    from app.services.speech_preparation import prepare_swahili_speech
                    srow = con.execute("SELECT payload FROM video_source_styles WHERE video_id=?", (vid,)).fetchone()
                    snap = json.loads(srow[0]).get("外文内容", {}) if srow and srow[0] else {}
                    blks = [(t.strip(), m) for t, m in eye_states.blocks(snap, "PRAYING") if t.strip()]
                    if any(m == "TALKING" for _, m in blks):
                        blk_word_modes = []
                        for btxt, bmode in blks:
                            prep_txt = prepare_swahili_speech(btxt).spoken_text
                            for w in _words(prep_txt):
                                blk_word_modes.append(bmode)
                        total_row_words = sum(len(_words(str(r["foreign_text"] or ""))) for r in rows if int(r["seg_seq"] or 0) < 1000)
                        if blk_word_modes and len(blk_word_modes) == total_row_words:
                            pos_w = 0
                            for r in rows:
                                if int(r["seg_seq"] or 0) >= 1000:
                                    continue
                                rw = _words(str(r["foreign_text"] or ""))
                                span_modes = set(blk_word_modes[pos_w : pos_w + len(rw)])
                                pos_w += len(rw)
                                if "TALKING" in span_modes:
                                    style_modes_by_sid[int(r["id"])] = "TALKING"
                except Exception:
                    pass

            from app.services.speech_preparation import _instruction_speech_seconds, ensure_terminal_period
            items = []
            for r in rows:
                sid = int(r["id"])
                txt = " ".join(str(r["foreign_text"] or "").split())
                is_aux = int(r["seg_seq"] or 0) >= 1000 or txt.startswith("[LEGACY_AUX]")
                has_prompt = bool(str(r["prompt"] or "").strip())
                is_manual_split = int(r["manual_text_lock"] or 0) >= 2
                is_submitted = str(r["prompt_review_status"] or "待检查") == "已提交"
                ch = saved.get(str(sid), {})
                eff_mode = (style_modes_by_sid.get(sid) or ch.get("mode") or v_mode or "TALKING").upper()
                eff_mode = "PRAYING" if eff_mode == "PRAYING" else "TALKING"
                eff_source = "sheet_color" if sid in style_modes_by_sid else (ch.get("source") or ("sheet_color" if ch else "unclassified"))
                is_locked_red = (v_mode == "PRAYING" and eff_mode == "TALKING")
                items.append({
                    "id": sid,
                    "text": txt,
                    "words": len(_words(txt)),
                    "mode": eff_mode,
                    "source": eff_source,
                    "vmodel": str(r["video_model"] or ""),
                    "can_merge": (not is_aux) and (not has_prompt) and (not is_manual_split) and (not is_submitted) and (not is_locked_red) and bool(txt),
                })

            removed_ids = []
            guard = 0
            while len(items) > 1 and guard < 300:
                guard += 1
                candidates = []
                for i, cur in enumerate(items):
                    if not cur["can_merge"] or cur["words"] <= 0 or cur["words"] >= limit:
                        continue
                    if i > 0:
                        prev = items[i - 1]
                        comb_txt = f"{prev['text']} {cur['text']}".strip()
                        if prev["can_merge"] and prev["mode"] == cur["mode"] and 0 < prev["words"] + cur["words"] <= limit and _instruction_speech_seconds(comb_txt) <= 7.8:
                            comb = prev["words"] + cur["words"]
                            candidates.append((min(prev["words"], cur["words"]), abs(16 - comb), i - 1, i))
                    if i + 1 < len(items):
                        nxt = items[i + 1]
                        comb_txt = f"{cur['text']} {nxt['text']}".strip()
                        if nxt["can_merge"] and cur["mode"] == nxt["mode"] and 0 < cur["words"] + nxt["words"] <= limit and _instruction_speech_seconds(comb_txt) <= 7.8:
                            comb = cur["words"] + nxt["words"]
                            candidates.append((min(cur["words"], nxt["words"]), abs(16 - comb), i, i + 1))
                if not candidates:
                    break
                _, _, left_i, right_i = min(candidates, key=lambda x: (x[0], x[1], x[2]))
                left_item = items[left_i]
                right_item = items[right_i]
                merged_txt = ensure_terminal_period(f"{left_item['text']} {right_item['text']}".strip())
                left_item["text"] = merged_txt
                left_item["words"] = len(_words(merged_txt))
                if left_item["source"] == "unclassified" and right_item["source"] != "unclassified":
                    left_item["source"] = right_item["source"]
                removed_ids.append(right_item["id"])
                del items[right_i]

            if not removed_ids:
                continue

            for rem_id in removed_ids:
                con.execute("DELETE FROM flow_duration_choices WHERE segment_id=?", (int(rem_id),))
                con.execute("DELETE FROM flow_segments WHERE id=?", (int(rem_id),))

            for seq, item in enumerate(items, 1):
                con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?", (-seq, int(item["id"])))
            for seq, item in enumerate(items, 1):
                meta = timing_metadata(item["text"])
                vmodel = item["vmodel"]
                est_dur = float(meta.get("estimated_speech_duration") or 0)
                flow_dur = 8 if vmodel == "flow_omni" else int(meta.get("flow_duration_seconds") or 8)
                t_status = "MANUAL_DURATION_LOCK" if vmodel == "flow_omni" else str(meta.get("timing_status") or "")
                con.execute("""
                    UPDATE flow_segments
                    SET seg_seq=?, foreign_text=?, estimated_speech_duration=?, flow_duration_seconds=?, timing_status=?,
                        manual_text_lock=CASE WHEN COALESCE(manual_text_lock,0)>=2 THEN manual_text_lock ELSE 1 END
                    WHERE id=?
                """, (seq, item["text"], est_dur, flow_dur, t_status, int(item["id"])))

            new_saved = {
                str(item["id"]): {
                    "text": item["text"],
                    "mode": item["mode"],
                    "source": item["source"] if item["source"] in ("sheet_color", "manual") else "sheet_color",
                }
                for item in items
            }
            data = {
                "work_date": work_dates.video_work_date(con, vid),
                "source": "sheet_color",
                "segments": new_saved,
            }
            con.execute(
                "INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"segment_eye_types:{vid}", json.dumps(data, ensure_ascii=False)),
            )
            production = " ".join(item["text"] for item in items if item["text"])
            con.execute("UPDATE videos SET script=?, production_script=? WHERE id=?", (production, production, vid))
            merged_videos += 1
    if merged_videos == 0:
        _AUTO_MERGE_SIG_CACHE[(day, limit)] = sig
    else:
        _AUTO_MERGE_SIG_CACHE.pop((day, limit), None)
    return merged_videos


def ai_reorganize_video_segments(video_ids, *, target_sec=7.0, max_sec=7.8, hard_max_sec=8.0):
    """Re-segment the specified videos' scripts so each segment is balanced around ~7s
    (strictly <= 8s when splittable) WITHOUT modifying any character of the original text.
    Preserves contiguous TALKING/PRAYING performance_mode blocks, sheet_color/manual sources,
    and updates existing prompts if every segment already had a prompt.
    """
    import json
    from app.core import work_dates
    from app.services.performance_types import choices
    from app.services.text_processing import _words
    from app.services.speech_preparation import (
        _instruction_speech_seconds,
        balance_segments_verbatim,
        ensure_terminal_period,
        prepare_swahili_speech,
        timing_metadata,
    )

    clean_vids = sorted({int(v) for v in (video_ids or []) if v is not None and int(v) > 0})
    if not clean_vids:
        return {
            "videos_processed": 0,
            "videos_changed": 0,
            "old_segments": 0,
            "new_segments": 0,
            "avg_seconds": 0.0,
            "max_seconds": 0.0,
            "changed_segment_ids": [],
        }

    videos_processed = 0
    videos_changed = 0
    videos_skipped_locked = 0
    old_seg_total = 0
    new_seg_total = 0
    all_new_durs = []
    changed_segment_ids = []

    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        for vid in clean_vids:
            vrow = con.execute("SELECT id, performance_mode FROM videos WHERE id=?", (vid,)).fetchone()
            if not vrow:
                continue
            v_mode = "PRAYING" if str(vrow["performance_mode"] or "").upper() == "PRAYING" else "TALKING"
            rows = list(con.execute("SELECT * FROM flow_segments WHERE video_id=? ORDER BY seg_seq, id", (vid,)).fetchall())
            if not rows:
                continue

            normal_rows = []
            aux_rows = []
            for r in rows:
                txt = " ".join(str(r["foreign_text"] or "").split()).strip()
                is_aux = int(r["seg_seq"] or 0) >= 1000 or txt.startswith("[LEGACY_AUX]")
                if is_aux:
                    aux_rows.append(r)
                elif txt:
                    normal_rows.append(r)

            if not normal_rows:
                continue

            videos_processed += 1
            old_seg_total += len(normal_rows)
            saved = choices(con, vid)

            # Resolve red (TALKING) vs black (PRAYING) blocks in PRAYING scripts so red segments are never merged with normal segments
            groups = []
            used_style_blocks = False
            if v_mode == "PRAYING":
                try:
                    from app.services import eye_states
                    srow = con.execute("SELECT payload FROM video_source_styles WHERE video_id=?", (vid,)).fetchone()
                    snap = json.loads(srow[0]).get("外文内容", {}) if srow and srow[0] else {}
                    blks = [(t.strip(), m) for t, m in eye_states.blocks(snap, "PRAYING") if t.strip()]
                    if any(m == "TALKING" for _, m in blks):
                        prep_blks = []
                        all_blk_words = []
                        for btxt, bmode in blks:
                            ptxt = " ".join(prepare_swahili_speech(btxt).spoken_text.split()).strip()
                            if ptxt:
                                prep_blks.append((ptxt, "PRAYING" if bmode == "PRAYING" else "TALKING"))
                                all_blk_words.extend(_words(ptxt))
                        row_words = _words(" ".join(str(r["foreign_text"] or "") for r in normal_rows))
                        # First check if current normal_rows already have pure TALKING/PRAYING segments matching saved choices
                        saved_talking_sids = {
                            int(r["id"])
                            for r in normal_rows
                            if str(saved.get(str(r["id"]), {}).get("mode") or "").upper() == "TALKING"
                        }
                        if saved_talking_sids:
                            for r in normal_rows:
                                sid = int(r["id"])
                                txt = " ".join(str(r["foreign_text"] or "").split()).strip()
                                ch = saved.get(str(sid), {})
                                eff_mode = "TALKING" if sid in saved_talking_sids else "PRAYING"
                                eff_source = ch.get("source") or "sheet_color"
                                if eff_mode == "TALKING":
                                    # Red segment inside PRAYING video: isolate it so it never merges with PRAYING or other segments
                                    groups.append({
                                        "mode": "TALKING",
                                        "source": eff_source,
                                        "texts": [txt],
                                        "rows": [r],
                                        "locked_red": True,
                                    })
                                elif groups and groups[-1]["mode"] == "PRAYING" and not groups[-1].get("locked_red"):
                                    groups[-1]["texts"].append(txt)
                                    groups[-1]["rows"].append(r)
                                else:
                                    groups.append({
                                        "mode": "PRAYING",
                                        "source": eff_source,
                                        "texts": [txt],
                                        "rows": [r],
                                        "locked_red": False,
                                    })
                            used_style_blocks = True
                        elif prep_blks and all_blk_words == row_words:
                            for ptxt, bmode in prep_blks:
                                groups.append({
                                    "mode": bmode,
                                    "source": "sheet_color",
                                    "texts": [ptxt],
                                    "rows": list(normal_rows),
                                    "locked_red": (bmode == "TALKING"),
                                })
                            used_style_blocks = True
                except Exception:
                    pass

            if not used_style_blocks:
                for r in normal_rows:
                    sid = int(r["id"])
                    txt = " ".join(str(r["foreign_text"] or "").split()).strip()
                    ch = saved.get(str(sid), {})
                    eff_mode = (ch.get("mode") or v_mode or "TALKING").upper()
                    eff_mode = "PRAYING" if eff_mode == "PRAYING" else "TALKING"
                    eff_source = ch.get("source") or ("sheet_color" if ch else "unclassified")
                    is_locked_red = (v_mode == "PRAYING" and eff_mode == "TALKING")
                    if is_locked_red:
                        groups.append({
                            "mode": "TALKING",
                            "source": eff_source,
                            "texts": [txt],
                            "rows": [r],
                            "locked_red": True,
                        })
                    elif groups and groups[-1]["mode"] == eff_mode and not groups[-1].get("locked_red"):
                        groups[-1]["texts"].append(txt)
                        groups[-1]["rows"].append(r)
                        if groups[-1]["source"] == "unclassified" and eff_source != "unclassified":
                            groups[-1]["source"] = eff_source
                    else:
                        groups.append({
                            "mode": eff_mode,
                            "source": eff_source,
                            "texts": [txt],
                            "rows": [r],
                            "locked_red": False,
                        })

            planned = []
            for grp in groups:
                joined_txt = " ".join(grp["texts"]).strip()
                if grp.get("locked_red") and _instruction_speech_seconds(joined_txt) <= hard_max_sec:
                    # Red (TALKING) segment in a closed-eye (PRAYING) script is locked and never merged or re-cut if <= 8.0s
                    balanced_txts = [ensure_terminal_period(joined_txt)]
                else:
                    balanced_txts = balance_segments_verbatim(
                        joined_txt,
                        target_sec=target_sec,
                        max_sec=max_sec,
                        hard_max_sec=hard_max_sec,
                    )
                for btxt in balanced_txts:
                    if not btxt:
                        continue
                    planned.append({
                        "text": ensure_terminal_period(btxt),
                        "mode": grp["mode"],
                        "source": grp["source"],
                        "template_rows": grp["rows"],
                    })

            orig_full = " ".join(" ".join(str(r["foreign_text"] or "").split()).strip() for r in normal_rows).strip()
            new_full = " ".join(p["text"] for p in planned).strip()
            if _words(orig_full) != _words(new_full) or not planned:
                # Safety guard: never allow any word mutation
                for r in normal_rows:
                    all_new_durs.append(_instruction_speech_seconds(str(r["foreign_text"] or "")))
                new_seg_total += len(normal_rows)
                continue

            old_texts = [" ".join(str(r["foreign_text"] or "").split()).strip() for r in normal_rows]
            new_texts = [p["text"] for p in planned]
            for btxt in new_texts:
                all_new_durs.append(_instruction_speech_seconds(btxt))
            new_seg_total += len(new_texts)

            if old_texts == new_texts:
                # Ensure manual_text_lock=2 so auto_merge doesn't undo it
                for r in normal_rows:
                    con.execute("UPDATE flow_segments SET manual_text_lock=2 WHERE id=?", (int(r["id"]),))
                continue

            videos_changed += 1
            old_count = len(normal_rows)
            new_count = len(planned)
            first_gmode = str(normal_rows[0]["generation_mode"] or "FRAME")
            rest_gmode = str(normal_rows[1]["generation_mode"] or "FRAME") if len(normal_rows) > 1 else first_gmode

            kept_sids = []
            for idx, item in enumerate(planned):
                btxt = item["text"]
                meta = timing_metadata(btxt)
                est_dur = float(meta.get("estimated_speech_duration") or 0)
                t_rows = item["template_rows"]
                ref_row = t_rows[min(idx, len(t_rows) - 1)]
                vmodel = str(ref_row["video_model"] or "")
                seg_rule = str(ref_row["segment_rule"] or "")
                gmode = first_gmode if idx == 0 else (
                    str(normal_rows[idx]["generation_mode"] or rest_gmode) if idx < old_count else rest_gmode
                )
                flow_dur = 8 if vmodel == "flow_omni" else int(meta.get("flow_duration_seconds") or 8)
                t_status = "MANUAL_DURATION_LOCK" if vmodel == "flow_omni" else str(meta.get("timing_status") or "")

                if idx < old_count:
                    sid = int(normal_rows[idx]["id"])
                    old_t = " ".join(str(normal_rows[idx]["foreign_text"] or "").split()).strip()
                    old_p = str(normal_rows[idx]["prompt"] or "").strip()
                    if old_t == btxt:
                        con.execute(
                            """UPDATE flow_segments
                               SET generation_mode=?, estimated_speech_duration=?, flow_duration_seconds=?,
                                   timing_status=?, manual_text_lock=2
                               WHERE id=?""",
                            (gmode, est_dur, flow_dur, t_status, sid),
                        )
                    elif old_p:
                        synced_p = sync_dialogue_into_prompt(old_p, old_t, btxt)
                        con.execute(
                            """UPDATE flow_segments
                               SET foreign_text=?, prompt=?, status='文案已改', prompt_review_status='待检查',
                                   generation_mode=?, estimated_speech_duration=?, flow_duration_seconds=?,
                                   timing_status=?, manual_text_lock=2
                               WHERE id=?""",
                            (btxt, synced_p, gmode, est_dur, flow_dur, t_status, sid),
                        )
                    else:
                        con.execute(
                            """UPDATE flow_segments
                               SET foreign_text=?, prompt='', ai_original_prompt='', status='待处理', model='',
                                   input_tokens=0, cached_tokens=0, output_tokens=0, cost_usd=0,
                                   prompt_review_status='待检查', prompt_submitted_at='',
                                   generation_mode=?, estimated_speech_duration=?, flow_duration_seconds=?,
                                   timing_status=?, manual_text_lock=2
                               WHERE id=?""",
                            (btxt, gmode, est_dur, flow_dur, t_status, sid),
                        )
                    kept_sids.append((sid, item))
                    changed_segment_ids.append(sid)
                else:
                    # Try to sync prompt from template row if template row had a prompt
                    tmpl_p = str(ref_row["prompt"] or "").strip()
                    tmpl_t = " ".join(str(ref_row["foreign_text"] or "").split()).strip()
                    synced_p = sync_dialogue_into_prompt(tmpl_p, tmpl_t, btxt) if tmpl_p else ""
                    new_status = "文案已改" if synced_p else "待处理"
                    cur = con.execute(
                        """INSERT INTO flow_segments(
                            video_id, seg_seq, foreign_text, prompt, ai_original_prompt, status, model,
                            generation_mode, video_model, segment_rule, prompt_review_status, prompt_submitted_at,
                            estimated_speech_duration, flow_duration_seconds, timing_status, manual_text_lock
                        ) VALUES(?,?,?,?,?,?,?, ?,?,?,'待检查','', ?,?,?,2)""",
                        (
                            vid,
                            -2000 - idx,
                            btxt,
                            synced_p,
                            "",
                            new_status,
                            str(ref_row["model"] or "") if synced_p else "",
                            gmode,
                            vmodel,
                            seg_rule,
                            est_dur,
                            flow_dur,
                            t_status,
                        ),
                    )
                    child_id = int(cur.lastrowid)
                    kept_sids.append((child_id, item))
                    changed_segment_ids.append(child_id)

            if old_count > new_count:
                for rem_row in normal_rows[new_count:]:
                    rem_sid = int(rem_row["id"])
                    _cleanup_deleted_segment_downstream(con, rem_sid)
                    con.execute("DELETE FROM flow_segments WHERE id=?", (rem_sid,))

            # Renumber normal segments 1..N
            for seq, (sid, _) in enumerate(kept_sids, 1):
                con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?", (-seq, int(sid)))
            for seq, (sid, _) in enumerate(kept_sids, 1):
                con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?", (seq, int(sid)))

            # Save eye types for all kept segments
            new_saved = {}
            for sid, item in kept_sids:
                src = item["source"] if item["source"] in ("sheet_color", "manual") else "sheet_color"
                new_saved[str(sid)] = {
                    "text": item["text"],
                    "mode": item["mode"],
                    "source": src,
                }
            data = {
                "work_date": work_dates.video_work_date(con, vid),
                "source": "sheet_color",
                "segments": new_saved,
            }
            con.execute(
                "INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"segment_eye_types:{vid}", json.dumps(data, ensure_ascii=False)),
            )
            production = " ".join(item["text"] for _, item in kept_sids if item["text"]).strip()
            con.execute(
                "UPDATE videos SET script=?, production_script=?, edit_status=CASE WHEN COALESCE(edit_status,'')='已放弃' THEN '已放弃' ELSE '等待片段' END WHERE id=?",
                (production, production, vid),
            )
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='davinci_video_state'").fetchone():
                con.execute("DELETE FROM davinci_video_state WHERE video_id=?", (vid,))

    _AUTO_MERGE_SIG_CACHE.clear()
    avg_sec = (sum(all_new_durs) / len(all_new_durs)) if all_new_durs else 0.0
    max_sec_actual = max(all_new_durs) if all_new_durs else 0.0
    return {
        "videos_processed": videos_processed,
        "videos_changed": videos_changed,
        "videos_skipped_locked": videos_skipped_locked,
        "old_segments": old_seg_total,
        "new_segments": new_seg_total,
        "avg_seconds": round(avg_sec, 2),
        "max_seconds": round(max_sec_actual, 2),
        "changed_segment_ids": changed_segment_ids,
    }


def merge_prompt_segment(segment_id, direction, mode=None):
    sid=int(segment_id); direction=str(direction or '').lower()
    if direction not in ('prev','next'): raise ValueError('无效合并方向')
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT id,video_id,seg_seq,foreign_text FROM flow_segments WHERE id=?",(sid,)).fetchone()
        if not row: raise ValueError('任务片段不存在')
        rows=_assert_prompt_copy_editable(con,int(row['video_id']))
        pos=next((i for i,r in enumerate(rows) if int(r['id'])==sid),-1)
        target_pos=pos-1 if direction=='prev' else pos+1
        if pos<0 or target_pos<0 or target_pos>=len(rows): raise ValueError('当前片段在该方向没有可合并的相邻片段')
        target=rows[target_pos]
        current=' '.join(str(row['foreign_text'] or '').split()); other=' '.join(str(target['foreign_text'] or '').split())
        if direction=='prev':
            keep=int(target['id']); remove=sid; merged=(other+' '+current).strip()
        else:
            keep=sid; remove=int(target['id']); merged=(current+' '+other).strip()
        _reset_prompt_after_copy_change(con,keep,merged,preserve_and_sync_prompt=True)
        _cleanup_deleted_segment_downstream(con,remove)
        con.execute("DELETE FROM flow_segments WHERE id=?",(remove,))
        _save_manual_segment_type(con,keep,merged,mode,source='manual' if mode else None)
        remaining=con.execute("SELECT id FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id",(int(row['video_id']),)).fetchall()
        for i,r in enumerate(remaining,1): con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?",(-i,int(r['id'])))
        for i,r in enumerate(remaining,1): con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?",(i,int(r['id'])))
        script_rows=con.execute("SELECT foreign_text FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id",(int(row['video_id']),)).fetchall()
        production=' '.join(str(r['foreign_text'] or '').strip() for r in script_rows if str(r['foreign_text'] or '').strip())
        con.execute("UPDATE videos SET script=?,production_script=?,edit_status='等待片段' WHERE id=?",(production,production,int(row['video_id'])))
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='davinci_video_state'").fetchone():
            con.execute("DELETE FROM davinci_video_state WHERE video_id=?",(int(row['video_id']),))
    return True


def rework_qc_segment_prompt(segment_id, prompt):
    sid=int(segment_id); prompt=str(prompt or '').strip()
    if not prompt: raise ValueError('提示词不能为空')
    with connect() as con:
        row=con.execute("SELECT generation_command,flow_output_path FROM flow_segments WHERE id=?",(sid,)).fetchone()
        if not row: raise ValueError('质检片段不存在')
        cmd=str(row['generation_command'] or ''); out=str(row['flow_output_path'] or '')
        if cmd: con.execute("UPDATE flow_outputs SET qc_status='旧版本失效' WHERE segment_id=? AND command_id=?",(sid,cmd))
        elif out: con.execute("UPDATE flow_outputs SET qc_status='旧版本失效' WHERE segment_id=? AND output_path=?",(sid,out))
        con.execute("""UPDATE flow_segments SET prompt=?,generation_command='',flow_status='待生成',flow_output_path='',flow_output_url='',
            flow_error='',flow_channel_key='R1',flow_retry_count=COALESCE(flow_retry_count,0)+1,flow_submitted_at='',flow_completed_at='',
            qc_status='退回',qc_note='修改Prompt',qc_reject_reason='修改Prompt',qc_decided_at=CURRENT_TIMESTAMP WHERE id=?""",(prompt,sid))
        con.execute("INSERT OR REPLACE INTO flow_redo(segment_id,created_at) VALUES(?,CURRENT_TIMESTAMP)",(sid,))
        con.execute("DELETE FROM flow_recovery WHERE segment_id=?",(sid,))
        con.execute("INSERT INTO prompt_submission_history(segment_id,prompt_snapshot) VALUES(?,?)",(sid,prompt))
    return True


_COPY_UNDO_DOWNSTREAM_TABLES = (
    "flow_dispatches",
    "flow_outputs",
    "flow_redo",
    "flow_failure_attempts",
    "flow_recovery",
    "speech_analysis",
    "local_qc_results",
    "ai_qc_results",
    "qc_decisions",
    "flow_duration_choices",
    "prompt_submission_history",
)


def snapshot_video_copy_state(video_ids) -> dict:
    """Capture a complete, lossless per-video copy & segment snapshot for Undo/Redo in Prompt Center."""
    vids = sorted({int(v) for v in (video_ids or []) if v})
    if not vids:
        return {"videos": {}}
    videos_state: dict[int, dict] = {}
    with connect() as con:
        existing_tables = {
            str(r[0])
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for vid in vids:
            vrow = con.execute(
                "SELECT id, host_id, seq, script, production_script, edit_status, special_requirements "
                "FROM videos WHERE id=?",
                (vid,),
            ).fetchone()
            if not vrow:
                continue
            segs = [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM flow_segments WHERE video_id=? ORDER BY seg_seq, id",
                    (vid,),
                ).fetchall()
            ]
            sids = [int(s["id"]) for s in segs]
            erow = con.execute(
                "SELECT value FROM app_settings WHERE key=?",
                (f"segment_eye_types:{vid}",),
            ).fetchone()
            eye_raw = str(erow[0]) if (erow is not None and erow[0] is not None) else None
            davinci_rows = None
            if "davinci_video_state" in existing_tables:
                davinci_rows = [
                    dict(r)
                    for r in con.execute(
                        "SELECT * FROM davinci_video_state WHERE video_id=?", (vid,)
                    ).fetchall()
                ]
            downstream: dict[str, list[dict]] = {}
            obsolete_rows: list[dict] = []
            if sids:
                sp = ",".join("?" for _ in sids)
                for tbl in _COPY_UNDO_DOWNSTREAM_TABLES:
                    if tbl in existing_tables:
                        downstream[tbl] = [
                            dict(r)
                            for r in con.execute(
                                f"SELECT * FROM {tbl} WHERE segment_id IN ({sp})", sids
                            ).fetchall()
                        ]
                if "flow_obsolete_segments" in existing_tables:
                    obsolete_rows = [
                        dict(r)
                        for r in con.execute(
                            f"SELECT * FROM flow_obsolete_segments WHERE segment_id IN ({sp})",
                            sids,
                        ).fetchall()
                    ]
            videos_state[vid] = {
                "video": dict(vrow),
                "segments": segs,
                "eye_types_raw": eye_raw,
                "davinci_rows": davinci_rows,
                "downstream": downstream,
                "obsolete": obsolete_rows,
            }
    return {"videos": videos_state}


def restore_video_copy_state(snapshot: dict) -> dict:
    """Atomically restore per-video copy & segment state captured by snapshot_video_copy_state."""
    raw_videos = (snapshot or {}).get("videos") or {}
    videos_map = {int(k): v for k, v in raw_videos.items() if v}
    if not videos_map:
        return {"restored_videos": 0, "segment_ids": []}

    restored_sids: list[int] = []
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        existing_tables = {
            str(r[0])
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        valid_seg_cols = [
            str(r["name"])
            for r in con.execute("PRAGMA table_info(flow_segments)").fetchall()
        ]
        table_cols_cache: dict[str, list[str]] = {}

        def _cols_for(tbl: str) -> list[str]:
            if tbl not in table_cols_cache:
                table_cols_cache[tbl] = [
                    str(r["name"])
                    for r in con.execute(f"PRAGMA table_info({tbl})").fetchall()
                ]
            return table_cols_cache[tbl]

        # Phase 1: Safety validation before mutating any row
        cur_rows_by_vid: dict[int, list] = {}
        for vid, vstate in videos_map.items():
            if not con.execute("SELECT 1 FROM videos WHERE id=?", (vid,)).fetchone():
                raise ValueError(f"目标完整视频（ID={vid}）已不存在，无法执行撤销。")
            cur_rows = con.execute(
                "SELECT id, generation_command, prompt_review_status, flow_status "
                "FROM flow_segments WHERE video_id=?",
                (vid,),
            ).fetchall()
            cur_rows_by_vid[vid] = cur_rows
            old_cmds = {
                str(s.get("generation_command") or "").strip()
                for s in (vstate.get("segments") or [])
                if str(s.get("generation_command") or "").strip()
            }
            old_submitted_sids = {
                int(s["id"])
                for s in (vstate.get("segments") or [])
                if str(s.get("prompt_review_status") or "") == "已提交"
            }
            for crow in cur_rows:
                cmd = str(crow["generation_command"] or "").strip()
                if cmd and cmd not in old_cmds:
                    raise ValueError(
                        "该视频在修改后已有片段派发至 Flow 生成队列，为保护正在执行的生成任务，无法直接撤销。"
                    )
                if (
                    str(crow["prompt_review_status"] or "") == "已提交"
                    and int(crow["id"]) not in old_submitted_sids
                ):
                    raise ValueError(
                        "该视频在修改后已新提交至 Flow 队列；如需回退文案，请先在「提交历史」中撤回排队。"
                    )

        # Phase 2: Atomic per-video restoration
        for vid, vstate in videos_map.items():
            segs = list(vstate.get("segments") or [])
            snap_sids = {int(s["id"]) for s in segs}
            cur_sids = {int(r["id"]) for r in cur_rows_by_vid.get(vid, ())}
            extra_sids = sorted(cur_sids - snap_sids)
            for esid in extra_sids:
                _cleanup_deleted_segment_downstream(con, esid)
                con.execute("DELETE FROM flow_segments WHERE id=?", (esid,))

            # Shift remaining rows to negative seg_seq so UNIQUE(video_id, seg_seq) never collides
            con.execute(
                "UPDATE flow_segments SET seg_seq = -100000 - id WHERE video_id=?",
                (vid,),
            )

            for seg in segs:
                cols = [c for c in valid_seg_cols if c in seg]
                placeholders = ",".join("?" for _ in cols)
                updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
                con.execute(
                    f"INSERT INTO flow_segments ({','.join(cols)}) VALUES ({placeholders}) "
                    f"ON CONFLICT(id) DO UPDATE SET {updates}",
                    [seg[c] for c in cols],
                )
                restored_sids.append(int(seg["id"]))

            eye_key = f"segment_eye_types:{vid}"
            eye_raw = vstate.get("eye_types_raw")
            if eye_raw is not None:
                con.execute(
                    "INSERT INTO app_settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (eye_key, eye_raw),
                )
            else:
                con.execute("DELETE FROM app_settings WHERE key=?", (eye_key,))

            vrow = vstate.get("video") or {}
            if vrow:
                con.execute(
                    "UPDATE videos SET script=?, production_script=?, edit_status=?, special_requirements=? "
                    "WHERE id=?",
                    (
                        str(vrow.get("script") or ""),
                        str(vrow.get("production_script") or ""),
                        str(vrow.get("edit_status") or "等待片段"),
                        str(vrow.get("special_requirements") or ""),
                        vid,
                    ),
                )

            if "davinci_video_state" in existing_tables and vstate.get("davinci_rows") is not None:
                con.execute("DELETE FROM davinci_video_state WHERE video_id=?", (vid,))
                dcols_all = _cols_for("davinci_video_state")
                for drow in vstate["davinci_rows"]:
                    dcols = [c for c in dcols_all if c in drow]
                    if dcols:
                        con.execute(
                            f"INSERT OR REPLACE INTO davinci_video_state ({','.join(dcols)}) "
                            f"VALUES ({','.join('?' for _ in dcols)})",
                            [drow[c] for c in dcols],
                        )

            if snap_sids:
                sids_sorted = sorted(snap_sids)
                sp = ",".join("?" for _ in sids_sorted)
                for tbl, saved_rows in (vstate.get("downstream") or {}).items():
                    if tbl not in existing_tables:
                        continue
                    con.execute(f"DELETE FROM {tbl} WHERE segment_id IN ({sp})", sids_sorted)
                    tcols_all = _cols_for(tbl)
                    for drow in saved_rows:
                        tcols = [c for c in tcols_all if c in drow]
                        if tcols:
                            con.execute(
                                f"INSERT OR REPLACE INTO {tbl} ({','.join(tcols)}) "
                                f"VALUES ({','.join('?' for _ in tcols)})",
                                [drow[c] for c in tcols],
                            )
                if "flow_obsolete_segments" in existing_tables and "obsolete" in vstate:
                    con.execute(
                        f"DELETE FROM flow_obsolete_segments WHERE segment_id IN ({sp})",
                        sids_sorted,
                    )
                    ocols_all = _cols_for("flow_obsolete_segments")
                    for orow in vstate["obsolete"]:
                        ocols = [c for c in ocols_all if c in orow]
                        if ocols:
                            con.execute(
                                f"INSERT OR IGNORE INTO flow_obsolete_segments ({','.join(ocols)}) "
                                f"VALUES ({','.join('?' for _ in ocols)})",
                                [orow[c] for c in ocols],
                            )

    _AUTO_MERGE_SIG_CACHE.clear()
    try:
        from app.services import sheet_style
        for vid in videos_map:
            sheet_style._snapshot_cache.pop(int(vid), None)
    except Exception:
        pass
    return {"restored_videos": len(videos_map), "segment_ids": restored_sids}
