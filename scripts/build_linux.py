"""Self-contained Python/Qt desktop package for Debian/Ubuntu amd64."""
import hashlib,json,os,platform,shutil,subprocess,sys,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.version import VERSION
SHA='24801ea31c7d406d559a17e2226325c723d50c56900b9c0da7b62adaae2affc9'
def run(*args,**kw):subprocess.run(list(args),check=True,**kw)
def main():
    assert sys.platform.startswith('linux') and platform.machine()=='x86_64'
    build=ROOT/'build/linux';package=build/'package';app=package/'opt/flowstudio';app.mkdir(parents=True)
    archive=build/'python.tar.gz'
    urllib.request.urlretrieve('https://github.com/astral-sh/python-build-standalone/releases/download/20261009/cpython-3.13.16%2B20261009-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz',archive)
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==SHA
    with tarfile.open(archive) as tar:tar.extractall(app,filter='data')
    python=app/'python/bin/python3'
    run(str(python),'-m','pip','install','--only-binary=:all:','-r',str(ROOT/'requirements-linux.lock'))
    run(str(python),'-m','pip','check')
    for name in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0'):
        if not name or name.startswith('.github/'):continue
        source=ROOT/name
        if source.is_file():
            target=app/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    (app/'installed.flag').write_text('Flow Studio managed installation\n')
    manifest={'python':'3.13.16','python_sha256':SHA,'architecture':'x86_64','packages':json.loads(subprocess.check_output([str(python),'-m','pip','list','--format=json']))}
    (app/'RUNTIME_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    test_deps=build/'test-dependencies'
    run(str(python),'-m','pip','install','--only-binary=:all:','--no-deps','--target',str(test_deps),'lupa==2.8')
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',FLOWSTUDIO_DATA_DIR=str(build/'test-data'),PYTHONPATH=str(app)+os.pathsep+str(test_deps))
    run(str(python),'-m','unittest','discover','-s',str(app/'tests'),cwd=app,env=env)
    run(str(python),str(app/'scripts/smoke_desktop.py'),cwd=app,env=env)
    launcher=package/'usr/bin/flowstudio';launcher.parent.mkdir(parents=True)
    launcher.write_text('#!/bin/sh\ncd /opt/flowstudio || exit 1\nexec /opt/flowstudio/python/bin/python3 /opt/flowstudio/main.py </dev/null >/dev/null 2>&1\n');launcher.chmod(0o755)
    desktop=package/'usr/share/applications/flowstudio.desktop';desktop.parent.mkdir(parents=True)
    desktop.write_text('[Desktop Entry]\nType=Application\nName=Flow Studio\nExec=flowstudio\nIcon=flowstudio\nTerminal=false\nCategories=AudioVideo;Video;\nStartupWMClass=Flow Studio\n')
    icon=package/'usr/share/icons/hicolor/256x256/apps/flowstudio.png';icon.parent.mkdir(parents=True)
    from PIL import Image
    Image.open(ROOT/'assets/flowstudio.png').resize((256,256)).save(icon)
    control=package/'DEBIAN/control';control.parent.mkdir()
    control.write_text(f'Package: flowstudio\nVersion: {VERSION}\nArchitecture: amd64\nMaintainer: Flow Studio\nSection: video\nPriority: optional\nDepends: libc6 (>= 2.35), libgl1, libegl1, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xinerama0, libxcb-randr0, libxcb-shape0, libxcb-sync1, libxcb-xfixes0, libxcb-shm0, libxcb-xkb1, libdbus-1-3, libfontconfig1, libfreetype6, libnss3, libpulse0, libasound2 | libasound2t64, xdg-utils\nRecommends: gnome-keyring, fonts-noto-cjk\nDescription: Flow Studio local video production desktop\n')
    for p in app.rglob('__pycache__'):shutil.rmtree(p)
    for p in app.rglob('*'):
        if p.is_file() and p.suffix in ('.db','.sqlite3','.log'):raise RuntimeError('Unexpected user data: '+str(p))
    dist=ROOT/'dist';dist.mkdir(exist_ok=True);deb=dist/f'FlowStudio-{VERSION}-Linux-amd64.deb'
    run('dpkg-deb','--root-owner-group','--build',str(package),str(deb))
    run('dpkg-deb','--info',str(deb))
    extracted=build/'installed-test';run('dpkg-deb','-x',str(deb),str(extracted))
    installed=extracted/'opt/flowstudio';env['PYTHONPATH']=str(installed)
    run(str(installed/'python/bin/python3'),str(installed/'scripts/smoke_desktop.py'),cwd=installed,env=env)
    env['QT_QPA_PLATFORM']='xcb'
    run('xvfb-run','-a',str(installed/'python/bin/python3'),str(installed/'scripts/smoke_desktop.py'),cwd=installed,env=env)
    with deb.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    deb.with_suffix('.deb.sha256').write_text(digest+'  '+deb.name+'\n')
if __name__=='__main__':main()
