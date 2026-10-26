"""Stage/apply HTTPS ingress without DNS changes or production dependency builds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request

BASE = Path('/home/codex-admin/services/self-agent')
TUNNEL_CONFIG = Path('/etc/cloudflared/config.yml')
SERVER_CONFIG = BASE / 'config/server.json'
TUNNEL_ID = 'caa74e4b-9f75-40d1-822a-77a32d993b77'


def ingress_candidate(original, hostname):
    if len(hostname) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', hostname):
        raise ValueError('invalid_hostname')
    if not re.search(r'^tunnel:\s*' + re.escape(TUNNEL_ID) + r'\s*$', original, re.M):
        raise ValueError('unexpected_tunnel')
    if re.search(r'^\s*-\s*hostname:\s*[\"\x27]?' + re.escape(hostname) + r'[\"\x27]?\s*$', original, re.M):
        raise ValueError('hostname_already_configured')
    catchall = list(re.finditer(r'^  - service: http_status:404\s*$', original, re.M))
    if len(catchall) != 1:
        raise ValueError('unexpected_catchall')
    offset = catchall[0].start()
    addition = '  - hostname: ' + hostname + '\n    service: http://127.0.0.1:8766\n'
    return original[:offset] + addition + original[offset:]


def checked(args):
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=60)


def replace_private(path, content, previous_stat):
    fd, name = tempfile.mkstemp(prefix='.self-agent-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, previous_stat.st_mode & 0o777)
        os.chown(name, previous_stat.st_uid, previous_stat.st_gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def health(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(30):
        try:
            with opener.open(url, timeout=2) as response:
                if json.load(response).get('status') == 'ok':
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError('origin_health_failed')


def main():
    import fcntl
    parser = argparse.ArgumentParser()
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-name')
    args = parser.parse_args()
    hostname = args.hostname
    if args.apply and args.confirm_name != hostname:
        raise ValueError('exact_hostname_confirmation_required')
    with (BASE / 'deploy.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old_tunnel = TUNNEL_CONFIG.read_bytes()
        old_server = SERVER_CONFIG.read_bytes()
        tunnel_stat, server_stat = TUNNEL_CONFIG.stat(), SERVER_CONFIG.stat()
        next_tunnel = ingress_candidate(old_tunnel.decode(), hostname).encode()
        server = json.loads(old_server)
        server.update(host='127.0.0.1', secure_cookie=True)
        next_server = (json.dumps(server, indent=2) + '\n').encode()
        directory = BASE / 'config/public-rollouts' / (str(time.time_ns()) + '-' + hostname)
        directory.mkdir(parents=True, mode=0o700)
        for name, content in [('tunnel.before.yml', old_tunnel), ('server.before.json', old_server),
                              ('tunnel.next.yml', next_tunnel), ('server.next.json', next_server)]:
            file = directory / name
            file.write_bytes(content)
            file.chmod(0o600)
        checked(['/usr/local/bin/cloudflared', 'tunnel', '--config', str(directory / 'tunnel.next.yml'), 'ingress', 'validate'])
        record = {'hostname': hostname, 'dns_type': 'CNAME', 'dns_name': hostname,
                  'dns_target': TUNNEL_ID + '.cfargotunnel.com', 'dns_proxied': True,
                  'dns_changed': False, 'public_verified': False, 'rollback_directory': str(directory),
                  'tunnel_before_sha256': hashlib.sha256(old_tunnel).hexdigest(),
                  'tunnel_after_sha256': hashlib.sha256(next_tunnel).hexdigest(),
                  'server_before_sha256': hashlib.sha256(old_server).hexdigest(),
                  'server_after_sha256': hashlib.sha256(next_server).hexdigest(), 'applied': False}
        if args.apply:
            if TUNNEL_CONFIG.read_bytes() != old_tunnel or SERVER_CONFIG.read_bytes() != old_server:
                raise RuntimeError('configuration_changed')
            try:
                replace_private(SERVER_CONFIG, next_server, server_stat)
                checked(['systemctl', 'restart', 'self-agent.service'])
                health('http://127.0.0.1:8766/healthz')
                replace_private(TUNNEL_CONFIG, next_tunnel, tunnel_stat)
                # The installed connector has no reload support.
                checked(['systemctl', 'restart', 'cloudflared.service'])
                checked(['systemctl', 'is-active', '--quiet', 'cloudflared.service'])
                record['applied'] = True
            except BaseException:
                replace_private(SERVER_CONFIG, old_server, server_stat)
                replace_private(TUNNEL_CONFIG, old_tunnel, tunnel_stat)
                checked(['systemctl', 'restart', 'self-agent.service'])
                checked(['systemctl', 'restart', 'cloudflared.service'])
                old_host = json.loads(old_server)['host']
                health('http://' + old_host + ':8766/healthz')
                raise
        (directory / 'record.json').write_text(json.dumps(record, indent=2))
        print(json.dumps(record))


if __name__ == '__main__':
    main()
