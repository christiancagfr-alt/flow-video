"""Wait for the app to exit, recheck bytes, then open the native installer."""
import argparse,hashlib,os,subprocess,sys,time
from pathlib import Path
import psutil
parser=argparse.ArgumentParser();parser.add_argument('--parent',type=int,required=True);parser.add_argument('--file',required=True);parser.add_argument('--sha256',required=True);args=parser.parse_args()
try:
    parent=psutil.Process(args.parent)
    parent.wait(timeout=600)
except psutil.NoSuchProcess:pass
except psutil.TimeoutExpired:raise SystemExit(1)
p=Path(args.file)
with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==args.sha256
if sys.platform=='win32':
    subprocess.Popen([str(p)],creationflags=subprocess.CREATE_NO_WINDOW)
elif sys.platform=='darwin':subprocess.Popen(['/usr/bin/open',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
else:subprocess.Popen(['xdg-open',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
