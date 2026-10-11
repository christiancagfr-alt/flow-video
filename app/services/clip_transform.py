"""Non-destructive, output-specific Resolve inspector transforms."""
import math
from app.core.database import connect
DEFAULT={'ZoomX':1.0,'ZoomY':1.0,'Pan':0.0,'Tilt':0.0,'width':720,'height':1280}
def schema(con):
    con.execute("CREATE TABLE IF NOT EXISTS qc_clip_transforms(output_id INTEGER PRIMARY KEY,zoom REAL NOT NULL,pan REAL NOT NULL,tilt REAL NOT NULL,width INTEGER NOT NULL,height INTEGER NOT NULL)")
def validate(values):
    v={**DEFAULT,**values};z=float(v['ZoomX']);x=float(v['Pan']);y=float(v['Tilt'])
    w,h=int(v['width']),int(v['height'])
    if (w,h) not in ((720,1280),(1080,1920)):raise ValueError('请选择实际达芬奇竖屏时间线尺寸')
    if not all(math.isfinite(n) for n in (z,x,y)) or not .1<=z<=10 or abs(x)>4*w or abs(y)>4*h:raise ValueError('画面调整参数超出范围')
    return dict(ZoomX=z,ZoomY=z,Pan=x,Tilt=y,width=w,height=h)
def get(output_id):
    with connect() as con:
        schema(con);r=con.execute('SELECT * FROM qc_clip_transforms WHERE output_id=?',(output_id,)).fetchone()
    return dict(ZoomX=r['zoom'],ZoomY=r['zoom'],Pan=r['pan'],Tilt=r['tilt'],width=r['width'],height=r['height']) if r else dict(DEFAULT)
def save(output_id,values):
    v=validate(values)
    with connect() as con:
        schema(con);con.execute('BEGIN IMMEDIATE')
        r=con.execute('SELECT fs.video_id FROM flow_outputs o JOIN flow_segments fs ON fs.id=o.segment_id WHERE o.id=?',(output_id,)).fetchone()
        if not r:raise ValueError('视频版本已移除，请刷新')
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='davinci_video_state'").fetchone():
            busy=con.execute("SELECT 1 FROM davinci_video_state s JOIN davinci_batches b ON b.batch_id=s.batch_id WHERE s.video_id=? AND b.status<>'PROJECT_REBUILT'",(r[0],)).fetchone()
            if busy:raise ValueError('该视频已进入达芬奇批次，请先在剪辑中心重建对应时间线后再调整，避免参数与时间线不一致')
        con.execute('INSERT OR REPLACE INTO qc_clip_transforms VALUES(?,?,?,?,?,?)',(output_id,v['ZoomX'],v['Pan'],v['Tilt'],v['width'],v['height']))
    return v
def for_source(segment_id,path):
    with connect() as con:
        schema(con)
        r=con.execute('SELECT t.* FROM qc_clip_transforms t JOIN flow_outputs o ON o.id=t.output_id WHERE o.segment_id=? AND o.output_path=? ORDER BY o.id DESC LIMIT 1',(segment_id,str(path))).fetchone()
    if not r:return {}
    return dict(ZoomX=r['zoom'],ZoomY=r['zoom'],Pan=r['pan'],Tilt=r['tilt'],width=r['width'],height=r['height'])
def apply_resolve(clip,values,width,height):
    if not values:return
    v=validate(values)
    if (int(width),int(height))!=(v['width'],v['height']):raise RuntimeError('画面调整时间线尺寸不匹配，请核对质检设置')
    for key in ('ZoomX','ZoomY','Pan','Tilt'):
        if not clip.SetProperty(key,v[key]):raise RuntimeError('达芬奇未接受画面参数：'+key)
        actual=clip.GetProperty(key)
        if actual is None or abs(float(actual)-v[key])>.001:raise RuntimeError('达芬奇画面参数回读不一致：'+key)
