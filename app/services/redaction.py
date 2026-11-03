import re
SENSITIVE={'authorization','api_key','access_token','refresh_token','client_secret','private_key','password','token','totp','totp_secret','x_api_key','xi_api_key','x_goog_api_key','cookie','set_cookie'}
def redact(value):
    if isinstance(value,dict):return {k:('[REDACTED]' if str(k).lower().replace('-','_') in SENSITIVE else redact(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [redact(v) for v in value]
    if isinstance(value,str):
        value=re.sub(r'(?i)(Bearer\s+)[\w.\-]+',r'\1[REDACTED]',value)
        value=re.sub(r'\bsk-[A-Za-z0-9_-]{20,}','[REDACTED]',value)
        value=re.sub(r'(?i)([?&](?:code|key|api_key|access_token|refresh_token|client_secret|token|signature|x-goog-signature|x-amz-signature)=)[^&\s]+',r'\1[REDACTED]',value)
        value=re.sub(r'\b(?:AIza[A-Za-z0-9_-]{30,}|gsk_[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,})','[REDACTED]',value)
        value=re.sub(r'''(?i)((?:["']?)(?:api[_-]?key|access_token|refresh_token|client_secret|password|totp_secret|x-api-key|xi-api-key|x-goog-api-key)(?:["']?)\s*[:=]\s*)(["'])(.*?)\2''',r'\1"[REDACTED]"',value)
    return value
