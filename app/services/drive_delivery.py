from pathlib import Path
import hashlib
import os
import re
import shutil
import uuid
from app.core import repository as repo, database

SYNCED='已交给Drive同步'

def _safe(value, fallback='未命名'):
    value=re.sub(r'[\\/:*?"<>|\x00-\x1f]+','_',str(value or '').strip()).strip(' .')
    return value or fallback

def sync_root():
    configured=str(repo.get_setting('drive_desktop_path','') or '').strip()
    if configured:
        root=Path(configured).expanduser()
        if not root.is_dir():raise ValueError('Google Drive同步目录不可用，请检查桌面版是否已登录。')
        return root
    accounts=Path.home()/'Library/CloudStorage'
    roots=[p/name for p in accounts.glob('GoogleDrive-*') for name in ('My Drive','我的云端硬盘') if (p/name).is_dir()]
    if len(roots)!=1:raise ValueError('请在系统设置选择Google Drive桌面版的同步文件夹。')
    return roots[0]

def configured():
    try:sync_root();return True,''
    except Exception as exc:return False,str(exc)

def _hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.digest()

def destination(row):
    folder=_safe(repo.get_setting('drive_desktop_folder','FlowStudio') or 'FlowStudio')
    root=sync_root()
    if not str(repo.get_setting('drive_desktop_path','') or '').strip():root=root/folder
    return root/_safe(row['work_date'])/_safe(row['recipient_name'])/_safe(row['host_name'])/_safe(Path(row['edit_output_path']).name)

def pending_rows(work_date=None, retry_failed=True, force=False):
    rows=[]
    for r in repo.list_upload_queue(work_date=work_date):
        status=str(r['upload_status'] or '')
        if str(r['edit_status'] or '') not in ('已导出','已完成'):continue
        if not force and status in ('已上传','已交付'):continue
        if not force and not retry_failed and status=='上传失败':continue
        src=Path(str(r['edit_output_path'] or ''))
        if not src.is_file():continue
        dest=destination(r)
        if not force and status==SYNCED and str(r['upload_target'] or '')==str(dest) and dest.is_file() and dest.stat().st_size==src.stat().st_size:continue
        rows.append(r)
    return rows

def self_check(work_date=None):
    root=sync_root();rows=[]
    for r in repo.list_upload_queue(work_date=work_date):
        if str(r['edit_status'] or '') not in ('已导出','已完成'):continue
        src=Path(str(r['edit_output_path'] or ''));dest=destination(r)
        if not src.is_file():status='本地成品缺失'
        elif not dest.is_file():status='当前同步目录缺失：需要重新提交'
        elif src.stat().st_size==0 or _hash(src)!=_hash(dest):status='内容不一致：请检查同名文件'
        else:status='本地与同步目录内容一致；云端状态未确认'
        rows.append({'video_id':int(r['video_id']),'source':str(src),'destination':str(dest),'status':status})
    return {'root':str(root),'rows':rows,'cloud':'云端是否上传完成需在Google Drive桌面版确认，本检查不将本地复制视为云端完成。'}

def upload_pending(progress=None, *, work_date=None, retry_failed=True, force=False):
    rows=pending_rows(work_date,retry_failed,force)
    done=0;failures=[]
    for r in rows:
        src=Path(r['edit_output_path']).expanduser()
        dest=destination(r)
        temp=None
        try:
            before=src.stat();assert before.st_size>0,'成品文件为空'
            dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():
                if not dest.is_file() or _hash(src)!=_hash(dest):raise ValueError('云端同步目录已有不同内容的同名文件，已保留，未覆盖。')
            if not dest.exists() or force:
                temp=dest.parent/('.flowstudio-'+uuid.uuid4().hex+'.part')
                shutil.copyfile(src,temp)
                after=src.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or _hash(src)!=_hash(temp):raise ValueError('复制校验未通过，源文件可能仍在变化。')
                if dest.exists():
                    if _hash(dest)!=_hash(src):raise ValueError('目标文件发生变化，未覆盖。')
                    os.replace(temp,dest)
                else:
                    with dest.open('xb') as output,temp.open('rb') as source:
                        try:
                            shutil.copyfileobj(source,output);output.flush();os.fsync(output.fileno())
                        except Exception:
                            output.close();dest.unlink(missing_ok=True);raise
                if _hash(src)!=_hash(dest):raise ValueError('最终同步目录文件校验失败')
            repo.set_video_drive_result(int(r['video_id']),'','',SYNCED)
            with database.connect() as con:con.execute('UPDATE videos SET upload_target=? WHERE id=?',(str(dest),int(r['video_id'])))
            done+=1
            if progress:progress({'type':'drive_file_uploaded','video_id':int(r['video_id']),'status':SYNCED,'done':done,'total':len(rows),'path':str(dest)})
        except Exception as exc:
            repo.set_video_upload_status([int(r['video_id'])],'上传失败')
            failures.append({'video_id':int(r['video_id']),'error':str(exc)})
        finally:
            if temp:temp.unlink(missing_ok=True)
    result={'uploaded':done,'total':len(rows),'failed':len(failures),'failures':failures}
    if progress:progress(dict(result,type='drive_finished'))
    return result
