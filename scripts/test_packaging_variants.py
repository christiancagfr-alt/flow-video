from pathlib import Path
import os,sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['FLOWSTUDIO_DATA_DIR']=str(ROOT/'build/packaging-tests')
from app.services.remotion_renderer import RemotionRenderer
from app.services.packaging_media import probe_media
from app.services import quiet_process as subprocess

folder=ROOT/'build/packaging-tests'
renderer=RemotionRenderer(str(ROOT/'build/packaging-engine'))
styles=json.loads((ROOT/'app/services/reels/presets.json').read_text(encoding='utf-8'))
payload={'source':str(folder/'source.mp4'),'mainDuration':2,'totalDuration':2,
    'width':320,'height':180,'fps':25,'ratio':'16:9','fit':'contain',
    'captions':[{'start':0,'end':2,'text':'Scrolling captions test'}],
    'reelsStyle':styles['滚动字幕 · 上浮'],
    'watermarks':[{'path':str(folder/'animated.gif'),'enabled':True,'position':'左上','mode':'小 Logo','scale':20,'opacity':80},
                  {'path':str(folder/'source.mp4'),'enabled':True,'position':'右上','mode':'小 Logo','scale':20,'opacity':70}]}
for codec,extension in [('h264','mp4'),('prores','mov'),('vp9','webm')]:
    payload['codec']=codec;output=folder/f'variant.{extension}'
    cmd,cwd=renderer.render_flowstudio_command(payload,str(output))
    with (folder/f'variant-{codec}.log').open('w',encoding='utf-8') as log:
        cp=subprocess.run(cmd,cwd=cwd,stdout=log,stderr=log,timeout=600)
    if cp.returncode:
        print((folder/f'variant-{codec}.log').read_text(encoding='utf-8')[-3000:]);raise SystemExit(1)
    meta=probe_media(output);assert meta['width']==320 and meta['height']==180 and abs(meta['duration']-2)<.15
    print(codec,meta,flush=True)
preview=folder/'still-preview.png'
cmd,cwd=renderer.render_flowstudio_command(payload,str(preview),25)
with (folder/'still.log').open('w',encoding='utf-8') as log:
    cp=subprocess.run(cmd,cwd=cwd,stdout=log,stderr=log,timeout=600)
assert cp.returncode==0 and preview.is_file()
print('Full preview passed')
