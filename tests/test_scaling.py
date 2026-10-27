import asyncio,hashlib,json,sqlite3,threading,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from self_agent.auth import Auth
from self_agent.capacity import Capacity,Backpressure
from self_agent.config import Config
from self_agent.engine import Engine
from self_agent.server import create_app
from self_agent.store import Store,fingerprint
from self_agent.spool import capture,drain,atomic_json

@pytest.fixture
def database(tmp_path):
    store=Store(tmp_path/'memory.sqlite3');auth=Auth(store)
    uid=auth.create_user('owner','long-fixture-password');other=auth.create_user('other','another-fixture-password')
    yield store,uid,other
    store.close()

def seed(store,uid,n=1000,project='p'):
    now=time.time();rows=[];fts=[]
    for number in range(n):
        mid=uid+':'+str(number);text='sqlite memory storage item '+str(number)
        rows.append((mid,uid,project,'fact',text,text,None,'active',1,now+number/10000,now+number/10000,fingerprint(text)))
        fts.append((mid,text))
    with store.tx() as db:db.executemany('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',rows);db.executemany('INSERT INTO memory_fts VALUES(?,?)',fts)
    return rows

def test_candidates_fetch_a_bounded_pool_and_reject_foreign_ids(database):
    store,uid,other=database;rows=seed(store,uid)
    foreign=store.add(other,'p','sqlite secret storage item');different=store.add(uid,'other-project','sqlite storage elsewhere')
    count=0
    def counted(cursor,row):
        nonlocal count
        count+=1;return sqlite3.Row(cursor,row)
    store.db.row_factory=counted
    result=store.lifecycle.candidates(uid,'p',{'content':rows[0][5],'kind':'fact'},[foreign['id'],different['id']])
    assert result[0]['id']==rows[0][0] and len(result)<=8
    assert count<80  # Fails the prior Python full-table materialization.
    assert all(m['user_id']==uid and m['project']=='p' for m in result)
    assert not any('history' in m or 'evidence' in m for m in result)

def test_cross_kind_equivalence_keeps_one_canonical_memory(database):
    store,uid,_=database;old=store.add(uid,'','我偏好中文说明',kind='preference')
    messages=[{'id':'new','role':'user','content':'以后说明继续用中文','observed_at':time.time()}]
    sid,_=store.source(uid,'','new',json.dumps(messages,ensure_ascii=False),'conversation');source=dict(store.db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone())
    item={'content':'说明默认用中文','kind':'decision','scope':'personal','explicit':True,'evidence':'以后说明继续用中文'}
    result=store.lifecycle.apply(uid,source,item,{'relation':'equivalent','target_id':old['id'],'target_version':old['version']},[old])
    assert result['id']==old['id'] and result['kind']=='preference' and len(store.listing(uid))==1
    assert len(result['evidence'])==1

@pytest.mark.parametrize('kind',['foreign','other_project','removed','expired','stale','irrelevant'])
def test_recall_gate_rechecks_canonical_eligibility(database,kind):
    store,uid,other=database;cfg=Config(store.filename.parent)
    memory=store.add(other if kind=='foreign' else uid,'other' if kind=='other_project' else 'p','记忆文件保存在数据盘')
    version=memory['version']
    if kind=='removed':store.update(uid,memory['id'],status='forgotten')
    if kind=='expired':store.lifecycle.metadata(memory['id'],valid_until=time.time()-1)
    if kind=='stale':store.update(uid,memory['id'],content='早餐喜欢清淡食物')
    engine=Engine(cfg,store,provider=SimpleNamespace(configured=False))
    score=.1 if kind=='irrelevant' else .95
    engine.index=SimpleNamespace(search_hits=lambda *a:[{'id':memory['id'],'version':version,'score':.99,'semantic_score':score}])
    assert engine.search(uid,'跨设备同步方法','p')==[]

def test_strong_semantic_paraphrase_and_stopword_only_query(database):
    store,uid,_=database;memory=store.add(uid,'p','所有文件应留在本机的数据盘')
    engine=Engine(Config(store.filename.parent),store,provider=SimpleNamespace(configured=False))
    engine.index=SimpleNamespace(search_hits=lambda *a:[{'id':memory['id'],'version':memory['version'],'score':.8,'semantic_score':.85}])
    assert engine.search(uid,'持久化位置','p')[0]['id']==memory['id']
    assert engine.search(uid,'这个可以吗','p')==[]

def test_low_disk_keeps_cursor_and_resumes_capture(tmp_path,monkeypatch):
    import self_agent.capacity as capacity
    from self_agent import hooks
    row={'id':'u','role':'user','content':'默认使用简单界面','observed_at':time.time()}
    monkeypatch.setattr(hooks,'normalized_messages',lambda *a:[row]);real=capacity.shutil.disk_usage
    monkeypatch.setattr(capacity.shutil,'disk_usage',lambda *a:SimpleNamespace(free=0))
    config={'local_data_dir':str(tmp_path),'local_started_at':0};event={'transcript_path':str(tmp_path/'fixture')}
    with pytest.raises(Backpressure,match='disk_low'):capture(config,'codex',event,'p')
    assert not list((tmp_path/'cursors').glob('*.json')) and not list((tmp_path/'inbox').glob('*.json'))
    monkeypatch.setattr(capacity.shutil,'disk_usage',real);capture(config,'codex',event,'p')
    assert json.loads(next((tmp_path/'cursors').glob('*.json')).read_text())['count']==1
    assert len(list((tmp_path/'inbox').glob('*.json')))==1

def test_full_capture_queue_does_not_advance_cursor(tmp_path,monkeypatch):
    from self_agent import hooks
    atomic_json(tmp_path/'server.json',{'max_capture_batches':1});atomic_json(tmp_path/'inbox/occupied.json',{'fixture':True})
    monkeypatch.setattr(hooks,'normalized_messages',lambda *a:[{'id':'u','role':'user','content':'保留来源','observed_at':time.time()}])
    config={'local_data_dir':str(tmp_path),'local_started_at':0};event={'transcript_path':str(tmp_path/'fixture')}
    with pytest.raises(Backpressure,match='capture_queue_full'):capture(config,'codex',event,'p')
    assert not list((tmp_path/'cursors').glob('*.json'))
    (tmp_path/'inbox/occupied.json').unlink();Capacity.for_root(tmp_path).status();capture(config,'codex',event,'p')
    assert len(list((tmp_path/'inbox').glob('*.json')))==1

def test_processing_backpressure_preserves_batch_and_recovers(database):
    store,uid,_=database;root=store.filename.parent;cfg=Config(root,local=True,local_user_id=uid,max_pending_jobs=1)
    sid,_=store.source(uid,'p','old','old');old=store.enqueue(uid,sid)
    messages=[{'id':'u','role':'user','content':'新的明确要求','observed_at':time.time()}]
    atomic_json(root/'inbox/new.json',{'external_id':'new','project':'p','client':'codex','messages':messages})
    drain(cfg,store);assert (root/'inbox/new.json').exists()
    assert store.db.execute('select count(*) from sources').fetchone()[0]==1
    with store.tx() as db:db.execute("UPDATE jobs SET state='done' WHERE id=?",(old,))
    Capacity(cfg).status();drain(cfg,store);assert not (root/'inbox/new.json').exists()
    assert store.db.execute('select count(*) from jobs').fetchone()[0]==2

def test_already_committed_batch_can_drain_even_under_storage_pressure(database):
    store,uid,_=database;root=store.filename.parent;messages=[{'id':'u','role':'user','content':'已提交的要求','observed_at':time.time()}]
    text=json.dumps(messages,ensure_ascii=False);sid,_=store.source(uid,'p','old',text,'conversation','same');jid=store.enqueue(uid,sid)
    with store.tx() as db:db.execute("UPDATE jobs SET state='done' WHERE id=?",(jid,))
    atomic_json(root/'inbox/replay.json',{'external_id':'same','project':'p','client':'codex','messages':messages})
    drain(Config(root,local=True,local_user_id=uid,max_data_bytes=1),store)
    assert not (root/'inbox/replay.json').exists() and store.db.execute('select count(*) from jobs').fetchone()[0]==1

def test_api_queue_limit_rejects_before_creating_another_source(tmp_path):
    app=create_app(Config(tmp_path,max_pending_jobs=1),start_worker=False);uid=app.state.auth.create_user('owner','long-password-owner')
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+app.state.auth.issue_key(uid,'test')
        assert client.post('/v1/sources',json={'content':'first'}).status_code==202
        assert client.post('/v1/sources',json={'content':'second'}).status_code==429
        assert app.state.store.db.execute('select count(*) from sources').fetchone()[0]==1

def test_safe_index_deferral_reuses_completed_extraction(database):
    store,uid,_=database;sid,_=store.source(uid,'p','new',json.dumps([{'role':'user','content':'使用中文说明'}]),'conversation');store.enqueue(uid,sid)
    class Provider:
        configured=True;calls=0
        def extract(self,text):self.calls+=1;return [{'content':'使用中文说明','kind':'preference','scope':'project','explicit':True,'evidence':'使用中文说明'}]
        def reconcile(self,item,candidates):return {'relation':'independent'}
    provider=Provider();cfg=Config(store.filename.parent,semantic=True,index_backend='mcp-memory-service');engine=Engine(cfg,store,provider)
    class Index:
        ready_for_reconcile=True;fail=True
        def candidate_ids(self,*a):
            if self.fail:raise OSError('temporarily busy')
            return []
        def search_ids(self,*a):return []
    engine.index=Index();assert engine.process_one()
    assert store.db.execute('select state from jobs').fetchone()[0]=='pending' and provider.calls==1
    engine.index.fail=False
    with store.tx() as db:db.execute('update jobs set next_at=0')
    assert engine.process_one() and provider.calls==1
    assert store.db.execute('select state from jobs').fetchone()[0]=='done'

def test_unknown_paid_failure_is_not_automatically_replayed(database):
    store,uid,_=database;sid,_=store.source(uid,'p','new','fixture');store.enqueue(uid,sid)
    class Provider:
        configured=True;calls=0
        def extract(self,text):self.calls+=1;raise OSError('unknown response')
    provider=Provider();engine=Engine(Config(store.filename.parent),store,provider)
    assert engine.process_one();assert not engine.process_one();assert provider.calls==1
    assert store.db.execute('select state from jobs').fetchone()[0]=='uncertain'

def test_mature_scheduler_keeps_capture_and_index_responsive_during_slow_generation(database):
    store,uid,_=database;root=store.filename.parent;started=threading.Event();release=threading.Event();indexed=threading.Event()
    class Provider:
        configured=True;calls=0
        def extract(self,text):self.calls+=1;started.set();release.wait(5);return []
    provider=Provider();sid,_=store.source(uid,'p','initial','first');store.enqueue(uid,sid)
    engine=Engine(Config(root,local=True,local_user_id=uid),store,provider)
    class Index:
        ready_for_reconcile=True;error='';memory=True
        def sync(self):indexed.set()
    engine.index=Index();engine.start()
    try:
        assert started.wait(2);indexed.clear()
        atomic_json(root/'inbox/second.json',{'external_id':'second','project':'p','client':'codex','messages':[{'id':'u','role':'user','content':'second','observed_at':time.time()}]})
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            with store.tx() as db:count=db.execute('select count(*) from sources').fetchone()[0]
            if count==2:break
            time.sleep(.02)
        assert count==2 and indexed.wait(2) and provider.calls==1
    finally:release.set();engine.close()


def test_reranker_rejects_high_vector_similarity_and_rechecks_concurrent_remove(database):
    store,uid,_=database;memory=store.add(uid,'p','数据盘存储所有知识库文件')
    engine=Engine(Config(store.filename.parent,semantic=True),store,provider=SimpleNamespace(configured=False))
    class Index:
        def search_hits(self,*a):return [{'id':memory['id'],'version':1,'score':.99,'semantic_score':.99}]
        def rerank(self,query,pool):return [{'id':memory['id'],'score':.001}]
    engine.index=Index();assert engine.search(uid,'明天天气怎么样','p')==[]
    def remove_during_rerank(query,pool):
        store.update(uid,memory['id'],status='forgotten');return [{'id':memory['id'],'score':.99}]
    engine.index.rerank=remove_during_rerank
    assert engine.search(uid,'知识库文件存储在哪里','p')==[]

def test_unavailable_reranker_keeps_literal_search_without_vector_noise(database):
    store,uid,_=database;memory=store.add(uid,'p','工程数据保留在 D 盘')
    engine=Engine(Config(store.filename.parent,semantic=True),store,provider=SimpleNamespace(configured=False))
    engine.index=SimpleNamespace(search_hits=lambda *a:[{'id':memory['id'],'version':1,'score':.99,'semantic_score':.99}],rerank=lambda *a:None)
    assert engine.search(uid,'天气预报','p')==[]
    assert engine.search(uid,'工程数据保留在 D 盘','p')[0]['id']==memory['id']

def test_queue_state_read_failure_closes_ingestion(tmp_path):
    (tmp_path/'memory.sqlite3').write_bytes(b'broken database')
    with pytest.raises(Backpressure,match='queue_unavailable'):Capacity(Config(tmp_path)).check()


def test_startup_context_needs_no_model_and_respects_scope_lifecycle_and_overrides(database):
    store,uid,other=database
    personal=store.add(uid,'','默认说明使用中文',kind='preference');project=store.add(uid,'p','当前项目说明用英文',kind='decision')
    store.add(other,'p','外国用户的偏好',kind='preference');store.add(uid,'other','其他项目的决策',kind='decision')
    removed=store.add(uid,'p','移出的默认值',kind='preference');store.update(uid,removed['id'],status='forgotten')
    expired=store.add(uid,'p','到期的默认值',kind='procedure');store.lifecycle.metadata(expired['id'],valid_until=time.time()-1)
    seed(store,uid,100)
    with store.tx() as db:
        store.lifecycle.metadata(personal['id'],topic='language');store.lifecycle.metadata(project['id'],topic='language')
    engine=Engine(Config(store.filename.parent),store,provider=SimpleNamespace(configured=False))
    engine.index=SimpleNamespace()
    result=engine.context(uid,'p');assert [m['id'] for m in result]==[project['id']]
    assert len(engine.context(uid,'other',limit=1))==1

def test_session_start_uses_confirmed_context_without_a_fabricated_query(monkeypatch):
    from self_agent import hooks
    calls=[];monkeypatch.setattr(hooks,'project_id',lambda *a:'p')
    def request(method,path,**kwargs):
        calls.append((path,kwargs.get('params')));return {'items':[{'id':'fixture','content':'默认用中文说明'}]}
    monkeypatch.setattr(hooks,'request',request)
    result=hooks.handle('codex',{'hook_event_name':'SessionStart'})
    assert calls==[('/v1/context',{'project':'p','limit':8})]
    assert '默认用中文说明' in result['hookSpecificOutput']['additionalContext']
