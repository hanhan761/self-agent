import json,time
import pytest
from fastapi.testclient import TestClient
from self_agent.config import Config
from self_agent.provider import XjtuProvider
from self_agent.xjtu_top import ModelRoute,TopError

def fixture_provider(tmp_path,monkeypatch):
    import self_agent.provider as module
    from self_agent import xjcode_auth
    monkeypatch.setattr(xjcode_auth,'credentials',lambda cfg:object())
    clock=[100.0];monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    class Client:
        catalogs=0;completions=0;granted=True
        def __init__(self,*args,**kwargs):pass
        def list_text_models(self):
            Client.catalogs+=1
            return {'qwen3.7-max':ModelRoute('qwen3.7-max','service','route','external')} if Client.granted else {}
        def complete(self,*args,**kwargs):
            Client.completions+=1
            return 'complete'
    monkeypatch.setattr(module,'TopClient',Client)
    return XjtuProvider(Config(tmp_path,xjcode_home=str(tmp_path),xjtu_model='qwen3.7-max')),Client,clock

def test_permission_revocation_expires_cached_route(tmp_path,monkeypatch):
    p,c,clock=fixture_provider(tmp_path,monkeypatch)
    p.complete([]);p.preflight()
    assert c.catalogs==1 and c.completions==1
    clock[0]+=61;c.granted=False
    with pytest.raises(RuntimeError,match='model_not_granted'):p.complete([])
    assert c.completions==1
    assert p.health['reason']=='model_not_granted'
    for _ in range(10):
        with pytest.raises(RuntimeError):p.preflight()
    assert c.catalogs==2
    clock[0]+=31;c.granted=True;p.complete([])
    assert c.catalogs==3 and c.completions==2 and p.health['state']=='ready'

def test_generation_error_invalidates_route(tmp_path,monkeypatch):
    p,c,clock=fixture_provider(tmp_path,monkeypatch)
    p.preflight()
    def reject(*args,**kwargs):raise TopError('private upstream text',action='CreateConversation',http_status=403)
    monkeypatch.setattr(c,'complete',reject)
    with pytest.raises(TopError):p.complete([])
    assert p.health['reason']=='provider_request_failed'
    c.granted=False
    with pytest.raises(RuntimeError,match='model_not_granted'):p.preflight()
    assert c.catalogs==2
    assert 'private' not in json.dumps(p.health)

def test_permission_failure_keeps_task_unattempted(tmp_path,monkeypatch):
    from self_agent.store import Store
    from self_agent.auth import Auth
    from self_agent.engine import Engine
    p,c,clock=fixture_provider(tmp_path,monkeypatch);c.granted=False
    store=Store(tmp_path/'db');uid=Auth(store).create_user('local','long-safe-password')
    sid,_=store.source(uid,'project','title','source');store.enqueue(uid,sid)
    engine=Engine(Config(tmp_path),store,provider=p)
    assert engine.process_one() is False
    row=store.db.execute('select * from jobs').fetchone()
    assert row['state']=='pending' and row['attempts']==0 and row['error']=='model_not_granted'
    assert c.completions==0
    store.close()

def test_overview_reports_all_failed_jobs_only_for_owner(tmp_path):
    from self_agent.server import create_app
    app=create_app(Config(tmp_path),start_worker=False)
    uid=app.state.auth.create_user('owner','long-safe-password')
    other=app.state.auth.create_user('other','long-safe-password')
    for i in range(35):
        sid,_=app.state.store.source(uid,'p',str(i),'source'+str(i));jid=app.state.store.enqueue(uid,sid)
        app.state.store.db.execute("update jobs set state='uncertain' where id=?",(jid,))
    sid,_=app.state.store.source(other,'p','foreign','private');app.state.store.enqueue(other,sid)
    class Provider:
        configured=True
        health={'state':'blocked','reason':'model_not_granted','checked_at':1}
    app.state.engine.provider=Provider()
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+app.state.auth.issue_key(uid,'test')
        data=client.get('/api/overview').json()
        assert data['job_counts']=={'uncertain':35}
        assert len(data['jobs'])==30
        assert data['provider']['health']['reason']=='model_not_granted'

def test_overview_keeps_old_failures_visible_after_new_successes(tmp_path):
    from self_agent.store import Store
    from self_agent.auth import Auth
    store=Store(tmp_path/'db');uid=Auth(store).create_user('owner','long-safe-password')
    sid,_=store.source(uid,'p','failed','old unresolved source');jid=store.enqueue(uid,sid)
    store.db.execute("update jobs set state='uncertain',created=1 where id=?",(jid,))
    for i in range(35):
        sid,_=store.source(uid,'p','new',str(i));done=store.enqueue(uid,sid)
        store.db.execute("update jobs set state='done' where id=?",(done,))
    data=store.overview(uid)
    assert data['jobs'][0]['id']==jid
    assert data['job_counts']['uncertain']==1
    store.close()
