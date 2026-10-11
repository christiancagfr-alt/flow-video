import re
SENSITIVE={'authorization','api_key','access_token','refresh_token','client_secret','private_key','password','token'}
def redact(value):
    if isinstance(value,dict):return {k:('[REDACTED]' if str(k).lower() in SENSITIVE else redact(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [redact(v) for v in value]
    if isinstance(value,str):
        value=re.sub(r'(?i)(Bearer\s+)[\w.\-]+',r'\1[REDACTED]',value)
        value=re.sub(r'\bsk-[A-Za-z0-9_-]{20,}','[REDACTED]',value)
        value=re.sub(r'(?i)([?&](?:code|access_token|refresh_token|client_secret)=)[^&\s]+',r'\1[REDACTED]',value)
    return value
