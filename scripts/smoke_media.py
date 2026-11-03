from pathlib import Path
import sys,json,subprocess
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from PySide6.QtWidgets import QApplication
from PIL import Image
from app.services.packaging_media import find_ffmpeg
from app.services.packaging_ffmpeg import build_command,encoder_args
from app.services.packaging_media import probe_media
from app.services.packaging_watermark import prepare_knockout
app=QApplication([]);out=root/'build/media-regression';out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(root/'bundled-components/packaging/ffmpeg-libs'))
import imageio_ffmpeg
ff=imageio_ffmpeg.get_ffmpeg_exe()
version=subprocess.check_output([ff,'-version'],text=True).splitlines()[0]
assert 'version 9.' in version, version
print(version,flush=True);video=out/'source.mp4'
subprocess.run([ff,'-y','-v','error','-f','lavfi','-i','color=c=navy:s=320x180:r=25:d=2','-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],check=True)
logo=out/'logo.png';Image.new('RGBA',(40,30),(255,0,0,180)).save(logo)
Image.new('RGB',(40,30),'white').save(out/'test.jpg')
with Image.open(out/'test.jpg') as im:im.load();assert im.size==(40,30)
styles=json.loads((root/'app/services/reels/presets.json').read_text())
results=[]
for codec,ext in [('h264','mp4'),('prores','mov'),('vp9','webm')]:
 work=out/codec;work.mkdir(exist_ok=True)
 payload={'source':str(video),'ffmpeg':ff,'mainDuration':2,'totalDuration':2,'width':320,'height':180,'fps':25,'codec':codec,'captions':[{'start':0.3,'end':1.5,'text':'Security regression'}],'reelsStyle':styles['Descript 经典黄'],'watermarks':[{'path':str(logo),'enabled':True,'scale':20,'opacity':80,'position':'右上'}]}
 enc,_=encoder_args(ff,codec,False);dest=out/('verified.'+ext);cmd,duration=build_command(payload,dest,work,enc)
 cp=subprocess.run(cmd,capture_output=True,text=True,timeout=120);(work/'ffmpeg.log').write_text(cp.stdout+'\n'+cp.stderr)
 if cp.returncode:raise RuntimeError(cp.stderr[-2000:])
 meta=probe_media(dest,ff);assert meta['width']==320 and meta['height']==180 and abs(meta['duration']-2)<.15
 results.append({'codec':codec,'metadata':meta,'bytes':dest.stat().st_size});print(results[-1],flush=True)
(out/'results.json').write_text(json.dumps(results,indent=2))

# Pillow major-version regression: RGB JPEG, RGBA PNG and animated watermark.
for source in (logo,out/'test.jpg'):
    with Image.open(source) as im: im.load();assert im.width==40
gif=out/'animated.gif'
Image.new('RGB',(40,30),'white').save(gif,save_all=True,append_images=[Image.new('RGB',(40,30),'red')],duration=100,loop=0)
print('Pillow image decode passed; media outputs:',json.dumps(results))

for source in (logo,gif):
    processed=prepare_knockout(source)
    with Image.open(processed) as im: im.load();assert im.size==(40,30)
print("Pillow watermark knockout passed")
