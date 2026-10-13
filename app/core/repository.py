
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
            SELECT h.*, COUNT(v.id) AS actual_video_count
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
    with connect() as con:
        videos = con.execute("SELECT * FROM videos WHERE host_id=? ORDER BY seq", (host_id,)).fetchall()
        for v in videos:
            count = con.execute(
                "SELECT COUNT(*) c FROM flow_segments WHERE video_id=?", (v["id"],)
            ).fetchone()["c"]
            if count:
                continue
            source = (v["original_script"] or v["script"] or "").replace("\r\n", "\n").replace("\r", "\n")
            if not source.strip():
                continue
            from app.services.reflow_rules import prepare_configured_speech as prepare_swahili_speech
            try:
                max_chars = int(get_setting("default_wrap", "0") or 0)
            except (TypeError, ValueError):
                max_chars = 0
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
            COALESCE(fs.generation_mode,'FRAME') generation_mode, fs.ai_original_prompt, fs.segment_rule, fs.status, fs.model,
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
    with connect() as con:
        row = con.execute("""
            SELECT
                fs.id segment_id, fs.seg_seq, fs.foreign_text, fs.prompt,
                COALESCE(fs.generation_mode,'FRAME') generation_mode, fs.ai_original_prompt, fs.segment_rule, fs.status, fs.model,
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
            WHERE fs.id=?
        """, (segment_id,)).fetchone()
        from app.services.performance_types import apply_choices
        return apply_choices(con,[row])[0] if row else None

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
            COALESCE(fs.generation_mode,'FRAME') generation_mode, fs.flow_status, fs.flow_output_path, COALESCE(fs.flow_output_url,'') flow_output_url, fs.flow_error,
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
    where = ["fs.flow_status='已完成'", "TRIM(fo.output_path)<>''"]
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
    where, args = [], []
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
    grouped = {}
    for segment in segments:
        grouped.setdefault(segment['video_id'], []).append(segment)
    result = []
    for raw in rows:
        row = dict(raw)
        parts = grouped.get(row['video_id'], [])
        row['segment_count'] = len(parts)
        row['completed_segments'] = sum(p['download_valid'] for p in parts)
        row['qc_passed'] = sum(p['material_valid'] for p in parts)
        row['waiting_reasons'] = {
            '返工中': sum(not p['material_valid'] and p['qc_status']=='退回' for p in parts),
            '等待质检': sum(p['download_valid'] and not p['material_valid'] and p['qc_status']!='退回' for p in parts),
            '生成失败': sum(not p['download_valid'] and p['qc_status']!='退回' and p['flow_status']=='失败' for p in parts),
            '等待生成 / 下载': sum(not p['download_valid'] and p['qc_status']!='退回' and p['flow_status']!='失败' for p in parts),
        }
        row['materials_ready'] = row['edit_status'] not in ('待准备', '等待片段', '素材待齐', '需要画面处理', '')
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


def ensure_channel_pool(normal_count=7, include_fast=True, *, browser_b_enabled=None, browser_b_normal_count=None, browser_b_fast_enabled=None):
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
    with connect() as con:
        published=_published_generation_commands(con)
        owner_table=bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='browser_command_owners'").fetchone())
        receipt_table=bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='flow_receipts'").fetchone())
        for base in scoped_rows:
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

            if not cmd:
                # Unknown submitted/running ownership must be inspected, never regenerated.
                continue

            # Any one of these is durable evidence that this exact command may still
            # produce a paid result.  Do not automatically submit it again.
            is_published=cmd in published
            has_owner=bool(owner_table and con.execute("SELECT 1 FROM browser_command_owners WHERE command_id=? LIMIT 1",(cmd,)).fetchone())
            has_submit_dispatch=bool(con.execute("""SELECT 1 FROM flow_dispatches WHERE segment_id=? AND command_id=? AND
                (status IN ('submitted','downloading','detected') OR TRIM(COALESCE(submitted_at,''))<>'') LIMIT 1""",(sid,cmd)).fetchone())
            has_output=bool(con.execute("SELECT 1 FROM flow_outputs WHERE segment_id=? AND command_id=? LIMIT 1",(sid,cmd)).fetchone())
            # Receipts are append-only evidence from the plugin. LIKE is deliberately
            # conservative: a false positive protects work; it can never cause duplicate generation.
            has_receipt=bool(receipt_table and con.execute("SELECT 1 FROM flow_receipts WHERE payload LIKE ? AND payload LIKE ? LIMIT 1",
                (f'%{cmd}%',f'%\"segment_id\": {sid}%')).fetchone())
            protected=is_published or has_owner or has_submit_dispatch or has_output or has_receipt

            if status in ('待生成','已准备') and not protected:
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

    # Return a fresh audit after repair.  The UI uses this to prove that the selected
    # date was actually scanned instead of merely showing a timer heartbeat.
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
    allowed_segments=None
    if work_date is not None:
        with read_connection(work_date) as scoped:
            allowed_segments={int(r[0]) for r in scoped.execute("SELECT id FROM flow_segments").fetchall()}
        if not allowed_segments:
            return {'segments':[], 'channels':[]}
    with connect() as con:
        published=_published_generation_commands(con)
        owner_table=bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='browser_command_owners'").fetchone())
        rows=con.execute("""SELECT id,generation_command,flow_status,flow_channel_key,COALESCE(flow_output_path,'') flow_output_path
                              FROM flow_segments
                             WHERE flow_status IN ('待生成','已准备')
                               AND TRIM(COALESCE(generation_command,''))<>''""").fetchall()
        orphan_cmds=set()
        for row in rows:
            sid=int(row['id']); cmd=str(row['generation_command'] or '')
            if allowed_segments is not None and sid not in allowed_segments:
                continue
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
    recovered=[];released=[];commands=set()
    with connect() as con:
        published=_published_generation_commands(con)
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
        receipt_states={}; terminal_commands=set()
        for rr in con.execute("SELECT payload FROM flow_receipts"):
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
        for row in rows:
            cmd=str(row['command_id'] or ''); sid=int(row['segment_id'])
            if not cmd or cmd in published or (cmd,sid) in terminal_commands:
                continue
            last=float(row['last_update_at'] or 0)
            if last and now-last < max(3,float(grace_seconds or 0)):
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
        'fast_enabled':get_setting('flow_pool_fast_enabled','1')!='0',
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
        a={'id':'A','enabled':True,'normal_count':7,'fast_enabled':True,'profile':'Default'}; groups.append(a)
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
    where=["TRIM(fo.output_path)<>''"] if history else ["fs.flow_status='已完成'","TRIM(fo.output_path)<>''"]
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
            v.id video_id,v.seq video_seq,v.image_path,v.chinese_script,v.script full_foreign_text,fs.seg_seq,fs.foreign_text,fs.prompt,COALESCE(fs.generation_mode,'FRAME') generation_mode,fs.flow_status,fs.flow_error,
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
            v.id video_id,v.seq video_seq,v.image_path,v.chinese_script,v.script full_foreign_text,fs.seg_seq,fs.foreign_text,fs.prompt,COALESCE(fs.generation_mode,'FRAME') generation_mode,fs.flow_status,fs.flow_error,
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
    """Delete only exact recorded production files that are not referenced elsewhere."""
    protected=set()
    for value in protected_paths:
        try: protected.add(str(Path(str(value)).expanduser().resolve()))
        except Exception: protected.add(str(value))
    deleted=[]; failed=[]
    video_ext={'.mp4','.mov','.m4v','.webm','.mkv','.avi'}
    for value in dict.fromkeys(str(x or '').strip() for x in paths if str(x or '').strip()):
        try:
            path=Path(value).expanduser()
            resolved=str(path.resolve())
            if resolved in protected or path.suffix.lower() not in video_ext:
                continue
            if path.is_file():
                path.unlink(); deleted.append(str(path))
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
            row=con.execute("SELECT prompt,prompt_review_status,flow_status FROM flow_segments WHERE id=?",(sid,)).fetchone()
            if not row or not str(row['prompt'] or '').strip():
                skipped+=1; continue
            if str(row['prompt_review_status'] or '')=='已提交':
                skipped+=1; continue
            con.execute("INSERT INTO prompt_submission_history(segment_id,prompt_snapshot) VALUES(?,?)",(sid,str(row['prompt'] or '')))
            con.execute("UPDATE flow_segments SET prompt_review_status='已提交',prompt_submitted_at=CURRENT_TIMESTAMP,flow_status=CASE WHEN flow_status IN ('','失败') THEN '待生成' ELSE flow_status END WHERE id=?",(sid,))
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
            con.execute("UPDATE videos SET edit_status='等待剪辑' WHERE id=?",(video_id,))
        else:
            con.execute("UPDATE videos SET edit_status='等待片段' WHERE id=?",(video_id,))
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


def set_segment_generation_mode(segment_id, mode, *, allow_active_rework=False, force_silent=False, reason='切换生成模式'):
    """Write the single authoritative segment mode.

    Pre-execution changes only update the shared field. If the current revision has already
    entered Flow and ``allow_active_rework`` is true, supersede that revision through the
    existing redo queue so delayed old receipts remain stale by generation_command.
    """
    sid=int(segment_id); mode=normalize_generation_mode(mode)
    with connect() as con:
        row=con.execute("SELECT * FROM flow_segments WHERE id=?",(sid,)).fetchone()
        if not row: raise ValueError('任务片段不存在')
        old=normalize_generation_mode(row['generation_mode'] if 'generation_mode' in row.keys() else 'FRAME')
        if old==mode: return {'changed':False,'rework':False,'mode':mode}
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
            return {'changed':True,'rework':True,'mode':mode}
        con.execute("UPDATE flow_segments SET generation_mode=? WHERE id=?",(mode,sid))
        return {'changed':True,'rework':False,'mode':mode}


def set_generation_mode_for_segments(segment_ids, mode, force_silent=False):
    mode=normalize_generation_mode(mode); changed=blocked=0
    for sid in [int(x) for x in segment_ids]:
        try:
            result=set_segment_generation_mode(sid,mode,allow_active_rework=False,force_silent=force_silent)
            changed += 1 if result.get('changed') else 0
        except ValueError:
            blocked += 1
    return {'changed':changed,'blocked':blocked,'mode':mode}


def set_first_segment_mode_for_videos(video_ids, mode='MATERIAL', force_silent=False):
    vids=sorted({int(x) for x in video_ids}); ids=[]
    if not vids: return {'changed':0,'blocked':0,'mode':normalize_generation_mode(mode)}
    q=','.join('?' for _ in vids)
    with connect() as con:
        rows=con.execute(f"""SELECT fs.id FROM flow_segments fs
            JOIN (SELECT video_id,MIN(seg_seq) first_seq FROM flow_segments WHERE video_id IN ({q}) GROUP BY video_id) x
              ON x.video_id=fs.video_id AND x.first_seq=fs.seg_seq
            ORDER BY fs.video_id,fs.id""",vids).fetchall()
        ids=[int(r['id']) for r in rows]
    return set_generation_mode_for_segments(ids,mode,force_silent=force_silent)


def _assert_prompt_copy_editable(con, video_id):
    rows=con.execute("SELECT * FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id",(int(video_id),)).fetchall()
    for row in rows:
        active=bool(str(row['generation_command'] or '').strip()) or str(row['prompt_review_status'] or '')=='已提交' or str(row['flow_status'] or '') not in ('','待生成','失败','已准备')
        if active:
            raise ValueError('当前完整视频已有片段进入 Flow，不能再调整文案结构。')
        for table in ('flow_outputs','flow_redo','flow_recovery','flow_dispatches'):
            if con.execute(f'SELECT 1 FROM {table} WHERE segment_id=? LIMIT 1',(int(row['id']),)).fetchone():
                raise ValueError('当前完整视频已有下游记录，不能再调整文案结构。')
    return rows


def _save_manual_segment_type(con, sid, text, mode=None):
    import json
    from app.services.performance_types import choices
    from app.core import work_dates
    row=con.execute('SELECT fs.video_id,v.performance_mode FROM flow_segments fs JOIN videos v ON v.id=fs.video_id WHERE fs.id=?',(sid,)).fetchone()
    saved=choices(con,row['video_id'])
    previous=saved.get(str(sid),{})
    mode=mode or previous.get('mode') or row['performance_mode']
    if mode not in ('TALKING','PRAYING'):raise ValueError('请选择睁眼或闭眼')
    saved[str(sid)]={'text':text,'mode':mode,'source':'manual'}
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
        _reset_prompt_after_copy_change(con,int(segment_id),row['foreign_text'])
        _save_manual_segment_type(con,int(segment_id),row['foreign_text'],mode)


def _reset_prompt_after_copy_change(con, sid, text):
    from app.services.speech_preparation import timing_metadata
    meta=timing_metadata(text)
    con.execute("""UPDATE flow_segments SET foreign_text=?,prompt='',ai_original_prompt='',status='待处理',model='',
        input_tokens=0,cached_tokens=0,output_tokens=0,cost_usd=0,prompt_review_status='待检查',prompt_submitted_at='',
        estimated_speech_duration=?,flow_duration_seconds=?,timing_status=?,manual_text_lock=1 WHERE id=?""",
        (text,float(meta.get('estimated_speech_duration') or 0),int(meta.get('flow_duration_seconds') or 0),str(meta.get('timing_status') or ''),int(sid)))
    _save_manual_segment_type(con,sid,text)


def edit_prompt_segment_text(segment_id, text):
    """Edit one pre-Flow segment; blank text deletes it. Never touches video numbering."""
    sid=int(segment_id); text=' '.join(str(text or '').split())
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT id,video_id,seg_seq FROM flow_segments WHERE id=?",(sid,)).fetchone()
        if not row: raise ValueError('任务片段不存在')
        rows=_assert_prompt_copy_editable(con,int(row['video_id']))
        if not text:
            con.execute("DELETE FROM flow_duration_choices WHERE segment_id=?",(sid,))
            con.execute("DELETE FROM flow_segments WHERE id=?",(sid,))
        else:
            _reset_prompt_after_copy_change(con,sid,text)
        # Compact only segment sequence inside the same complete video. videos.seq is untouched.
        remaining=con.execute("SELECT id FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id",(int(row['video_id']),)).fetchall()
        for i,r in enumerate(remaining,1): con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?",(-i,int(r['id'])))
        for i,r in enumerate(remaining,1): con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?",(i,int(r['id'])))
        script_rows=con.execute("SELECT foreign_text FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id",(int(row['video_id']),)).fetchall()
        production=' '.join(str(r['foreign_text'] or '').strip() for r in script_rows if str(r['foreign_text'] or '').strip())
        con.execute("UPDATE videos SET script=?,production_script=? WHERE id=?",(production,production,int(row['video_id'])))
    return True


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
        _reset_prompt_after_copy_change(con,keep,merged)
        con.execute("DELETE FROM flow_duration_choices WHERE segment_id=?",(remove,))
        con.execute("DELETE FROM flow_segments WHERE id=?",(remove,))
        _save_manual_segment_type(con,keep,merged,mode)
        remaining=con.execute("SELECT id FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id",(int(row['video_id']),)).fetchall()
        for i,r in enumerate(remaining,1): con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?",(-i,int(r['id'])))
        for i,r in enumerate(remaining,1): con.execute("UPDATE flow_segments SET seg_seq=? WHERE id=?",(i,int(r['id'])))
        script_rows=con.execute("SELECT foreign_text FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id",(int(row['video_id']),)).fetchall()
        production=' '.join(str(r['foreign_text'] or '').strip() for r in script_rows if str(r['foreign_text'] or '').strip())
        con.execute("UPDATE videos SET script=?,production_script=? WHERE id=?",(production,production,int(row['video_id'])))
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
