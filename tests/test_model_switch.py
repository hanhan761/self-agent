import json,time,http.client
from types import SimpleNamespace
import pytest
from self_agent.config import Config
from self_agent.provider import XjtuProvider,ProviderUnavailable
from self_agent.xjtu_top import TopError,ModelRoute

@pytest.fixture
def routing(tmp_path,monkeypatch):
    from self_agent import provider,xjcode_auth
    clock=[time.time()]
    monkeypatch.setattr(provider.time,'time',lambda:clock[0])
    monkeypatch.setattr(provider.time,'monotonic',lambda:clock[0])
    identity=SimpleNamespace(account_id='fixture-account',workspace_id='fixture-workspace')
    monkeypatch.setattr(xjcode_auth,'credentials',lambda cfg:identity)
    class Client:
        catalogs=0;calls=[];granted={'primary','backup','extra','unapproved'};errors={};responses={}
        def __init__(self,*a,**kw):pass
        def list_text_models(self):
            Client.catalogs+=1
            return {n:ModelRoute(n,n,n,'external') for n in Client.granted}
        def complete(self,prompt,*,model):
            assert model and model.public_id in ('primary','backup','extra')
            Client.calls.append(model.public_id)
            if Client.errors.get(model.public_id):raise Client.errors[model.public_id]
            return Client.responses.get(model.public_id,'{"memories":[]}')
    monkeypatch.setattr(provider,'TopClient',Client)
    cfg=Config(tmp_path,xjcode_home=str(tmp_path),xjtu_model='primary',xjtu_auto_switch=True,xjtu_backup_models=('backup','extra'))
    return XjtuProvider(cfg),Client,clock,identity

def test_missing_grant_selects_explicit_backup_without_paid_probe(routing):
    p,c,clock,_=routing;c.granted.remove('primary')
    p.preflight()
    assert p.health['state']=='fallback' and p.health['active_model']=='backup'
    assert not c.calls and not p.health['models'][1]['last_success']
    p.complete([]);assert c.calls==['backup']
    assert 'fixture-account' not in json.dumps(p.health)

def test_prechat_failure_fails_over_and_primary_recovers_after_cooldown(routing):
    p,c,clock,_=routing
    c.errors['primary']=TopError('hidden',action='CreateConversation',http_status=503)
    p.complete([])
    assert c.calls==['primary','backup']
    assert p.health['switches'][-1]['to']=='backup'
    assert p.pool.models['primary']['until']>clock[0]
    p.complete([]);assert c.calls[-1]=='backup'
    clock[0]+=61;c.errors={}
    p.complete([]);assert c.calls[-1]=='primary'
    assert p.health['switches'][-1]['reason']=='preferred_recovered'

def test_uncertain_chat_is_not_replayed_but_next_request_switches(routing):
    p,c,_,_=routing;c.errors['primary']=TopError('partial reply',action='Chat')
    with pytest.raises(TopError):p.complete([])
    assert c.calls==['primary']
    p.complete([])
    assert c.calls==['primary','backup']

def test_account_denial_blocks_all_models(routing):
    p,c,clock,_=routing;c.errors['primary']=TopError('hidden',action='CreateConversation',http_status=403)
    with pytest.raises(TopError):p.complete([])
    with pytest.raises(ProviderUnavailable,match='account_unavailable'):p.preflight()
    assert c.calls==['primary']

def test_cooldown_and_switch_history_survive_restart_and_respect_scope(routing):
    p,c,_,identity=routing;c.errors['primary']=TopError('hidden',action='BatchCreateMessages',http_status=503)
    p.complete([])
    other=XjtuProvider(p.config);other.preflight()
    assert other.health['active_model']=='backup'
    assert other.health['switches'][-1]['from']=='primary'
    identity.account_id='different-fixture-account'
    fresh=XjtuProvider(p.config);fresh.preflight()
    assert fresh.health['active_model']=='primary'
    assert not fresh.health['switches']

def test_idle_check_refreshes_grants_without_generation(routing):
    p,c,clock,_=routing
    p.check_health();assert c.catalogs==1 and not c.calls
    p.check_health();assert c.catalogs==1
    clock[0]+=61;c.granted.remove('primary')
    p.check_health();assert p.health['active_model']=='backup' and not c.calls

def test_explicit_rate_denial_switches_and_honors_retry_after(routing):
    p,c,clock,_=routing
    c.errors['primary']=TopError('rate',action='Chat',http_status=429,rate_receipt={'limited':True,'retry_after_seconds':600})
    p.complete([])
    assert c.calls==['primary','backup']
    assert p.pool.models['primary']['until']>=clock[0]+600

def engine_job(p):
    from self_agent.store import Store
    from self_agent.auth import Auth
    from self_agent.engine import Engine
    store=Store(p.config.data_dir/'test.sqlite3');uid=Auth(store).create_user('local','long-safe-password')
    text=json.dumps([{'role':'user','content':'我喜欢中文说明'}],ensure_ascii=False)
    sid,_=store.source(uid,'p','title',text);jid=store.enqueue(uid,sid)
    return Engine(p.config,store,p),store,uid,jid

def test_all_models_unavailable_keep_source_pending_with_bounded_calls(routing):
    p,c,clock,_=routing
    c.errors={n:TopError('offline',action='CreateConversation',http_status=503) for n in p.pool.names}
    engine,store,uid,jid=engine_job(p)
    assert engine.process_one()
    row=store.db.execute('select state,attempts from jobs where id=?',(jid,)).fetchone()
    assert tuple(row)==('pending',1) and c.calls==['primary','backup','extra']
    assert not store.listing(uid)
    clock[0]+=31
    assert not engine.process_one() and len(c.calls)==3
    store.close()

def test_bad_complete_output_retries_once_on_backup_then_saves(routing):
    p,c,clock,_=routing;c.responses['primary']='invalid completed output'
    c.responses['backup']=json.dumps({'memories':[{'content':'我喜欢中文说明','kind':'preference','evidence':'我喜欢中文说明','explicit':True,'scope':'personal'}]},ensure_ascii=False)
    engine,store,uid,jid=engine_job(p)
    engine.process_one()
    assert store.db.execute('select state from jobs where id=?',(jid,)).fetchone()[0]=='pending'
    assert not store.listing(uid)
    clock[0]+=2;engine.process_one()
    assert store.db.execute('select state from jobs where id=?',(jid,)).fetchone()[0]=='done'
    assert c.calls==['primary','primary','backup']
    assert len(store.listing(uid))==1
    store.close()

def test_invalid_outputs_do_not_retry_forever_or_enter_memory(routing):
    p,c,clock,_=routing;c.responses={n:'invalid completed output' for n in p.pool.names}
    engine,store,uid,jid=engine_job(p)
    engine.process_one();clock[0]+=2;engine.process_one()
    assert store.db.execute('select state from jobs where id=?',(jid,)).fetchone()[0]=='failed'
    assert c.calls==['primary','primary','backup','backup'] and not store.listing(uid)
    store.close()

def test_uncertain_job_stays_uncertain(routing):
    p,c,_,_=routing;c.errors['primary']=TopError('stream interrupted',action='Chat')
    engine,store,uid,jid=engine_job(p);engine.process_one()
    assert store.db.execute('select state from jobs where id=?',(jid,)).fetchone()[0]=='uncertain'
    assert c.calls==['primary'] and not store.listing(uid)
    store.close()

def test_disabled_policy_never_changes_selected_model(routing):
    p,c,_,_=routing;p.config.xjtu_auto_switch=False
    disabled=XjtuProvider(p.config);c.granted.remove('primary')
    with pytest.raises(ProviderUnavailable,match='model_not_granted'):disabled.preflight()
    assert not c.calls

def test_prechat_account_failure_waits_without_uncertain_replay(routing):
    p,c,clock,_=routing;c.errors['primary']=TopError('account denied',action='CreateConversation',http_status=403)
    engine,store,uid,jid=engine_job(p);engine.process_one()
    assert store.db.execute('select state from jobs where id=?',(jid,)).fetchone()[0]=='pending'
    clock[0]+=31;assert not engine.process_one()
    assert c.calls==['primary']
    store.close()

def test_long_retry_after_survives_restart(routing):
    p,c,clock,_=routing
    c.errors['primary']=TopError('rate',action='Chat',http_status=429,rate_receipt={'limited':True,'retry_after_seconds':172800})
    p.complete([])
    restored=XjtuProvider(p.config);restored.preflight()
    assert restored.pool.models['primary']['until']>=clock[0]+172800
    assert restored.health['active_model']=='backup'

def test_install_discovery_accepts_only_explicit_authorized_backups(tmp_path,monkeypatch):
    from self_agent import xjcode_auth,xjtu_top
    monkeypatch.setattr(xjcode_auth,'identity',lambda home:{'access_key':'fixture','secret':'fixture','account_id':'fixture'})
    class Catalog:
        def __init__(self,*a,**k):pass
        def list_text_models(self):return {'backup':object(),'unapproved':object()}
    monkeypatch.setattr(xjtu_top,'TopClient',Catalog)
    with pytest.raises(RuntimeError,match='requested_model_not_granted'):xjcode_auth.discover(tmp_path,model='primary')
    assert xjcode_auth.discover(tmp_path,model='primary',backup_models=('backup',))['model']=='backup'

def test_idle_worker_pauses_generation_and_cleanup_when_pool_has_no_grants(routing):
    p,c,clock,_=routing;c.granted={'unapproved'}
    engine,store,uid,jid=engine_job(p)
    engine.process_cleanup_one=lambda:pytest.fail('maintenance claimed while model pool blocked')
    engine._generation_tick();engine._generation_tick()
    assert c.catalogs==1 and not c.calls
    row=store.db.execute('select state,attempts from jobs where id=?',(jid,)).fetchone()
    assert tuple(row)==('pending',0)
    assert p.health['reason']=='model_not_granted'
    store.close()

@pytest.mark.parametrize('changes',[{'xjtu_auto_switch':'false'},{'xjtu_backup_models':'backup'},{'xjtu_backup_models':('bad model name',)},{'xjtu_backup_models':('a','b','c','d','e')}])
def test_invalid_model_pools_fail_closed(tmp_path,changes):
    cfg=Config(tmp_path,xjtu_auto_switch=True,**{k:v for k,v in changes.items() if k!='xjtu_auto_switch'})
    if 'xjtu_auto_switch' in changes:cfg.xjtu_auto_switch=changes['xjtu_auto_switch']
    with pytest.raises(ValueError,match='invalid_native_model_pool'):XjtuProvider(cfg)

@pytest.mark.parametrize('error',[TimeoutError('private socket text'),http.client.IncompleteRead(b'private partial')])
def test_real_stream_reader_normalizes_transport_failure(error):
    from self_agent.xjtu_top import TopClient,Credentials
    class Broken:
        def readline(self,*a):raise error
    c=TopClient(Credentials('fixture','fixture','account','workspace','service'),url='http://127.0.0.1')
    with pytest.raises(TopError) as exc:list(c.iter_chat(Broken(),'conversation'))
    assert exc.value.action=='Chat' and 'private' not in str(exc.value)

def test_prepare_response_read_timeout_is_safe_prechat_failure(monkeypatch):
    from self_agent.xjtu_top import TopClient,Credentials
    class Broken:
        status=200
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,*a):raise TimeoutError('private socket text')
    c=TopClient(Credentials('fixture','fixture','account','workspace','service'),url='http://127.0.0.1')
    monkeypatch.setattr(c,'_request',lambda *a:Broken())
    with pytest.raises(TopError) as exc:c.call('CreateConversation',{})
    assert exc.value.action=='CreateConversation' and 'private' not in str(exc.value)
