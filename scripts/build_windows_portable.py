"""Reproducible Windows x64 source + embedded Python distribution. No user data."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from packaging.tags import cpython_tags, compatible_tags
from packaging.utils import parse_wheel_filename
from bundle_web_plugin import iter_plugin_files

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build'
OUT=BUILD/'FlowStudio-Windows'
PYTHON_VERSION='3.13.16'
PYTHON_SHA256='97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297'

def download(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url,timeout=90) as response:return response.read()
        except OSError:
            if attempt==2:raise
            time.sleep(1+attempt)

def wheel_record(line):
    name,version=line.split('==')
    metadata=json.loads(download(f'https://pypi.org/pypi/{name}/{version}/json'))
    tags=set(cpython_tags((3,13),abis=['cp313'],platforms=['win_amd64']))|set(compatible_tags((3,13),interpreter='cp313',platforms=['win_amd64']))
    wheels=[x for x in metadata['urls'] if x['filename'].endswith('.whl') and parse_wheel_filename(x['filename'])[3]&tags]
    if not wheels:raise RuntimeError('No compatible wheel: '+line)
    item=wheels[0];path=BUILD/'wheels'/item['filename'];path.parent.mkdir(parents=True,exist_ok=True)
    expected=item['digests']['sha256']
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        data=download(item['url'])
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Checksum mismatch: '+line)
        path.write_bytes(data)
    return {'package':name,'version':version,'filename':path.name,'sha256':expected,'url':item['url']}

def source_files():
    files=[]
    for folder,suffixes in [('app',{'.py'}),('scripts',{'.py','.ps1','.iss'}),('assets',{'.svg','.png','.ico','.icns'}),('davinci_autoedit_v0_5_0',{'.lua'}),('tests',{'.py','.js'})]:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts and not any(x.startswith('TEST_RESULTS') for x in p.parts):files.append(p)
    files.extend((ROOT/'app/data/caption_presets/builtin').glob('*.json'))
    files.extend((ROOT/'app/services/reels').glob('*.json'))
    files.extend(iter_plugin_files(ROOT))
    files.extend(ROOT.glob('requirements-asr.txt'))
    files.extend(ROOT.glob('THIRD_PARTY_NOTICES.md'))
    for name in ['main.py','Flow Studio.vbs','监控达芬奇唤醒.bat','requirements-release.lock','requirements-windows.txt','requirements-macos.lock','requirements-linux.lock','README.md','RELEASE_NOTES.md','.env.example','.gitignore']:
        p=ROOT/name
        if p.exists():files.append(p)
    return sorted(set(files))

def extract_checked(archive,dest,wheel=False):
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            parts=PurePosixPath(item.filename).parts
            if not parts or '..' in parts or PurePosixPath(item.filename).is_absolute() or any(':' in x or '\\' in x for x in parts):raise ValueError('Unsafe archive path')
            if item.is_dir():continue
            if wheel and parts[0].endswith('.data'):
                if len(parts)<3 or parts[1] not in ('purelib','platlib'):continue
                parts=parts[2:]
            target=dest.joinpath(*parts)
            if not target.resolve().is_relative_to(dest.resolve()):raise ValueError('Archive escapes destination')
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(item) as source,target.open('wb') as output:shutil.copyfileobj(source,output)

def main():
    BUILD.mkdir(exist_ok=True)
    archive=BUILD/'downloads'/f'python-{PYTHON_VERSION}-embed-amd64.zip';archive.parent.mkdir(exist_ok=True)
    if not archive.exists():archive.write_bytes(download(f'https://www.python.org/ftp/python/{PYTHON_VERSION}/{archive.name}'))
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=PYTHON_SHA256:raise ValueError('Python checksum mismatch')
    lines=[x.strip() for x in (ROOT/'requirements-release.lock').read_text().splitlines() if '==' in x]
    with ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(wheel_record,lines))
    manifest=ROOT/'audit/wheel-manifest.json';manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps(records,indent=2),encoding='utf-8')
    resolved_build=BUILD.resolve();resolved_out=OUT.resolve()
    if resolved_out==resolved_build or not resolved_out.is_relative_to(resolved_build):
        raise ValueError(f'Unsafe Windows build output path: {resolved_out}')
    if OUT.exists():shutil.rmtree(OUT)
    OUT.mkdir(parents=True,exist_ok=True)
    for p in source_files():
        target=OUT/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
    runtime=OUT/'runtime';runtime.mkdir(exist_ok=True)
    extract_checked(archive,runtime)
    for row in records:extract_checked(BUILD/'wheels'/row['filename'],runtime/'Lib/site-packages',wheel=True)
    (runtime/'python313._pth').write_text('python313.zip\n.\nLib/site-packages\n..\nimport site\n',encoding='utf-8')
    # Embed mode otherwise does not process pywin32.pth on some Python builds.
    (runtime/'sitecustomize.py').write_text("import os,sys\nfrom pathlib import Path\np=Path(__file__).parent/'Lib/site-packages'\nfor name in ('win32','win32/lib','Pythonwin'):sys.path.append(str(p/name))\n_dll=os.add_dll_directory(str(p/'pywin32_system32'))\n",encoding='utf-8')
    (OUT/'RUNTIME_MANIFEST.json').write_text(json.dumps({'python':PYTHON_VERSION,'python_sha256':PYTHON_SHA256,'wheels':records},indent=2),encoding='utf-8')
    from bundle_packaging_components import bundle
    bundle(OUT,runtime/'python.exe')
    print('Portable tree prepared:',OUT,flush=True)

if __name__=='__main__':main()
