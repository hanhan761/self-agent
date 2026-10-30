"""Local setup and lifecycle. Credentials and machine state stay outside Git."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse
import httpx
from .config import Config,private_root
from .spool import atomic_json


def load_local(root=None):
    root=Path(root or private_root()/'local')
    value=json.loads((root/'server.json').read_text('utf-8'))
    return Config(data_dir=root,**value)


def local_client(config,python=None,repo=None):
    return {'local':True,'url':'http://127.0.0.1:'+str(config.port),
            'token_file':str(config.data_dir/'device.token'),'local_data_dir':str(config.data_dir),
            'local_started_at':config.local_started_at,'instance_id':config.local_instance_id,
            'python':str(python or sys.executable),'source':str(repo or Path(__file__).resolve().parents[1])}


def healthy(client):
    try:
        with httpx.Client(trust_env=False,timeout=0.3) as http:
            import hmac
            challenge=secrets.token_hex(16)
            value=http.get(client['url']+'/healthz',params={'challenge':challenge}).json()
            token=Path(client['token_file']).read_text('utf-8').strip()
            proof=hmac.new(token.encode(),challenge.encode(),hashlib.sha256).hexdigest()
            return value.get('local_instance_id')==client['instance_id'] and hmac.compare_digest(value.get('proof',''),proof)
    except (httpx.HTTPError,ValueError,OSError):return False


def ensure_service(client):
    sync_connection(client)
    if healthy(client):return True
    root=Path(client['local_data_dir'])
    from .lock import ProcessLock
    try:
        with ProcessLock(root/'launch.lock'):
            if healthy(client):return True
            # A recent launch may still be loading: don't create duplicate interpreters.
            marker=root/'launch.json'
            if marker.exists():
                try:
                    if time.time()-json.loads(marker.read_text('utf-8'))['at']<20:return False
                except (ValueError,KeyError):pass
            python=Path(client['python'])
            if os.name=='nt' and python.with_name('pythonw.exe').exists():python=python.with_name('pythonw.exe')
            root.mkdir(parents=True,exist_ok=True)
            with (root/'service.log').open('ab') as log:
                process=subprocess.Popen([str(python),str(Path(client['source'])/'scripts/local_runner.py'),'serve','--root',str(root)],
                    stdin=subprocess.DEVNULL,stdout=log,stderr=log,cwd=client['source'],
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            atomic_json(marker,{'at':time.time(),'pid':process.pid})
    except RuntimeError:return False
    return False


def wait_service(client,timeout=30):
    ensure_service(client)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        sync_connection(client)
        if healthy(client):return True
        time.sleep(0.1)
    raise RuntimeError('local_service_did_not_start')


def set_autostart(client,enabled=True):
    if os.name!='nt':return False
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            python=Path(client['python']).with_name('pythonw.exe')
            command=subprocess.list2cmdline([str(python),str(Path(client['source'])/'scripts/local_runner.py'),'ensure','--root',client['local_data_dir']])
            winreg.SetValueEx(key,'SelfAgentLocal',0,winreg.REG_SZ,command)
        else:
            try:
                current=winreg.QueryValueEx(key,'SelfAgentLocal')[0]
                expected=subprocess.list2cmdline([str(Path(client['python']).with_name('pythonw.exe')),str(Path(client['source'])/'scripts/local_runner.py'),'ensure','--root',client['local_data_dir']])
                if current==expected:winreg.DeleteValue(key,'SelfAgentLocal')
            except FileNotFoundError:pass
    return enabled


def setup_local(client='auto',home=None,data_dir=None,model_cache=None,xjcode_home=None,
                start=True,autostart=True,client_file=None):
    from .auth import Auth
    from .store import Store
    from .install import install_client,backup
    home=Path(home or Path.home())
    root=Path(data_dir or private_root()/'local').resolve();root.mkdir(parents=True,exist_ok=True)
    path=root/'server.json'
    fresh=not path.exists()
    repo=Path(__file__).resolve().parents[1]
    bundle=repo.parent
    model_cache=Path(model_cache or bundle/'models/paraphrase-multilingual-MiniLM-L12-v2')
    if not (model_cache/'model.onnx').is_file() or not (model_cache/'tokenizer.json').is_file():
        raise RuntimeError('local_model_not_installed')
    if fresh:
        config=Config(data_dir=root,local=True,local_instance_id=secrets.token_hex(16),
                      local_started_at=time.time(),index_backend='mcp-memory-service',semantic=True,
                      embedding_model='paraphrase-multilingual-MiniLM-L12-v2',embedding_dims=384,
                      model_cache=str(model_cache),max_data_bytes=8*1024**3,
                      xjtu_auto_switch=True,xjtu_backup_models=('qwen-plus-latest',))
        # The selected port is verified free; the server still fails closed on a later collision.
        with socket.socket() as port:
            try:port.bind(('127.0.0.1',8766));config.port=8766
            except OSError:
                port.bind(('127.0.0.1',0));config.port=port.getsockname()[1]
        store=Store(root/'memory.sqlite3')
        try:
            auth=Auth(store)
            with store.tx() as db:existing=db.execute("SELECT id FROM users WHERE username='local'").fetchone()
            config.local_user_id=existing[0] if existing else auth.create_user('local',secrets.token_urlsafe(32),True)
            token=auth.issue_key(config.local_user_id,'local-device')
            (root/'device.token').write_text(token,'utf-8');(root/'device.token').chmod(0o600)
        finally:store.close()
    else:
        if start and (root/'local-client.json').exists():
            if not stop(root)['stopped']:raise RuntimeError('old_local_service_still_running')
            (root/'launch.json').unlink(missing_ok=True)
        config=load_local(root)
        config.model_cache=str(model_cache)
    # Reuse only the explicitly selected XJCode home under this Windows user.
    auth_home=Path(xjcode_home or home/'.xjcode').resolve()
    if (auth_home/'credentials.dpapi').exists():
        from .xjcode_auth import discover
        route=discover(auth_home,model=config.xjtu_model,backup_models=config.xjtu_backup_models if config.xjtu_auto_switch else ())
        if config.xjtu_account_fingerprint and route['account_fingerprint']!=config.xjtu_account_fingerprint:
            raise RuntimeError('native_account_changed')
        config.xjcode_home=str(auth_home)
        config.xjtu_account_fingerprint=route['account_fingerprint']
        config.allow_campus_http=True
        atomic_json(root/'native-route.json',route)
    else:
        from .xjcode_auth import login,discover
        helper=bundle/'bin/xjcode-login.exe'
        login(auth_home,helper)
        route=discover(auth_home,model=config.xjtu_model,backup_models=config.xjtu_backup_models if config.xjtu_auto_switch else ())
        config.xjcode_home=str(auth_home);config.xjtu_account_fingerprint=route['account_fingerprint']
        config.allow_campus_http=True
        atomic_json(root/'native-route.json',route)
    values={k:v for k,v in vars(config).items() if k!='data_dir'}
    atomic_json(path,values)
    connection=local_client(config)
    atomic_json(root/'local-client.json',connection)
    if start:
        wait_service(connection)
        wait_ready(connection)
        config.port=urlparse(connection['url']).port
    connection_file=Path(client_file or private_root()/'client.json')
    if fresh:
        atomic_json(root/'previous-client.json',{'present':connection_file.exists(),
                    'value':json.loads(connection_file.read_text('utf-8')) if connection_file.exists() else None})
    if start and connection_file.exists() and not (root/'migration.json').exists():
        previous=json.loads(connection_file.read_text('utf-8'))
        if not previous.get('local'):
            from .local_migration import migrate
            migrate(config,previous)
    backup(connection_file,root/'config-backups')
    if not connection_file.exists() or not json.loads(connection_file.read_text('utf-8')).get('local'):
        config.local_started_at=time.time()
        atomic_json(path,{k:v for k,v in vars(config).items() if k!='data_dir'})
        connection['local_started_at']=config.local_started_at
    atomic_json(connection_file,connection)
    atomic_json(root/'local-client.json',connection)
    selected=['codex','claude'] if client=='both' else [client]
    if client=='auto':selected=[c for c,d in [('codex','.codex'),('claude','.claude')] if (home/d).exists()]
    if not selected:raise RuntimeError('no_supported_client_found')
    installed=[install_client(c,home=home) for c in selected]
    if autostart:
        set_autostart(connection)
        create_shortcut(connection)
    result={'local':True,'configured':True,'clients':installed,'data_directory':str(root),
            'hook_review_required':'codex' in selected,'reload_required':True,
            'backend':'mcp-memory-service 12.4.0','url':connection['url']}
    atomic_json(root/'installation.json',{'connection_file':str(connection_file),'clients':selected,
                                         'autostart':autostart,'source':str(repo)})
    return result


def status(root=None):
    root=Path(root or private_root()/'local')
    if not (root/'local-client.json').exists():return {'installed':False}
    client=json.loads((root/'local-client.json').read_text('utf-8'))
    value={'installed':True,'running':healthy(client),'url':client['url'],
           'pending_capture':len(list((root/'inbox').glob('*.json')))}
    if value['running']:
        token=Path(client['token_file']).read_text('utf-8').strip()
        with httpx.Client(trust_env=False,timeout=3) as http:
            r=http.get(client['url']+'/api/overview',headers={'Authorization':'Bearer '+token});r.raise_for_status()
            value['overview']=r.json()
    return value


def stop(root=None):
    root=Path(root or private_root()/'local')
    client=json.loads((root/'local-client.json').read_text('utf-8'))
    if not healthy(client):return {'stopped':True}
    token=Path(client['token_file']).read_text('utf-8').strip()
    with httpx.Client(trust_env=False,timeout=3) as http:
        r=http.post(client['url']+'/api/local/stop',json={},headers={'Authorization':'Bearer '+token});r.raise_for_status()
    deadline=time.monotonic()+8
    while healthy(client) and time.monotonic()<deadline:time.sleep(0.1)
    return {'stopped':not healthy(client)}


def serve(root):
    import uvicorn
    from .lock import ProcessLock
    from .server import create_app
    config=load_local(root)
    with ProcessLock(config.data_dir/'server.lock'), socket.socket() as listener:
        try:listener.bind(('127.0.0.1',config.port))
        except OSError:
            listener.bind(('127.0.0.1',0));config.port=listener.getsockname()[1]
            atomic_json(config.data_dir/'server.json',{k:v for k,v in vars(config).items() if k!='data_dir'})
            updated=local_client(config)
            atomic_json(config.data_dir/'local-client.json',updated)
            installation=config.data_dir/'installation.json'
            if installation.exists():
                target=Path(json.loads(installation.read_text('utf-8'))['connection_file'])
                if target.exists() and json.loads(target.read_text('utf-8')).get('instance_id')==config.local_instance_id:
                    atomic_json(target,updated)
        app=create_app(config)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=config.port,access_log=False,log_config=None,log_level='warning'))
        app.state.local_shutdown=lambda:setattr(server,'should_exit',True)
        server.run(sockets=[listener])


def repair(root=None,home=None):
    root=Path(root or private_root()/'local');config=load_local(root)
    install=json.loads((root/'installation.json').read_text('utf-8'))
    from .install import install_client
    for client in install['clients']:install_client(client,home=home)
    connection=local_client(config)
    atomic_json(root/'local-client.json',connection)
    atomic_json(Path(install['connection_file']),connection)
    set_autostart(connection,install['autostart'])
    wait_service(connection)
    return status(root)


def uninstall(root=None,home=None):
    root=Path(root or private_root()/'local')
    install=json.loads((root/'installation.json').read_text('utf-8'))
    result=stop(root)
    if not result['stopped']:raise RuntimeError('local_service_still_running')
    from .install import remove_client
    for client in install['clients']:remove_client(client,home=home)
    if install['autostart']:
        client=json.loads((root/'local-client.json').read_text('utf-8'))
        set_autostart(client,False)
        create_shortcut(client,remove=True)
    connection_file=Path(install['connection_file'])
    if connection_file.exists():
        current=json.loads(connection_file.read_text('utf-8'))
        if current.get('local_data_dir')==str(root):
            previous=json.loads((root/'previous-client.json').read_text('utf-8'))
            if previous['present']:atomic_json(connection_file,previous['value'])
            else:connection_file.unlink()
    return {'uninstalled':True,'data_preserved':str(root)}


def open_ui(root=None):
    """Authenticate the optional browser UI via a private one-use POST, never a secret URL."""
    import html,webbrowser
    root=Path(root or private_root()/'local');config=load_local(root)
    client=local_client(config);wait_service(client)
    ticket=secrets.token_urlsafe(32)
    atomic_json(root/'ui-ticket.json',{'hash':hashlib.sha256(ticket.encode()).hexdigest(),'expires':time.time()+60})
    file=root/'open-library.html'
    file.write_text('<!doctype html><meta charset="utf-8"><title>Self Agent</title>'
        '<form method="post" action="'+html.escape(client['url'])+'/api/local/open">'
        '<input type="hidden" name="ticket" value="'+html.escape(ticket)+'">'
        '<button>打开本机知识库</button></form><script>document.forms[0].submit()</script>','utf-8')
    file.chmod(0o600)
    webbrowser.open(file.as_uri())
    # This launcher is explicitly user-invoked; keep the private ticket briefly, then remove it.
    deadline=time.monotonic()+65
    while (root/'ui-ticket.json').exists() and time.monotonic()<deadline:time.sleep(0.2)
    file.unlink(missing_ok=True)
    return {'opened':True}


def wait_ready(client,timeout=120):
    token=Path(client['token_file']).read_text('utf-8').strip()
    deadline=time.monotonic()+timeout
    with httpx.Client(trust_env=False,timeout=3) as http:
        while time.monotonic()<deadline:
            response=http.get(client['url']+'/api/overview',headers={'Authorization':'Bearer '+token})
            response.raise_for_status();state=response.json()['search']
            if state['semantic']:return True
            if state['state'] not in ('not_loaded',''):raise RuntimeError('local_index_initialization_failed')
            time.sleep(0.2)
    raise RuntimeError('local_index_not_ready')


def sync_connection(client):
    """A verified instance may move to a free local port; never adopt another instance."""
    file=Path(client['local_data_dir'])/'local-client.json'
    if file.exists():
        saved=json.loads(file.read_text('utf-8'))
        if saved.get('instance_id')==client['instance_id']:
            client['url']=saved['url']


def create_shortcut(client,remove=False):
    if os.name!='nt':return
    import win32com.client
    shell=win32com.client.Dispatch('WScript.Shell')
    menu=Path(shell.SpecialFolders('Programs'))/'Self Agent.lnk'
    shortcut=shell.CreateShortcut(str(menu))
    target=str(Path(client['python']).with_name('pythonw.exe'))
    if remove:
        if str(shortcut.TargetPath).lower()==target.lower():menu.unlink(missing_ok=True)
    else:
        shortcut.TargetPath=target
        shortcut.Arguments=subprocess.list2cmdline([str(Path(client['source'])/'scripts/open_local.py')])
        shortcut.WorkingDirectory=client['source'];shortcut.Save()
