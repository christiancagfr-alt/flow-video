"""Install optional local ASR into app data, never modify the app's base runtime."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib,json,tempfile
from urllib.request import urlopen
from urllib.parse import urlsplit
from app.services.app_paths import data_dir
from app.services import quiet_process as subprocess

def main(packages=None, destination=None):
    target=destination or data_dir()/'packaging/asr-libs';target.mkdir(parents=True,exist_ok=True)
    with urlopen('https://pypi.org/pypi/pip/json',timeout=30) as response:
        meta=json.load(response)
    wheel=next(x for x in meta['urls'] if x['filename'].endswith('py3-none-any.whl'))
    url=wheel['url']
    if urlsplit(url).scheme!='https' or urlsplit(url).hostname!='files.pythonhosted.org':
        raise ValueError('组件下载地址校验失败')
    with tempfile.TemporaryDirectory(prefix='flowstudio-pip-') as folder:
        archive=Path(folder)/wheel['filename']
        with urlopen(url,timeout=60) as response:data=response.read(20*1024*1024)
        if hashlib.sha256(data).hexdigest()!=wheel['digests']['sha256']:raise ValueError('组件文件校验失败')
        archive.write_bytes(data)
        code='import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("pip",run_name="__main__")'
        command=[sys.executable,'-X','utf8','-c',code,str(archive),'install','--target',str(target),'--upgrade',
            '--cache-dir',str(target.parent/'pip-cache'),'--timeout','30','--retries','2',
            '--only-binary=:all:','--index-url','https://pypi.org/simple','--disable-pip-version-check',
            ] + (packages or ['-r',str(Path(__file__).resolve().parents[1]/'requirements-asr.txt')])
        return subprocess.run(command,stdout=sys.stdout,stderr=sys.stderr).returncode

if __name__=='__main__':
    if sys.stdout:sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr:sys.stderr.reconfigure(encoding='utf-8')
    try:sys.exit(main())
    except Exception as exc:print('组件安装失败：'+str(exc));sys.exit(1)
