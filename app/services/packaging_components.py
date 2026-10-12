from pathlib import Path
import shutil,os
from app.services.app_paths import data_dir

def find_node():
    found=shutil.which('node')
    if found:return found
    folder=data_dir()/'packaging/node'
    candidates=list(folder.glob('**/node.exe'))+list(folder.glob('**/bin/node'))
    if candidates:
        os.environ['PATH']=str(candidates[0].parent)+os.pathsep+os.environ.get('PATH','')
        return str(candidates[0])
    return None
