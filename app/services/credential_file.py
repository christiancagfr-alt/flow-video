"""Protect refresh credentials with the current Windows user's DPAPI key."""
import os,json,base64
from pathlib import Path

def save(path,text):
    path=Path(path)
    if os.name=='nt':
        import win32crypt
        encrypted=win32crypt.CryptProtectData(text.encode('utf-8'),'Flow Studio Google OAuth',None,None,None,1)
        text=json.dumps({'windows_dpapi':base64.b64encode(encrypted).decode('ascii')})
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(text,encoding='utf-8')
    if os.name!='nt':os.chmod(temporary,0o600)
    temporary.replace(path)

def load(path):
    path=Path(path);data=json.loads(path.read_text(encoding='utf-8'))
    if 'windows_dpapi' in data:
        if os.name!='nt':raise ValueError('Windows credentials must be reauthorized on this platform')
        import win32crypt
        return json.loads(win32crypt.CryptUnprotectData(base64.b64decode(data['windows_dpapi']),None,None,None,1)[1].decode('utf-8'))
    if os.name=='nt':save(path,json.dumps(data))
    return data
