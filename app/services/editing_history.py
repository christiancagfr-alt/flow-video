"""One persistent row per editing attempt. Legacy completed videos are visible too."""
import json
from app.core.database import connect


def record_submission(video_id,path,segs):
    with connect() as con:
        old=con.execute('SELECT edit_status,edit_output_path FROM videos WHERE id=?',(video_id,)).fetchone()
        if not old:raise ValueError('视频任务已被清空')
        if not con.execute('SELECT 1 FROM editing_history WHERE video_id=?',(video_id,)).fetchone() and old['edit_status'] not in ('等待片段','素材待齐','待剪辑','等待剪辑','待导入DaVinci',''):
            con.execute('INSERT INTO editing_history(video_id,status,output_path) VALUES(?,?,?)',(video_id,old['edit_status'],old['edit_output_path']))
        return con.execute('INSERT INTO editing_history(video_id,job_path,status,source_json) VALUES(?,?,?,?)',
            (video_id,str(path),'已提交',json.dumps([dict(s) for s in segs],ensure_ascii=False))).lastrowid


def mark_failed(hid,message):
    with connect() as con:con.execute('UPDATE editing_history SET status=? WHERE id=?',(message,hid))


def rows():
    with connect() as con:
        history=[dict(r) for r in con.execute("""SELECT e.*,r.work_date,r.name recipient_name,h.name host_name,v.seq video_seq
            FROM editing_history e JOIN videos v ON v.id=e.video_id JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id ORDER BY e.id DESC""")]
        history += [dict(r) for r in con.execute("""SELECT 0 id,v.id video_id,'' job_path,v.edit_status status,v.edit_output_path output_path,'' source_json,
            '旧版记录' created_at,r.work_date,r.name recipient_name,h.name host_name,v.seq video_seq
            FROM videos v JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            WHERE (v.edit_status IN ('剪辑中','已剪辑','待人工检查','待导出','导出中','已导出','已完成') OR v.edit_output_path<>'')
            AND NOT EXISTS(SELECT 1 FROM editing_history e WHERE e.video_id=v.id)""")]
    return history
