import hashlib,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.version import VERSION
import build_windows_portable as portable
portable.main()
output=portable.OUT
(output/'installed.flag').write_text('Flow Studio managed installation\n')
python=output/'runtime/python.exe'
test_deps=ROOT/'build/test-dependencies'
# Install the test-only wheel using the build Python, never alter the release runtime.
subprocess.run([sys.executable,'-m','pip','download','--only-binary=:all:','--no-deps','--python-version','313','--implementation','cp','--abi','cp313','--platform','win_amd64','--dest',str(test_deps),'lupa==2.8'],check=True)
for wheel in test_deps.glob('*.whl'):portable.extract_checked(wheel,test_deps,wheel=True)
runner=ROOT/'build/run-tests.py'
runner.write_text("import sys,unittest\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(test_deps))+ ")\nsuite=unittest.defaultTestLoader.discover("+repr(str(output/'tests'))+")\nraise SystemExit(not unittest.TextTestRunner().run(suite).wasSuccessful())\n")
env=dict(os.environ,QT_QPA_PLATFORM='offscreen',FLOWSTUDIO_DATA_DIR=str(ROOT/'build/test-data'))
subprocess.run([str(python),str(runner)],check=True,env=env,cwd=output)
subprocess.run([str(python),str(output/'scripts/smoke_desktop.py')],check=True,env=env,cwd=output)
for p in output.rglob('__pycache__'):shutil.rmtree(p)
compiler=shutil.which('ISCC.exe') or 'C:/Program Files (x86)/Inno Setup 6/ISCC.exe'
subprocess.run([compiler,'/DAppVersion='+VERSION,str(ROOT/'scripts/windows-installer.iss')],check=True)
installer=ROOT/'dist'/f'FlowStudio-{VERSION}-Windows-x64-Setup.exe'
with installer.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
installer.with_suffix('.exe.sha256').write_text(digest+'  '+installer.name+'\n')
# Silent clean installation validates the real installer, without starting the app.
installed=ROOT/'build/installed-test'
subprocess.run([str(installer),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/DIR='+str(installed)],check=True)
subprocess.run([str(installed/'runtime/python.exe'),str(installed/'scripts/smoke_desktop.py')],check=True,env=env,cwd=installed)
