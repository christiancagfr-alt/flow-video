"""Manual integration check: generated fixtures only, no user media or paid API calls."""
from pathlib import Path
import os,sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['FLOWSTUDIO_DATA_DIR']=str(ROOT/'build/packaging-tests')
from app.services import quiet_process as subprocess
from app.services.packaging_media import find_ffmpeg,probe_media
from app.services.remotion_renderer import RemotionRenderer
from PIL import Image

def main():
    folder=ROOT/'build/packaging-tests';folder.mkdir(exist_ok=True)
    video=folder/'source.mp4';ffmpeg=find_ffmpeg()
    subprocess.run([ffmpeg,'-y','-v','error','-f','lavfi','-i','color=c=navy:s=360x640:r=24:d=3',
        '-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],check=True)
    logo=folder/'logo.png';Image.new('RGBA',(120,60),(255,40,40,190)).save(logo)
    intro=folder/'intro.png';Image.new('RGB',(360,640),'green').save(intro)
    broll=folder/'broll.png';Image.new('RGB',(360,640),'purple').save(broll)
    presets=json.loads((ROOT/'app/services/reels/presets.json').read_text(encoding='utf-8'))
    payload={'source':str(video),'mainDuration':3,'totalDuration':4,'ratio':'9:16','width':360,'height':640,'fps':24,'codec':'h264',
        'captions':[{'start':.3,'end':2.5,'text':'Hello beautiful world','words':[{'text':'Hello','start':.3,'end':.8},{'text':'beautiful','start':.9,'end':1.5},{'text':'world','start':1.8,'end':2.5}]}],
        'reelsStyle':presets['Descript 经典黄'],'watermarks':[{'enabled':True,'path':str(logo),'mode':'小 Logo','position':'右上','opacity':75,'scale':25}],
        'title':{'enabled':True,'text':'TITLE RETAINED','size':24,'position':'顶部居中'},
        'broll':[{'path':str(broll),'start':1,'end':1.5}],
        'intro':{'enabled':True,'path':str(intro),'duration':.5},'outro':{'enabled':True,'path':str(intro),'duration':.5}}
    renderer=RemotionRenderer(str(ROOT/'build/packaging-engine'))
    out=folder/'reels-render.mp4'
    cmd,cwd=renderer.render_flowstudio_command(payload,str(out))
    with (folder/'render.log').open('w',encoding='utf-8') as log:
        cp=subprocess.run(cmd,cwd=cwd,stdout=log,stderr=log,timeout=600)
    print('Render exit:',cp.returncode)
    if cp.returncode:print((folder/'render.log').read_text(encoding='utf-8')[-4000:]);return 1
    meta=probe_media(out,ffmpeg);print(meta)
    assert meta['width']==360 and meta['height']==640 and abs(meta['duration']-4)<.15
    subprocess.run([ffmpeg,'-y','-v','error','-ss','1.2','-i',str(out),'-frames:v','1',str(folder/'render-frame.png')],check=True)
    return 0
if __name__=='__main__':sys.exit(main())
