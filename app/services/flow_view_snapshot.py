"""Read-only display snapshots. No QWidget is read or written here."""
import time
from functools import lru_cache
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader
from app.services.image_assets import image_cache_key, MAX_BYTES, _macos_sips_decode
from pathlib import Path
from app.core import repository as repo
from app.services import host_priority, chrome_profiles
from app.services.perf_diagnostics import measured

@lru_cache(maxsize=128)
def thumbnail(key):
    # QImage is safe in a worker; QPixmap is created only on the GUI thread.
    if key[1] is None or key[2] > MAX_BYTES:return None
    reader=QImageReader(key[0]);reader.setAutoTransform(True);reader.setDecideFormatFromContent(True)
    size=reader.size()
    if size.isValid():reader.setScaledSize(size.scaled(QSize(48,48),Qt.KeepAspectRatio))
    image=reader.read()
    if image.isNull():
        try:image=_macos_sips_decode(*key)
        except Exception:return None
        if image is None:return None
    return image.scaled(QSize(48,48),Qt.KeepAspectRatio,Qt.SmoothTransformation)

@measured('flow_ui_refresh')
def read_snapshot(key):
    day, rid, hid, scope, query, page = key
    all_tasks = [dict(t) for t in repo.list_flow_tasks(work_date=day)]
    scoped = [t for t in all_tasks if (not rid or t['recipient_id']==rid) and (not hid or t['host_id']==hid)]
    tree={}
    for task in scoped:
        parent=None
        for field,title in (('recipient_id',task['recipient_name']),('host_id',task['host_name']),('video_id',f"视频 {task['video_seq']:02d}")):
            node=(field,task[field]);info=tree.setdefault(node,[parent,str(title),0,0])
            info[2]+=int(task['flow_status']=='已完成');info[3]+=1;parent=node
    images={}
    for task in all_tasks:
        task['_output_exists']=bool(task['flow_output_path']) and Path(str(task['flow_output_path'])).is_file()
        hid_key=task['host_id']
        if hid_key not in images:
            revision=image_cache_key(task['image_path'])
            images[hid_key]=(revision,thumbnail(revision))
    rows = scoped
    if scope:
        field, value = scope
        rows = [t for t in rows if t[field]==value]
    if query:
        rows = [t for t in rows if query in (f"{t['recipient_name']} {t['host_name']} {t['video_seq']:02d}-{t['seg_seq']:02d} {t['foreign_text']}").lower()]
    pages = max(1,(len(rows)+99)//100)
    page = max(0,min(page,pages-1))
    channels = [dict(c) for c in repo.list_channel_pool(enabled_only=True)]
    summaries = {str(c['channel_key']):dict(repo.channel_dispatch_summary(c['channel_key'])) for c in channels}
    groups = [dict(g) for g in repo.list_browser_groups(True)]
    links = [dict(r) for r in repo.list_flow_host_links(rid,work_date=day)]
    by_host = {}
    for task in all_tasks: by_host.setdefault(task['host_id'],[]).append(task)
    link_values=[]
    for row in links:
        tasks=by_host.get(row['host_id'],[])
        pending=sum((t['flow_status'] or '待生成') in ('待生成','失败','已准备') for t in tasks)
        active=sum((t['flow_status'] or '') in ('已提交','生成中','下载中') for t in tasks)
        done=sum((t['flow_status'] or '')=='已完成' for t in tasks)
        failed=sum((t['flow_status'] or '') in ('失败','下载失败') for t in tasks)
        keys=list(dict.fromkeys(str(t['flow_channel_key']) for t in tasks if t['flow_channel_key']))
        status='🟢 完成' if tasks and done==len(tasks) else ('🟠 进行中' if active else ('🔴 有失败' if failed else '⚪ 待调度'))
        link_values.append([row['recipient_name'],row['host_name'],pending,active,done,failed,'、'.join(keys) or '—',status])
    profile=repo.get_setting('chrome_profile_directory','Default') or 'Default'
    return dict(key=key,all_tasks=all_tasks,tree_rows=scoped,tree=tree,images=images,rows=rows[page*100:(page+1)*100],
        total=len(rows),pages=pages,page=page,stats=repo.count_flow_task_status(rid,hid,work_date=day),
        channels=channels,summaries=summaries,groups=groups,b_enabled=repo.browser_b_enabled(),
        root=repo.get_setting('flow_channel_download_root',str(Path.home()/'Downloads'/'FlowStudio_Channels')),
        live=[dict(d) for d in repo.list_live_flow_dispatches(work_date=day,max_age_minutes=30)],
        priorities=host_priority.load(day),links=links,link_values=link_values,
        profile=profile,profiles=chrome_profiles.list_chrome_profiles())
