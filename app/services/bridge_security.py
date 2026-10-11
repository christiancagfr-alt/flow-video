"""HTTP boundary checks for loopback-only services."""
import re
from urllib.parse import urlsplit
from pathlib import Path

def allowed_request(headers,port,extensions=True):
    host=headers.get('Host','')
    if host not in (f'127.0.0.1:{port}',f'localhost:{port}',f'[::1]:{port}'):return False
    origin=headers.get('Origin','')
    if origin:
        if origin in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):return True
        return bool(extensions and re.fullmatch(r'chrome-extension://[a-p]{32}',origin))
    return headers.get('Sec-Fetch-Site','') not in ('cross-site','same-site')

def published_file(path,jobs):
    try:target=Path(path).resolve(strict=True)
    except (OSError,ValueError):return False
    if target.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.gif','.mp4','.mov','.webm','.wav','.mp3','.m4a'):return False
    def visit(value):
        if isinstance(value,dict):return any(visit(v) for v in value.values())
        if isinstance(value,(list,tuple)):return any(visit(v) for v in value)
        if isinstance(value,str):
            try:return Path(value).is_absolute() and Path(value).resolve()==target
            except (OSError,ValueError):return False
        return False
    return visit(jobs)
