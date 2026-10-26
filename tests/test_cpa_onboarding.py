import hashlib
import io
import json
from pathlib import Path
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from self_agent.config import Config
from self_agent.server import create_app

CPA_A='cpa-person-a-key-very-long-and-random'
CPA_B='cpa-person-b-key-very-long-and-random'


@pytest.fixture
def cpa_service(tmp_path):
    keys=tmp_path/'cpa.yaml';permissions=tmp_path/'permissions.json'
    keys.write_text(json.dumps({'api-keys':[CPA_A,CPA_B]}),'utf-8')
    permissions.write_text(json.dumps({'schema_version':1,'revision':1,'entries':{}}),'utf-8')
    app=create_app(Config(tmp_path/'state',secure_cookie=True,cpa_config_file=str(keys),cpa_permissions_file=str(permissions)),start_worker=False)
    uid=app.state.auth.create_user('admin','long-local-password',True)
    admin_key=app.state.auth.issue_key(uid,'existing-admin')
    with TestClient(app,base_url='https://memory.example.com') as client:
        yield client,app,keys,permissions,admin_key,uid


def bearer(token):return {'Authorization':'Bearer '+token}


def test_same_cpa_key_same_space_and_other_keys_isolated(cpa_service):
    c,app,keys,permissions,admin_key,uid=cpa_service
    assert c.get('/api/auth/options').json()['cpa']
    assert c.post('/api/login/key',json={'token':'not-a-valid-cpa-key'}).status_code==401
    assert c.post('/api/login/key',json={'token':CPA_A}).status_code==200
    first=c.get('/api/me').json()
    assert first['admin'] is False and first['id']!=uid
    memory=c.post('/v1/memories',json={'content':'A private project decision'}).json()
    c.cookies.clear()
    assert c.get('/api/me',headers=bearer(CPA_A)).json()['id']==first['id']
    second=c.get('/api/me',headers=bearer(CPA_B)).json()
    assert first['id']!=second['id']
    assert c.get('/v1/memories/'+memory['id'],headers=bearer(CPA_B)).status_code==404
    assert c.get('/v1/export',headers=bearer(CPA_B)).json()['memories']==[]
    export=json.dumps(c.get('/v1/export',headers=bearer(CPA_A)).json())
    assert CPA_A not in export and 'external_identities' not in export and 'pairing_codes' not in export
    for row in app.state.store.db.iterdump():
        assert CPA_A not in row and CPA_B not in row


def test_disable_cpa_revokes_cookie_and_derived_device_key(cpa_service):
    c,app,keys,permissions,*_=cpa_service
    assert c.post('/api/login/key',json={'token':CPA_A}).status_code==200
    code=c.post('/api/pairing',json={'name':'office'}).json()['code']
    device=c.post('/api/pairing/redeem',json={'code':code}).json()['token']
    assert c.get('/api/me',headers=bearer(device)).status_code==200
    permissions.write_text(json.dumps({'schema_version':1,'entries':{hashlib.sha256(CPA_A.encode()).hexdigest():{'enabled':False,'models':None,'concurrency':0}}}),'utf-8')
    assert c.get('/api/me').status_code==401
    assert c.get('/api/me',headers=bearer(device)).status_code==401
    assert c.get('/api/me',headers=bearer(CPA_A)).status_code==401
    assert c.post('/api/login/key',json={'token':CPA_A}).status_code==401


def test_removal_and_registry_failure_fail_closed(cpa_service):
    c,app,keys,permissions,admin_key,uid=cpa_service
    assert c.post('/api/login/key',json={'token':CPA_A}).status_code==200
    keys.write_text(json.dumps({'api-keys':[CPA_B]}),'utf-8')
    assert c.get('/api/me').status_code==401
    keys.unlink()
    assert c.get('/api/me',headers=bearer(CPA_B)).status_code==503
    # Independent local administrator recovery remains available.
    assert c.get('/api/me',headers=bearer(admin_key)).status_code==200


def test_link_existing_space_does_not_grant_cpa_admin(cpa_service):
    c,app,keys,permissions,admin_key,uid=cpa_service
    assert c.post('/api/cpa/link',json={'token':CPA_A},headers=bearer(admin_key)).status_code==200
    user=c.get('/api/me',headers=bearer(CPA_A)).json()
    assert user['id']==uid and user['admin'] is False
    assert c.post('/api/users',json={'username':'escalated','password':'long-password-escalated','admin':True},headers=bearer(CPA_A)).status_code==403
    other=c.get('/api/me',headers=bearer(CPA_B)).json()['id']
    assert other!=uid
    assert c.post('/v1/memories',json={'content':'B already has private data'},headers=bearer(CPA_B)).status_code==201
    assert c.post('/api/cpa/link',json={'token':CPA_B},headers=bearer(admin_key)).status_code==400
    assert c.get('/api/me',headers=bearer(CPA_B)).json()['id']==other


def test_pairing_is_one_use_expires_and_cannot_impersonate(cpa_service):
    c,app,keys,permissions,admin_key,uid=cpa_service
    assert c.post('/api/pairing',json={'name':'anonymous'}).status_code==401
    code=c.post('/api/pairing',json={'name':'laptop'},headers=bearer(CPA_A)).json()['code']
    one=c.post('/api/pairing/redeem',json={'code':code})
    assert one.status_code==200
    assert c.post('/api/pairing/redeem',json={'code':code}).status_code==401
    assert c.get('/api/me',headers=bearer(one.json()['token'])).json()['id']==c.get('/api/me',headers=bearer(CPA_A)).json()['id']
    code=c.post('/api/pairing',json={'name':'expired'},headers=bearer(CPA_A)).json()['code']
    with app.state.store.tx() as db:db.execute('UPDATE pairing_codes SET expires=?',(time.time()-1,))
    assert c.post('/api/pairing/redeem',json={'code':code}).status_code==401


def test_local_key_login_session_is_revoked_with_key(cpa_service):
    c,app,keys,permissions,admin_key,uid=cpa_service
    assert c.post('/api/login/key',json={'token':admin_key}).status_code==200
    with app.state.store.tx() as db:db.execute('DELETE FROM api_keys WHERE hash=?',(hashlib.sha256(admin_key.encode()).hexdigest(),))
    assert c.get('/api/me').status_code==401


def test_download_installer_has_only_short_lived_pairing_secret(cpa_service):
    c,app,keys,permissions,admin_key,uid=cpa_service
    assert c.post('/api/pairing/installer',json={'client':'codex'},headers=bearer(CPA_A)).status_code==200
    r=c.post('/api/pairing/installer',json={'client':'both','name':'my laptop'},headers=bearer(CPA_A))
    assert r.headers['cache-control']=='no-store'
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        assert set(archive.namelist())=={'install.ps1','start.cmd','README.txt'}
        script=archive.read('install.ps1').decode('utf-8-sig')
        assert "[string]$Client = 'both'" in script
        assert "[string]$ServiceUrl = 'https://memory.example.com'" in script
        assert CPA_A not in script and admin_key not in script
        assert '--pair-code-stdin' in script
        assert b'ExecutionPolicy' in archive.read('start.cmd')
    assert c.post('/api/pairing/installer',json={'client':'arbitrary'},headers=bearer(CPA_A)).status_code==422


def test_empty_auto_created_space_can_link_without_losing_devices(cpa_service):
    c,app,keys,permissions,admin_key,uid=cpa_service
    assert c.post('/api/login/key',json={'token':CPA_A}).status_code==200
    code=c.post('/api/pairing',json={'name':'first device'}).json()['code']
    device=c.post('/api/pairing/redeem',json={'code':code}).json()['token']
    assert c.post('/api/cpa/link',json={'token':CPA_A},headers=bearer(admin_key)).status_code==200
    assert c.get('/api/me').json()['id']==uid
    linked=c.get('/api/me',headers=bearer(device)).json()
    assert linked['id']==uid and linked['admin'] is False


def test_setup_migrates_only_verified_owned_runner(tmp_path,monkeypatch):
    from self_agent.install import install_client
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'private'))
    repo=Path(__file__).resolve().parents[1]
    old=tmp_path/'old-client/scripts';old.mkdir(parents=True)
    for name in ['hook_runner.py','mcp_runner.py']:
        (old/name).write_bytes((repo/'scripts'/name).read_bytes())
    home=tmp_path/'home';(home/'.claude').mkdir(parents=True)
    command=json.dumps('old-python')+' '+json.dumps(str(old/'hook_runner.py'))+' claude'
    (home/'.claude.json').write_text(json.dumps({'mcpServers':{'self_agent':{'command':'old-python','args':[str(old/'mcp_runner.py')]},'other':{'command':'keep'}}}),'utf-8')
    (home/'.claude/settings.json').write_text(json.dumps({'hooks':{'Stop':[{'hooks':[{'type':'command','command':command}]},{'hooks':[{'type':'command','command':'keep-this-hook'}]}]}}),'utf-8')
    install_client('claude',home=home)
    config=json.loads((home/'.claude.json').read_text('utf-8'))
    hooks=json.loads((home/'.claude/settings.json').read_text('utf-8'))['hooks']['Stop']
    assert config['mcpServers']['other']['command']=='keep'
    assert config['mcpServers']['self_agent']['args']==[str(repo/'scripts/mcp_runner.py')]
    assert len(hooks)==2
    assert any(h['hooks'][0]['command']=='keep-this-hook' for h in hooks)
