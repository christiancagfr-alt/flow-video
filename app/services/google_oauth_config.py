"""Validate OAuth configuration without logging credentials."""
import json
from pathlib import Path


def load_desktop_config(path):
    path=Path(path).expanduser()
    if not path.is_file():
        raise ValueError('请选择 Google OAuth 桌面应用客户端 JSON 文件。')
    try:
        data=json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, OSError, UnicodeError):
        raise ValueError('授权文件不是可读取的 JSON，请重新下载 OAuth 桌面应用客户端文件。') from None
    if isinstance(data,dict) and data.get('type')=='service_account':
        raise ValueError('选中的是服务账号密钥，不能用于当前 Google 账号登录。请在 Google Cloud 创建 OAuth 客户端 ID，应用类型选择“桌面应用”，下载 JSON 后在系统设置中重新选择。无需修改或重命名现有密钥内容。')
    if not isinstance(data,dict) or not isinstance(data.get('installed'),dict):
        raise ValueError('请选择 OAuth“桌面应用”客户端 JSON；登录令牌、服务账号密钥和 Web 客户端文件不适用于此入口。')
    config=data['installed']
    required=('client_id','client_secret','auth_uri','token_uri','redirect_uris')
    if any(not config.get(key) for key in required) or not isinstance(config.get('redirect_uris'),list):
        raise ValueError('OAuth 桌面应用客户端文件缺少必要字段，请从 Google Cloud 重新下载完整 JSON。')
    return data
