import hashlib,json,time
from pathlib import Path
import pytest
from self_agent.config import Config
from self_agent.store import Store
from self_agent.auth import Auth
from self_agent.spool import capture,drain


def test_local_capture_is_durable_redacted_incremental_and_idempotent(tmp_path,monkeypatch):
    from self_agent import hooks
    now=time.time()
    rows=[{'id':'old','role':'user','content':'old private history','observed_at':now-60},
          {'id':'new','role':'user','content':'我喜欢中文。token: abcdefghijklmnop','observed_at':now}]
    monkeypatch.setattr(hooks,'normalized_messages',lambda *a:list(rows))
    root=tmp_path/'local';root.mkdir()
    config={'local_data_dir':str(root),'local_started_at':now-1}
    event={'transcript_path':str(tmp_path/'fake.jsonl')}
    capture(config,'codex',event,'project-a')
    pending=list((root/'inbox').glob('*.json'));assert len(pending)==1
    text=pending[0].read_text('utf-8')
    assert 'old private history' not in text and 'abcdefghijklmnop' not in text and '[REDACTED]' in text
    copy=pending[0].read_bytes()
    store=Store(root/'memory.sqlite3');uid=Auth(store).create_user('local','long-safe-password')
    cfg=Config(root,local=True,local_user_id=uid)
    drain(cfg,store);assert not list((root/'inbox').glob('*.json'))
    pending[0].write_bytes(copy);drain(cfg,store)  # Simulate crash after DB commit before inbox unlink.
    with store.tx() as db:
        assert db.execute('SELECT count(*) FROM sources').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==1
    capture(config,'codex',event,'project-a');assert not list((root/'inbox').glob('*.json'))
    rows.append({'id':'next','role':'assistant','content':'本轮完成','observed_at':now})
    capture(config,'codex',event,'project-a');assert len(list((root/'inbox').glob('*.json')))==1
    store.close()


def test_local_capture_does_not_advance_after_failed_publish(tmp_path,monkeypatch):
    from self_agent import hooks,spool
    monkeypatch.setattr(hooks,'normalized_messages',lambda *a:[{'id':'m','role':'user','content':'偏好中文','observed_at':time.time()}])
    original=spool.atomic_json
    def fail(path,value):
        if Path(path).parent.name=='inbox':raise OSError('disk full')
        original(path,value)
    monkeypatch.setattr(spool,'atomic_json',fail)
    with pytest.raises(OSError):capture({'local_data_dir':str(tmp_path),'local_started_at':0},'codex',{'transcript_path':'example'},'p')
    assert not list((tmp_path/'cursors').glob('*.json'))


def test_local_hook_never_waits_for_http_upload(tmp_path,monkeypatch):
    from self_agent import hooks,client,spool
    called=[]
    monkeypatch.setattr(hooks,'project_id',lambda *a:'p')
    monkeypatch.setattr(client,'client_config',lambda:{'local':True})
    monkeypatch.setattr(spool,'capture',lambda *a:called.append(a))
    monkeypatch.setattr(hooks,'request',lambda *a,**k:pytest.fail('network call in Stop'))
    assert hooks.handle('codex',{'hook_event_name':'Stop','transcript_path':'x'})=={}
    assert len(called)==1


def test_native_account_cannot_change_silently(tmp_path,monkeypatch):
    from self_agent import xjcode_auth
    monkeypatch.setattr(xjcode_auth,'identity',lambda home:{'account_id':'changed','access_key':'fixture','secret':'fixture'})
    cfg=Config(tmp_path,xjcode_home=str(tmp_path),xjtu_account_fingerprint='authorized')
    with pytest.raises(RuntimeError,match='native_account_not_allowed'):xjcode_auth.credentials(cfg)


def test_preflight_failure_preserves_pending_job(tmp_path):
    from self_agent.engine import Engine
    class Offline:
        configured=True
        def preflight(self):raise OSError('offline')
        def extract(self,*args):pytest.fail('generation before successful preflight')
    store=Store(tmp_path/'db');uid=Auth(store).create_user('u','long-safe-password')
    sid,_=store.source(uid,'p','title','content');store.enqueue(uid,sid)
    engine=Engine(Config(tmp_path),store,provider=Offline())
    assert engine.process_one() is False
    with store.tx() as db:
        job=db.execute('SELECT * FROM jobs').fetchone()
        assert job['state']=='pending' and job['attempts']==0 and job['next_at']>time.time()
    store.close()


def test_scoped_projection_ids():
    from self_agent.local_index import LocalIndex
    assert LocalIndex.scope('u','p')!=LocalIndex.scope('u','q')
    assert LocalIndex.scope('u','p')!=LocalIndex.scope('v','p')


def test_local_http_rejects_wrong_host_and_unauthenticated_stop(tmp_path):
    from self_agent.server import create_app
    from fastapi.testclient import TestClient
    app=create_app(Config(tmp_path,local=True,local_instance_id='fixture'),start_worker=False)
    with TestClient(app,base_url='http://127.0.0.1:8766') as client:
        assert client.get('/healthz').json()['local_instance_id']=='fixture'
        assert client.get('/healthz',headers={'host':'evil.example'}).status_code==403
        assert client.post('/api/local/stop',json={}).status_code==401


def test_uninstall_preserves_mixed_hook_handlers(tmp_path,monkeypatch):
    from self_agent import install
    monkeypatch.setattr(install,'private_root',lambda:tmp_path/'private')
    repo=Path(__file__).resolve().parents[1]
    install.install_client('codex',home=tmp_path,repo=repo)
    hook_file=tmp_path/'.codex/hooks.json';data=json.loads(hook_file.read_text())
    data['hooks']['Stop'][0]['hooks'].append({'type':'command','command':'other-tool'})
    hook_file.write_text(json.dumps(data))
    install.remove_client('codex',home=tmp_path,repo=repo)
    out=json.loads(hook_file.read_text())
    assert out['hooks']['Stop'][0]['hooks']==[{'type':'command','command':'other-tool'}]
    assert '[mcp_servers.self_agent]' not in (tmp_path/'.codex/config.toml').read_text()


def test_local_ui_ticket_is_one_use_and_no_secret_url(tmp_path):
    from self_agent.server import create_app
    from fastapi.testclient import TestClient
    from self_agent.auth import digest
    cfg=Config(tmp_path,local=True,local_instance_id='fixture')
    app=create_app(cfg,start_worker=False)
    cfg.local_user_id=app.state.auth.create_user('local','long-safe-password',True)
    ticket='private-launch-ticket'
    (tmp_path/'ui-ticket.json').write_text(json.dumps({'hash':digest(ticket),'expires':time.time()+60}))
    with TestClient(app,base_url='http://127.0.0.1:8766') as client:
        bad=client.post('/api/local/open',content='ticket=wrong',headers={'content-type':'application/x-www-form-urlencoded','origin':'null'},follow_redirects=False)
        assert bad.status_code==401
        good=client.post('/api/local/open',content='ticket='+ticket,headers={'content-type':'application/x-www-form-urlencoded','origin':'null'},follow_redirects=False)
        assert good.status_code==303 and good.headers['location']=='/'
        assert 'HttpOnly' in good.headers['set-cookie']
        assert client.get('/api/me').status_code==200
        assert client.post('/api/local/open',content='ticket='+ticket,headers={'content-type':'application/x-www-form-urlencoded'},follow_redirects=False).status_code==401


def test_fresh_setup_uses_existing_xjcode_without_prompt(tmp_path,monkeypatch):
    from self_agent import local_runtime,xjcode_auth
    home=tmp_path/'home';(home/'.codex').mkdir(parents=True)
    (home/'.xjcode').mkdir();(home/'.xjcode/credentials.dpapi').write_bytes(b'protected fixture')
    models=tmp_path/'models';models.mkdir();(models/'model.onnx').write_bytes(b'fixture');(models/'tokenizer.json').write_text('{}')
    monkeypatch.setattr(xjcode_auth,'discover',lambda *a,**k:{'workspace_id':'personal-fixture','model':'qwen3.8-max','account_fingerprint':'allowed'})
    monkeypatch.setattr(xjcode_auth,'login',lambda *a,**k:pytest.fail('unexpected interactive login'))
    monkeypatch.setattr(local_runtime,'private_root',lambda:tmp_path/'private')
    target=tmp_path/'connection.json';old={'url':'https://old.example','token_file':'unchanged'};target.write_text(json.dumps(old))
    result=local_runtime.setup_local('codex',home=home,data_dir=tmp_path/'data',model_cache=models,
                                     start=False,autostart=False,client_file=target)
    assert result['configured'] and result['hook_review_required']
    cfg=local_runtime.load_local(tmp_path/'data')
    assert cfg.xjtu_account_fingerprint=='allowed' and cfg.local
    assert json.loads((tmp_path/'data/previous-client.json').read_text())['value']==old
    assert 'protected fixture' not in (tmp_path/'data/server.json').read_text()


def test_health_proof_requires_private_token(tmp_path):
    import hmac
    from self_agent.server import create_app
    from fastapi.testclient import TestClient
    cfg=Config(tmp_path,local=True,local_instance_id='fixture')
    (tmp_path/'device.token').write_text('fixture-private-token')
    with TestClient(create_app(cfg,start_worker=False),base_url='http://127.0.0.1:8766') as client:
        data=client.get('/healthz',params={'challenge':'nonce'}).json()
        assert data['proof']==hmac.new(b'fixture-private-token',b'nonce',hashlib.sha256).hexdigest()
        assert 'fixture-private-token' not in json.dumps(data)


def test_reinstall_preserves_mixed_hook_handlers(tmp_path,monkeypatch):
    from self_agent import install
    monkeypatch.setattr(install,'private_root',lambda:tmp_path/'private')
    install.install_client('codex',home=tmp_path)
    file=tmp_path/'.codex/hooks.json';data=json.loads(file.read_text())
    data['hooks']['Stop'][0]['hooks'].append({'type':'command','command':'unrelated-check'})
    file.write_text(json.dumps(data));install.install_client('codex',home=tmp_path)
    handlers=[h for item in json.loads(file.read_text())['hooks']['Stop'] for h in item['hooks']]
    assert sum(h['command']=='unrelated-check' for h in handlers)==1
    assert len(handlers)==2


def test_project_detection_never_inherits_mcp_stdin(tmp_path,monkeypatch):
    from self_agent import hooks
    import subprocess
    seen={}
    class Result: returncode=0;stdout='https://github.com/example/project.git\n'
    def fake(*args,**kwargs):seen.update(kwargs);return Result()
    monkeypatch.setattr(hooks.subprocess,'run',fake)
    assert hooks.project_id(tmp_path)=='github.com/example/project'
    assert seen['stdin']==subprocess.DEVNULL


def test_shortcut_does_not_require_inherited_appdata(tmp_path,monkeypatch):
    client_module=pytest.importorskip('win32com.client')
    from self_agent.local_runtime import create_shortcut
    class Shortcut:
        def Save(self):self.saved=True
    shortcut=Shortcut()
    class Shell:
        def SpecialFolders(self,name):assert name=='Programs';return str(tmp_path)
        def CreateShortcut(self,path):assert path.endswith('Self Agent.lnk');return shortcut
    monkeypatch.delenv('APPDATA',raising=False)
    monkeypatch.setattr(client_module,'Dispatch',lambda name:Shell())
    create_shortcut({'python':str(tmp_path/'python.exe'),'source':str(tmp_path)})
    assert shortcut.saved
