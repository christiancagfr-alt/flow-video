"""Build a relocatable macOS application on a native GitHub runner."""
import argparse, hashlib, json, os, platform, plistlib, shutil, subprocess, tarfile, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HASHES={'arm64':'11785155d0f70e634178219c20925d8f20be00a3da4684fc4f5019dd15602ef7','x86_64':'bd085c51e960f00ee33b630e2b13ac90fe90cdc3da25a0f0bc0719b1294920bf'}
def run(*args,**kw): subprocess.run(list(args),check=True,**kw)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--arch',choices=HASHES,required=True);args=parser.parse_args()
    assert platform.system()=='Darwin' and platform.machine()==args.arch
    build=ROOT/'build/macos';build.mkdir(parents=True,exist_ok=True)
    app=build/'Flow Studio.app';resources=app/'Contents/Resources';resources.mkdir(parents=True,exist_ok=True)
    native='aarch64' if args.arch=='arm64' else args.arch
    name=f'cpython-3.13.16+20261009-{native}-apple-darwin-install_only_stripped.tar.gz'
    archive=build/name
    urllib.request.urlretrieve('https://github.com/astral-sh/python-build-standalone/releases/download/20261009/'+name,archive)
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==HASHES[args.arch], 'Python checksum mismatch'
    with tarfile.open(archive) as tar: tar.extractall(resources,filter='data')
    python=resources/'python/bin/python3'
    run(str(python),'-m','pip','install','--only-binary=:all:','--index-url','https://pypi.org/simple','-r',str(ROOT/'requirements-macos.lock'))
    run(str(python),'-m','pip','check')
    # Copy only version-controlled source, never local credentials or generated data.
    for name in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0'):
        if not name or name.startswith('.github/'): continue
        source=ROOT/name
        if source.is_file():
            target=resources/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    manifest={'python':'3.13.16','python_build':'20261009','architecture':args.arch,'python_sha256':HASHES[args.arch],
              'packages':json.loads(subprocess.check_output([str(python),'-m','pip','list','--format=json']))}
    (resources/'RUNTIME_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    executable=app/'Contents/MacOS/FlowStudio';executable.parent.mkdir(parents=True,exist_ok=True)
    executable.write_text('#!/bin/zsh\nset -eu\nROOT="$(cd "$(dirname "$0")/../Resources" && pwd)"\ncd "$ROOT"\nexec "$ROOT/python/bin/python3" "$ROOT/main.py" </dev/null >/dev/null 2>&1\n')
    executable.chmod(0o755)
    with (app/'Contents/Info.plist').open('wb') as f:
        plistlib.dump({'CFBundleName':'Flow Studio','CFBundleDisplayName':'Flow Studio','CFBundleIdentifier':'com.flowstudio.desktop',
            'CFBundleVersion':'0.13.5.106','CFBundleShortVersionString':'0.13.5.106','CFBundleExecutable':'FlowStudio',
            'CFBundlePackageType':'APPL','LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,
            'NSAppleEventsUsageDescription':'Flow Studio uses automation to control DaVinci Resolve.'},f)
    # Tests use isolated state outside the immutable application bundle.
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',FLOWSTUDIO_DATA_DIR=str(build/'test-data'),PYTHONPATH=str(resources))
    run(str(python),'-m','unittest','discover','-s',str(resources/'tests'),cwd=resources,env=env)
    run(str(python),str(resources/'scripts/smoke_macos.py'),cwd=resources,env=env)
    for p in resources.rglob('__pycache__'): shutil.rmtree(p)
    for p in resources.rglob('*'):
        if p.is_file() and p.suffix in ('.db','.sqlite3','.log'): raise RuntimeError('Unexpected user data: '+str(p))
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    output=dist/f'FlowStudio-0.13.5.106-macOS-{args.arch}.zip'
    run('/usr/bin/ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(output))
    # Verify relocation, including the Python/Qt runtime, after extraction.
    verify=build/'relocated';run('/usr/bin/ditto','-x','-k',str(output),str(verify))
    relocated=verify/'Flow Studio.app/Contents/Resources'
    env['PYTHONPATH']=str(relocated)
    run(str(relocated/'python/bin/python3'),str(relocated/'scripts/smoke_macos.py'),cwd=relocated,env=env)
    with output.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n')
if __name__=='__main__':main()
