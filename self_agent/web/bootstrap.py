"""Agent bootstrap. Read pairing data from stdin; never from process arguments."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Unexpected redirect; verify the service URL')


def main():
    if sys.version_info < (3, 11):
        raise RuntimeError('Select or install Python 3.11+ before running the bootstrap')
    settings=json.loads(sys.stdin.read(16384))
    origin=settings['service_url'].rstrip('/')
    parsed=urllib.parse.urlparse(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('An exact HTTPS service origin is required')
    pair=settings['pair_code']
    if not isinstance(pair,str) or not 20<=len(pair)<=100:
        raise ValueError('Invalid pairing code')
    client=settings.get('client','auto')
    if client not in ('auto','codex','claude','both'):
        raise ValueError('Unsupported client')
    proxy=settings.get('proxy')
    if not proxy:
        candidates=urllib.request.getproxies()
        proxy=candidates.get('https') or candidates.get('http')
    if proxy:
        if '://' not in proxy:proxy='http://'+proxy
        p=urllib.parse.urlparse(proxy)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
            raise ValueError('Proxy must be HTTP(S), without embedded credentials')
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                                      urllib.request.ProxyHandler({'http':proxy,'https':proxy} if proxy else {}))
    def download(relative,limit):
        with opener.open(origin+relative,timeout=45) as response:
            data=response.read(limit+1)
        if len(data)>limit:raise RuntimeError('Download exceeds the client size limit')
        return data
    manifest=json.loads(download('/assets/downloads/client-manifest.json',16384))
    if not re.fullmatch('[0-9a-f]{64}',str(manifest.get('sha256',''))):
        raise RuntimeError('Invalid client manifest')
    content=download('/assets/downloads/client.zip',10*1024**2)
    if hashlib.sha256(content).hexdigest()!=manifest['sha256']:
        raise RuntimeError('Client SHA-256 mismatch')
    if os.name=='nt':
        private=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'self-agent'
    else:
        private=Path.home()/'.local/share/self-agent'
    work=private/'client'/('agent-'+secrets.token_hex(8))
    source=work/'source'
    source.mkdir(parents=True,mode=0o700)
    archive=work/'client.zip';archive.write_bytes(content);archive.chmod(0o600)
    with zipfile.ZipFile(archive) as zipped:
        if sum(item.file_size for item in zipped.infolist())>32*1024**2:
            raise RuntimeError('Expanded client exceeds its size limit')
        for item in zipped.infolist():
            target=(source/item.filename).resolve()
            if not target.is_relative_to(source.resolve()) or ':' in item.filename or (item.external_attr>>16)&0o170000==0o120000:
                raise RuntimeError('Unsafe archive member')
        zipped.extractall(source)
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    def run(arguments,body=None,timeout=600):
        result=subprocess.run(arguments,input=body,capture_output=True,text=True,timeout=timeout,**flags)
        if result.returncode:
            # setup deliberately emits no key or request body in errors.
            raise RuntimeError('Setup step failed: '+result.stderr[-1500:])
        if result.stdout.strip():print(result.stdout.strip(),flush=True)
    environment=work/'venv'
    run([sys.executable,'-m','venv',str(environment)])
    python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    arguments=[str(python),'-m','pip','install','--disable-pip-version-check','-e',str(source)]
    if proxy:arguments+=['--proxy',proxy]
    run(arguments)
    arguments=[str(python),'-m','self_agent.cli','setup','--url',origin,'--client',client,'--pair-code-stdin']
    if proxy:arguments+=['--proxy',proxy]
    run(arguments,pair+'\n',timeout=60)
    pair=None
    run([str(python),'-c',"from self_agent.client import request;import json;d=request('GET','/v1/search',params={'q':'connection verification','limit':1});print(json.dumps({'connected':True,'authenticated_search_verified':isinstance(d.get('items'),list)}))"],timeout=30)
    print(json.dumps({'installation_directory':str(work),'next_step':'Rediscover/restart the host if required; Codex hook trust is reviewed in /hooks.'}))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(1)
