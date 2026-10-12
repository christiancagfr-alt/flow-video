"""Isolated component checks/downloads. No credentials in command arguments."""
from pathlib import Path
import sys,os,json,shutil,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.app_paths import data_dir
from app.services import quiet_process as process
ROOT=data_dir()/'packaging'
os.environ.setdefault('HF_HOME',str(ROOT/'models'))
sys.path.insert(0,str(ROOT/'asr-libs'))
if sys.stdout:sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr:sys.stderr.reconfigure(encoding='utf-8')

def node_runtime():
    node=None if os.environ.get('FLOWSTUDIO_BUNDLE_NODE') else shutil.which('node')
    if node:return Path(node)
    candidates=list((ROOT/'node').glob('**/node.exe'))+list((ROOT/'node').glob('**/bin/node'))
    if candidates:return candidates[0]
    # Official Node distribution with published SHA-256; extract only checked paths.
    import urllib.request,hashlib,platform,zipfile,tarfile,tempfile
    system={'win32':'win','darwin':'darwin'}.get(sys.platform,'linux')
    arch='arm64' if platform.machine().lower() in ('arm64','aarch64') else 'x64'
    base='https://nodejs.org/dist/latest-v22.x/'
    with urllib.request.urlopen(base+'SHASUMS256.txt',timeout=30) as response:lines=response.read().decode().splitlines()
    suffix=f'-{system}-{arch}'+('.zip' if system=='win' else '.tar.gz')
    checksum,name=next(line.split() for line in lines if line.strip().endswith(suffix))
    folder=ROOT/'node';folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        archive=Path(temp)/name;digest=hashlib.sha256()
        with urllib.request.urlopen(base+name,timeout=60) as response,archive.open('wb') as out:
            while chunk:=response.read(1024*1024):digest.update(chunk);out.write(chunk)
        if digest.hexdigest()!=checksum:raise ValueError('Node 下载校验失败')
        if system=='win':
            from pathlib import PurePosixPath
            with zipfile.ZipFile(archive) as z:
                for member in z.infolist():
                    parts=PurePosixPath(member.filename.replace('\\','/')).parts
                    if member.is_dir():
                        if '..' in parts or any(':' in part for part in parts):raise ValueError('非法压缩包路径')
                        continue
                    if not parts or '..' in parts or any(':' in part or part.startswith('/') for part in parts):
                        raise ValueError('非法压缩包路径')
                    target=folder.joinpath(*parts).resolve()
                    if not target.is_relative_to(folder.resolve()):raise ValueError('非法压缩包路径')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as source, target.open('wb') as output:shutil.copyfileobj(source, output)
        else:
            with tarfile.open(archive) as t:t.extractall(folder,filter='data')
    return node_runtime()

def main():
    from app.services.bundled_components import restore
    restore()
    action=sys.argv[1]
    print('开始组件操作：'+action,flush=True)
    model=sys.argv[2] if len(sys.argv)>2 else 'base'
    if action=='check':
        from app.services.remotion_renderer import RemotionRenderer
        engine=RemotionRenderer(sys.argv[3] if len(sys.argv)>3 and sys.argv[3] else str(ROOT/'remotion')).check()
        print('渲染引擎：'+engine.message,flush=True)
        print('FLOW_ENGINE='+json.dumps({'ok':engine.ok,'path':engine.project_dir,'message':engine.message}),flush=True)
        from app.services.packaging_media import find_ffmpeg
        for name,fn in [('FFmpeg',find_ffmpeg),('Node',lambda:shutil.which('node') or next(iter((ROOT/'node').glob('**/node*')),None)),
                        ('字幕识别组件',lambda:__import__('faster_whisper').__version__)]:
            try:print(f'{name}：{fn() or "未安装"}',flush=True)
            except Exception:print(f'{name}：未安装或不可用',flush=True)
        try:
            from faster_whisper.utils import download_model
            path=download_model(model,local_files_only=True)
            print(f'模型 {model}：'+('已缓存' if (Path(path)/'model.bin').is_file() else '缓存不完整'))
        except Exception:print(f'模型 {model}：尚未完整下载，请点击下载 / 重试')
    elif action=='model':
        if model not in ('base','small','medium','large-v3'):raise ValueError('请选择支持的模型')
        from faster_whisper import WhisperModel
        print(f'下载并验证模型 {model}，可重试以复用缓存…',flush=True)
        from faster_whisper.utils import download_model
        try:
            cached=download_model(model,local_files_only=True)
            WhisperModel(cached,device='cpu',compute_type='int8',cpu_threads=2)
            print('完整本地模型已验证，无需下载。',flush=True)
            return
        except Exception:
            pass
        for attempt in range(3):
            try:
                from huggingface_hub import snapshot_download
                source=snapshot_download('Systran/faster-whisper-'+model,
                    allow_patterns=['config.json','preprocessor_config.json','model.bin','tokenizer.json','vocabulary.*'],max_workers=2)
                WhisperModel(source,device='cpu',compute_type='int8',cpu_threads=2)
                break
            except Exception as exc:
                message=str(exc)
                if attempt==2 or not any(token.lower() in message.lower() for token in ('10054','connect','snapshot','hub','timeout','disconnected','network')):raise
                print(f'连接中断，{3*(attempt+1)} 秒后进行第 {attempt+2}/3 次尝试；保留下载缓存。',flush=True)
                time.sleep(3*(attempt+1))
        print('模型下载完成，可开始识别。',flush=True)
    elif action=='asr':
        from scripts.install_packaging_asr import main as install
        raise SystemExit(install())
    elif action=='ffmpeg':
        from scripts.install_packaging_asr import main as install
        raise SystemExit(install(['imageio-ffmpeg==0.6.0'],ROOT/'ffmpeg-libs'))
    elif action=='remotion':
        print('准备 Node / npm…',flush=True)
        node=node_runtime();env=os.environ.copy();env['PATH']=str(node.parent)+os.pathsep+env.get('PATH','')
        choices=[node.parent/'node_modules/npm/bin/npm-cli.js',node.parent.parent/'lib/node_modules/npm/bin/npm-cli.js']
        npm=next((x for x in choices if x.is_file()),None)
        if not npm:raise ValueError('Node 已安装，但缺少 npm；请修复 Node 安装后重试。')
        folder=ROOT/'remotion';folder.mkdir(parents=True,exist_ok=True)
        manifest={'private':True,'dependencies':{'remotion':'4.0.534','@remotion/cli':'4.0.534','react':'19.2.0','react-dom':'19.2.0'}}
        (folder/'package.json').write_text(json.dumps(manifest),encoding='utf-8')
        process.run([str(node),str(npm),'install','--registry=https://registry.npmjs.org','--cache',str(ROOT/'npm-cache')],cwd=folder,env=env,check=True,stdout=sys.stdout,stderr=sys.stderr)
        for attempt in range(3):
            try:
                process.run([str(node),str(folder/'node_modules/@remotion/cli/remotion-cli.js'),'browser','ensure'],cwd=folder,env=env,check=True,stdout=sys.stdout,stderr=sys.stderr,timeout=300)
                break
            except (process.CalledProcessError,process.TimeoutExpired):
                if attempt==2:raise
                print('渲染浏览器下载未完成，保留缓存后重试…',flush=True)
                time.sleep(5*(attempt+1))
        print('渲染引擎和浏览器安装完成。',flush=True)
    else:raise ValueError('未知组件操作')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        text=str(exc)
        if any(x in text for x in ('10054','ConnectError','snapshot','Hub')):
            text='模型服务器连接中断或模型缓存不完整。请检查网络 / 代理，在组件管理中点击下载 / 重试；完整缓存下载成功后可离线使用。'
        print('未完成：'+text,flush=True);sys.exit(1)

