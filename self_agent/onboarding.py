"""One prompt or one pairing code; store only a knowledge-service device key."""
import getpass
import json
from pathlib import Path
import secrets
import socket
from urllib.parse import urlparse
import httpx
from .config import private_root
from .install import backup, install_client


def setup(url, client='codex', pair_code=None, proxy=None, prompt=getpass.getpass):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('invalid_service_url')
    if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('请使用 HTTPS 服务地址')
    if proxy:
        p = urlparse(proxy)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            raise ValueError('invalid_proxy_url')
    with httpx.Client(base_url=url.rstrip('/'), proxy=proxy, trust_env=False, follow_redirects=False, timeout=20) as remote:
        if not pair_code:
            cpa_key = prompt('CPA 密钥（隐藏输入）：').strip()
            # Exchange once for a scoped device key. Never store the CPA key on disk.
            response = remote.post('/api/pairing', json={'name': socket.gethostname()[:50] + ' · ' + client}, headers={'Authorization': 'Bearer ' + cpa_key})
            response.raise_for_status()
            pair_code = response.json()['code']
            cpa_key = None
        response = remote.post('/api/pairing/redeem', json={'code': pair_code})
        response.raise_for_status()
        device_key = response.json()['token']
        check = remote.get('/api/me', headers={'Authorization': 'Bearer ' + device_key})
        check.raise_for_status()
    private = private_root()
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_file = private / ('device-' + secrets.token_hex(8) + '.token')
    key_file.write_text(device_key, 'utf-8')
    key_file.chmod(0o600)
    config_file = private / 'client.json'
    backup(config_file, private / 'config-backups')
    values = {'url': url.rstrip('/'), 'token_file': str(key_file)}
    if proxy:
        values['proxy'] = proxy
    temporary = config_file.with_suffix('.tmp')
    temporary.write_text(json.dumps(values), 'utf-8')
    temporary.chmod(0o600)
    temporary.replace(config_file)
    clients = ('codex', 'claude') if client == 'both' else (client,)
    result = [install_client(name) for name in clients]
    return {'connected': True, 'clients': list(clients), 'hook_review_required': 'codex' in clients, 'key_file': str(key_file)}
