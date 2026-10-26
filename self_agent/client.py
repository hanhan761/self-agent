from pathlib import Path
import json
import os
from urllib.parse import urlparse
import httpx
from .config import private_root


def client_config():
    filename=Path(os.environ.get('SELF_AGENT_CLIENT_CONFIG',private_root()/'client.json'))
    if not filename.exists():raise RuntimeError('client_not_configured')
    value=json.loads(filename.read_text('utf-8'))
    parsed=urlparse(value['url'])
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('invalid_service_url')
    return value


def request(method,path,*,body=None,params=None,timeout=10):
    config=client_config()
    token=Path(config['token_file']).read_text('utf-8').strip()
    with httpx.Client(base_url=config['url'].rstrip('/'),timeout=timeout,trust_env=False,follow_redirects=False,proxy=config.get('proxy')) as client:
        response=client.request(method,path,params=params,json=body,headers={'Authorization':'Bearer '+token})
        response.raise_for_status()
        return response.json()
