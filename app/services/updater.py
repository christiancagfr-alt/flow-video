"""Explicit update download from the project's GitHub release, verified before use."""
import hashlib, json, os, platform, re, sys, urllib.request
from pathlib import Path
from app.version import VERSION, REPOSITORY
from app.services.app_paths import data_dir
MAX_SIZE=2*1024**3

def version_tuple(value):
    if not re.fullmatch(r'v?\d+(?:\.\d+){2,3}',str(value)): raise ValueError('Invalid release version')
    result=tuple(int(x) for x in str(value).lstrip('v').split('.'))
    return result+(0,)*(4-len(result))

def asset_name(version, system=None, machine=None):
    system=system or sys.platform;machine=(machine or platform.machine()).lower()
    if system=='win32' and machine in ('amd64','x86_64'): suffix='Windows-x64-Setup.exe'
    elif system=='darwin' and machine in ('arm64','aarch64','x86_64','amd64'):
        suffix='macOS-'+('arm64' if machine in ('arm64','aarch64') else 'x86_64')+'.dmg'
    elif system.startswith('linux') and machine in ('amd64','x86_64'): suffix='Linux-amd64.deb'
    else: raise ValueError('当前平台暂未提供安装包，请查看 GitHub 发布页。')
    return 'FlowStudio-'+version.lstrip('v')+'-'+suffix

def select_release(data, system=None, machine=None):
    if data.get('draft') or data.get('prerelease'): return None
    tag=str(data.get('tag_name',''))
    if version_tuple(tag)<=version_tuple(VERSION):return None
    name=asset_name(tag,system,machine)
    asset=next((a for a in data.get('assets',[]) if a.get('name')==name and a.get('state')=='uploaded'),None)
    if not asset:raise ValueError('新版尚未提供此平台安装包，请稍后重试。')
    digest=str(asset.get('digest',''))
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',digest):raise ValueError('新版安装包缺少可靠校验值，已停止下载。')
    expected=f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
    if asset.get('browser_download_url')!=expected:raise ValueError('安装包来源不符合预期。')
    size=int(asset.get('size',0))
    if not 0<size<=MAX_SIZE:raise ValueError('安装包大小不符合预期。')
    return {'version':tag.lstrip('v'),'name':name,'url':expected,'sha256':digest[7:],'size':size}

def check():
    req=urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',headers={'Accept':'application/vnd.github+json','User-Agent':'FlowStudio/'+VERSION})
    with urllib.request.urlopen(req,timeout=25) as response:
        raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('更新信息过大')
    return select_release(json.loads(raw))

def verify(path, release):
    path=Path(path)
    if path.stat().st_size!=release['size']:raise ValueError('安装包大小校验失败，请重新下载。')
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=release['sha256']:raise ValueError('安装包校验失败，请重新下载。')

def download(release, progress=lambda value:None, cancelled=lambda:False):
    folder=data_dir()/'updates';folder.mkdir(parents=True,exist_ok=True)
    target=folder/release['name'];temporary=target.with_suffix(target.suffix+'.part')
    try:
        req=urllib.request.Request(release['url'],headers={'User-Agent':'FlowStudio/'+VERSION})
        with urllib.request.urlopen(req,timeout=30) as response,temporary.open('wb') as output:
            if not response.url.startswith('https://'):raise ValueError('拒绝不安全的下载连接')
            size=0
            while True:
                if cancelled():raise InterruptedError('下载已取消')
                block=response.read(1024*1024)
                if not block:break
                size+=len(block)
                if size>release['size']:raise ValueError('安装包超出预期大小')
                output.write(block);progress(int(size*100/release['size']))
        verify(temporary,release);temporary.replace(target)
        return target
    finally:temporary.unlink(missing_ok=True)

def launch_after_exit(path, release):
    verify(path,release)
    from app.services import quiet_process
    helper=Path(__file__).resolve().parents[2]/'scripts/install_update.py'
    quiet_process.Popen([sys.executable,str(helper),'--parent',str(os.getpid()),'--file',str(path),'--sha256',release['sha256']],start_new_session=sys.platform!='win32')
