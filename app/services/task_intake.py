from __future__ import annotations

import csv
import io
import json
import re
import shutil
import time
import datetime as _dt
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from app.core import repository as repo
from app.services.text_processing import smart_segment, strip_decorative_symbols
from app.services import runtime_log


def sheet_export_url(url: str) -> str:
    raw=(url or "").strip()
    if not raw:
        raise ValueError("未设置 Google 表格链接")
    m=re.search(r"/spreadsheets/d/([\w-]+)",raw)
    if not m:
        return raw
    sid=m.group(1)
    gid=(urllib.parse.parse_qs(urllib.parse.urlparse(raw).query).get("gid") or [""])[0]
    if not gid:
        mg=re.search(r"[#&]gid=(\d+)",raw); gid=mg.group(1) if mg else "0"
    return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"


def fetch_csv_public(url: str, timeout: int=25) -> str:
    req=urllib.request.Request(sheet_export_url(url),headers={"User-Agent":"FlowStudio/0.13.3"})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        data=resp.read(30*1024*1024+1)
        if len(data)>30*1024*1024:raise ValueError("表格下载超过 30 MB")
    return data.decode("utf-8-sig",errors="replace")


def parse_rows(csv_text: str) -> list[dict[str,str]]:
    reader=csv.DictReader(io.StringIO(csv_text))
    out=[]
    for idx,row in enumerate(reader,2):
        norm={str(k or "").strip():str(v or "").strip() for k,v in row.items()}
        if any(norm.values()):
            norm["__row__"]=str(idx); out.append(norm)
    return out


def _pick(row:dict,*names:str)->str:
    lowered={k.lower():v for k,v in row.items()}
    for name in names:
        if name in row and row[name].strip(): return row[name].strip()
        if name.lower() in lowered and lowered[name.lower()].strip(): return lowered[name.lower()].strip()
    return ""


def _brief_value(brief: str, *labels: str) -> str:
    if not brief:
        return ""
    for label in labels:
        m=re.search(rf"(?:^|[\n\r;；])\s*{re.escape(label)}\s*[：:]\s*([^\n\r;；]+)",brief,re.I)
        if m: return m.group(1).strip()
    return ""


def normalize_task_row(row:dict)->dict:
    # Flexible aliases plus a generic “任务简介” fallback, so the user's existing Sheet does not
    # need to be redesigned just for Studio. Structured columns always win when both are present.
    brief=_pick(row,"任务简介","任务说明","简介","brief","task brief")
    recipient=_pick(row,"接收人","接受人","recipient","客户") or _brief_value(brief,"接收人","接受人","客户")
    host=_pick(row,"AI主播","主播","人物","制作名","host") or _brief_value(brief,"AI主播","主播","人物","制作名")
    foreign=_pick(row,"外语文案","外文","外语","foreign","文案") or _brief_value(brief,"外语文案","外文","外语","文案")
    chinese=_pick(row,"中文对照","中文","Chinese","中文文案") or _brief_value(brief,"中文对照","中文文案","中文")
    drive=_pick(row,"网盘链接","图片链接","Drive链接","素材链接","google drive") or _brief_value(brief,"网盘链接","图片链接","Drive链接","素材链接")
    count=_pick(row,"完整视频数量","视频数量","数量","count") or _brief_value(brief,"完整视频数量","视频数量","数量")
    date=_pick(row,"日期","制作日期","date") or _brief_value(brief,"日期","制作日期")
    task_id=_pick(row,"任务ID","task id","id") or f"row-{row.get('__row__','0')}"
    return {"source_task_id":task_id,"recipient":recipient,"host":host,"foreign":foreign,"chinese":chinese,"drive_url":drive,"count":count,"date":date,"source_row":row.get("__row__","")}


def normalize_date_yyyymmdd(value: str) -> str:
    raw=str(value or '').strip()
    if not raw: return ''
    digits=re.sub(r'\D','',raw)
    if len(digits)==8:
        # yyyyMMdd, ddMMyyyy, MMddyyyy (prefer European ddMMyyyy when year is last).
        if digits[:4].isdigit() and 2000 <= int(digits[:4]) <= 2100: return digits
        if 2000 <= int(digits[4:]) <= 2100:
            d,m,y=digits[:2],digits[2:4],digits[4:]
            try: _dt.date(int(y),int(m),int(d)); return y+m+d
            except Exception: pass
    # Flexible separators / one-digit month or day / Chinese date markers.
    m=re.match(r'^\s*(20\d{2})\D+(\d{1,2})\D+(\d{1,2})\D*$',raw)
    if m:
        try:return _dt.date(int(m.group(1)),int(m.group(2)),int(m.group(3))).strftime('%Y%m%d')
        except Exception:pass
    m=re.match(r'^\s*(\d{1,2})\D+(\d{1,2})\D+(20\d{2})\D*$',raw)
    if m:
        try:return _dt.date(int(m.group(3)),int(m.group(2)),int(m.group(1))).strftime('%Y%m%d')
        except Exception:pass
    for fmt in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%m/%d/%Y'):
        try:return _dt.datetime.strptime(raw,fmt).strftime('%Y%m%d')
        except Exception:pass
    return digits[:8]


def _safe(value:str)->str:
    value=re.sub(r'[\\/:*?"<>|\x00-\x1f]+','_',str(value or '').strip())
    return re.sub(r'\s+',' ',value).strip(' .') or '未命名'


def standard_image_name(recipient:str,host:str,index:int,suffix:str='.jpg')->str:
    return f"{_safe(recipient)}-{_safe(host)}-{int(index):02d}{suffix.lower()}"


def extract_drive_file_id(url:str)->str:
    for pat in [r"/file/d/([\w-]+)",r"[?&]id=([\w-]+)"]:
        m=re.search(pat,url or "")
        if m:return m.group(1)
    return ""


def direct_drive_download_url(url:str)->str:
    fid=extract_drive_file_id(url)
    return f"https://drive.google.com/uc?export=download&id={fid}" if fid else url


def import_rows(rows:list[dict], *, creator:str, fixed_code:str="ZB", today_only:bool=True) -> dict:
    created=0; skipped=0; warnings=[]
    for raw in rows:
        t=normalize_task_row(raw)
        if not t["recipient"] or not t["host"] or not t["foreign"]:
            warnings.append(f"第 {t['source_row']} 行缺少接收人/主播/外语文案")
            continue
        if repo.source_task_exists(t["source_task_id"],t["source_row"]):
            skipped+=1; continue
        source_date=normalize_date_yyyymmdd(t["date"])
        today=time.strftime("%Y%m%d")
        if today_only and source_date and source_date != today:
            skipped+=1; continue
        date=source_date or today
        # Current task source convention: one row = one complete video. Consecutive rows with same
        # recipient+host reuse the same host and next video sequence.
        rid=repo.find_or_create_recipient(t["recipient"],fixed_code,creator,date)
        hid=repo.find_or_create_host(rid,t["host"])
        vid=repo.add_video_to_host(hid, original_script=t["foreign"], chinese=t["chinese"], source_task_id=t["source_task_id"], source_row=t["source_row"], drive_url=t["drive_url"])
        clean=strip_decorative_symbols(t["foreign"])
        segments=smart_segment(clean)
        repo.update_video_source_text(vid,t["foreign"],clean)
        repo.sync_flow_segments(vid,segments)
        repo.mark_source_task(t["source_task_id"],t["source_row"],vid,"已导入")
        if t["drive_url"]:
            seq=repo.video_seq(vid)
            repo.create_asset_job(vid,t["drive_url"],seq,standard_image_name(t["recipient"],t["host"],seq))
        created+=1
    return {"created":created,"skipped":skipped,"warnings":warnings}


def queue_sheet_sync(sheet_url:str)->str:
    job_id="sheet-"+uuid.uuid4().hex
    repo.create_web_fetch_job(job_id,"sheet_csv",sheet_export_url(sheet_url),{"source_url":sheet_url})
    return job_id


def consume_sheet_fetch(job_id:str, creator:str, fixed_code:str="ZB") -> dict:
    row=repo.get_web_fetch_job(job_id)
    if not row or row["status"]!="done":
        raise RuntimeError("Google表格尚未获取完成")
    data=json.loads(row["result_json"] or "{}")
    text=data.get("text","")
    return import_rows(parse_rows(text),creator=creator,fixed_code=fixed_code)


def queue_pending_assets(limit:int=50)->int:
    """Queue direct Google Drive/file URLs for authenticated browser-side fetch.

    Folder links are not guessed into files; those remain visible as manual exceptions unless the
    source sheet provides direct file links. This prevents downloading the wrong reference image.
    """
    count=0
    for row in repo.list_asset_jobs('queued')[:max(1,int(limit))]:
        url=str(row['source_url'] or '').strip()
        fid=extract_drive_file_id(url)
        job_id=f"asset-{int(row['id'])}-{uuid.uuid4().hex[:10]}"
        meta={'asset_job_id':int(row['id']),'expected_name':str(row['expected_name'] or ''),'video_id':int(row['video_id']),
              'asset_index':int(row['asset_index'] or 1),'source_url':url}
        if 'drive.google.com/drive/folders/' in url and not fid:
            # Browser-authenticated folder page fetch. The result is parsed locally, then the
            # selected image is fetched as a direct file. This keeps source names irrelevant.
            repo.create_web_fetch_job(job_id,'asset_folder',url,meta)
        else:
            repo.create_web_fetch_job(job_id,'asset_file',direct_drive_download_url(url),meta)
        from app.core.database import connect as _connect
        with _connect() as con:
            con.execute("UPDATE asset_jobs SET status='fetching' WHERE id=?",(int(row['id']),))
        count+=1
    return count


def _natural_key(name:str):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)',name or '')]


def _drive_folder_files(html:str)->list[dict]:
    """Best-effort extraction from authenticated Drive folder HTML/bootstrap payload.

    Drive changes its UI often, so failure is surfaced as an asset exception rather than guessing
    the wrong image. Direct file links remain the most reliable path.
    """
    found={}
    # Visible/file links (when Drive renders anchors server-side).
    for m in re.finditer(r'https://drive\.google\.com/(?:file/d/|open\?id=)([A-Za-z0-9_-]{15,})[^"\'<>]*',html or ''):
        found.setdefault(m.group(1),{'id':m.group(1),'name':''})
    # Bootstrap tuples frequently keep file id close to an image filename.
    for m in re.finditer(r'["\']([A-Za-z0-9_-]{20,})["\'][\s\S]{0,320}?["\']([^"\']+\.(?:jpe?g|png|webp|heic|avif))["\']',html or '',re.I):
        fid,name=m.group(1),m.group(2)
        if 'drive.google.com' not in name: found[fid]={'id':fid,'name':name}
    files=list(found.values())
    files=[x for x in files if x.get('id')]
    # Preserve the folder payload/UI order. Original filenames are deliberately *not* used as
    # production sequence; Studio renames the downloaded images by task/video sequence.
    return files


def _consume_folder_fetch_results()->dict:
    from app.core.database import connect as _connect
    queued=failed=0
    with _connect() as con:
        rows=con.execute("SELECT * FROM web_fetch_jobs WHERE kind='asset_folder' AND status IN ('done','failed') ORDER BY updated_at").fetchall()
    for row in rows:
        try: meta=json.loads(row['meta_json'] or '{}')
        except Exception: meta={}
        aid=int(meta.get('asset_job_id') or 0)
        if not aid: continue
        asset=next((x for x in repo.list_asset_jobs() if int(x['id'])==aid),None)
        if not asset or str(asset['status']) in ('done','failed'): continue
        if row['status']=='failed':
            repo.complete_asset_job(aid,'',str(row['error'] or 'Drive文件夹读取失败'));failed+=1;continue
        try:data=json.loads(row['result_json'] or '{}')
        except Exception:data={}
        files=_drive_folder_files(str(data.get('text') or ''))
        idx=max(1,int(meta.get('asset_index') or 1))-1
        if idx>=len(files):
            repo.complete_asset_job(aid,'',f'Drive文件夹只识别到 {len(files)} 张图片，无法取得第 {idx+1} 张');failed+=1;continue
        f=files[idx]
        job_id=f"assetfile-{aid}-{uuid.uuid4().hex[:10]}"
        meta2={**meta,'drive_file_id':f['id'],'drive_source_name':f.get('name','')}
        repo.create_web_fetch_job(job_id,'asset_file',f"https://drive.google.com/uc?export=download&id={f['id']}",meta2)
        # Prevent this completed folder listing from being consumed again.
        with _connect() as con: con.execute("UPDATE web_fetch_jobs SET kind='asset_folder_consumed' WHERE job_id=?",(row['job_id'],))
        queued+=1
    return {'queued':queued,'failed':failed}


def consume_asset_fetch_results(inbox_root:str|Path|None=None)->dict:
    import base64
    folder_result=_consume_folder_fetch_results()
    root=Path(inbox_root or repo.get_setting('task_asset_root','') or (Path.home()/'Documents'/'FlowStudio'/'TaskAssets')).expanduser()
    root.mkdir(parents=True,exist_ok=True)
    done=failed=0
    from app.core.database import connect as _connect
    with _connect() as con:
        rows=con.execute("SELECT * FROM web_fetch_jobs WHERE kind='asset_file' AND status IN ('done','failed') ORDER BY updated_at").fetchall()
    for row in rows:
        try: meta=json.loads(row['meta_json'] or '{}')
        except Exception: meta={}
        aid=int(meta.get('asset_job_id') or 0)
        if not aid: continue
        asset=next((x for x in repo.list_asset_jobs() if int(x['id'])==aid),None)
        if not asset or str(asset['status']) in ('done','failed'): continue
        if row['status']=='failed':
            repo.complete_asset_job(aid,'',str(row['error'] or '网页端下载失败'));failed+=1;continue
        try: result=json.loads(row['result_json'] or '{}')
        except Exception: result={}
        b64=result.get('base64') or ''
        if not b64:
            repo.complete_asset_job(aid,'','网页端没有返回图片内容');failed+=1;continue
        expected=str(meta.get('expected_name') or asset['expected_name'] or f'asset-{aid}')
        mime=str(result.get('content_type') or '').split(';',1)[0].strip().lower()
        mime_suffix={"image/png":".png","image/webp":".webp","image/jpeg":".jpg","image/jpg":".jpg","image/heic":".heic","image/avif":".avif"}.get(mime,'')
        current_suffix=Path(expected).suffix.lower()
        # The standardized *stem* is authoritative; use the real downloaded image type for suffix.
        if mime_suffix:
            expected=str(Path(expected).with_suffix(mime_suffix))
        elif not current_suffix:
            expected += '.jpg'
        folder=root/_safe(str(asset['recipient_name']))/_safe(str(asset['host_name']))
        folder.mkdir(parents=True,exist_ok=True)
        if Path(expected).name!=expected or any(c in expected for c in ('/', '\\', ':')) or expected in ('.','..'):
            repo.complete_asset_job(aid,'','素材文件名无效，拒绝写入目录之外');failed+=1;continue
        path=folder/expected
        if len(b64)>40*1024*1024:
            repo.complete_asset_job(aid,'','素材超过 30 MB');failed+=1;continue
        path.write_bytes(base64.b64decode(b64,validate=True))
        repo.complete_asset_job(aid,str(path));done+=1
    return {'done':done,'failed':failed+int(folder_result.get('failed',0)),'folder_queued':int(folder_result.get('queued',0)),'root':str(root)}
