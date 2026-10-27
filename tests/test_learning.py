import json,time
import pytest
from fastapi.testclient import TestClient
from self_agent.config import Config
from self_agent.server import create_app

@pytest.fixture
def service(tmp_path):
    app=create_app(Config(tmp_path),start_worker=False)
    uid=app.state.auth.create_user('learner','long-enough-password')
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+app.state.auth.issue_key(uid,'test')
        yield c,app,uid

class Provider:
    configured=True
    def __init__(self,item,relation='independent',target=None):self.item=item;self.relation=relation;self.target=target
    def extract(self,text):return [self.item]
    def reconcile(self,item,candidates):
        old=next((m for m in candidates if m['id']==self.target),None)
        return {'relation':self.relation,'target_id':old['id'] if old else None,'target_version':old['version'] if old else None}

def learn(c,app,content,scope='personal',relation='independent',target=None,observed_at=None,**extra):
    item={'content':content,'kind':'preference','explicit':True,'evidence':content,'scope':scope,**extra}
    app.state.engine.provider=Provider(item,relation,target)
    r=c.post('/v1/sources',json={'project':'a','messages':[{'id':content,'role':'user','content':content,'observed_at':observed_at or time.time()}]})
    assert r.status_code==202,r.text
    assert app.state.engine.process_one()
    return r.json()

def test_personal_scope_and_project_exception(service):
    c,app,uid=service
    learn(c,app,'我喜欢先讲结论')
    personal=c.get('/v1/search',params={'q':'结论','project':'b'}).json()['items']
    assert len(personal)==1 and personal[0]['scope']=='personal'
    learn(c,app,'这个项目先讲结论并提供完整过程',scope='project')
    assert len(c.get('/v1/search',params={'q':'结论','project':'b'}).json()['items'])==1

def test_replacement_and_undo(service):
    c,app,uid=service
    learn(c,app,'我偏好详细说明')
    old=app.state.store.listing(uid)[0]
    learn(c,app,'以后我偏好简洁说明',relation='supersedes',target=old['id'])
    assert app.state.store.get(uid,old['id'])['status']=='superseded'
    current=app.state.store.listing(uid)[0]
    operation=current['changes'][0]['id']
    assert c.post('/v1/changes/'+operation+'/undo',json={}).status_code==200
    assert app.state.store.get(uid,old['id'])['status']=='active'
    assert app.state.store.get(uid,current['id'])['status']=='superseded'

def test_duplicates_keep_evidence_and_no_resurrection(service):
    c,app,uid=service
    learn(c,app,'我喜欢中文解释')
    old=app.state.store.listing(uid)[0]
    learn(c,app,'我习惯用中文理解',relation='equivalent',target=old['id'])
    assert len(app.state.store.listing(uid))==1
    assert len(app.state.store.get(uid,old['id'])['evidence'])==2
    c.delete('/v1/memories/'+old['id'])
    learn(c,app,'我希望解释使用中文',relation='equivalent',target=old['id'])
    assert app.state.store.listing(uid)==[]

def test_older_and_ambiguous_changes_cannot_replace(service):
    c,app,uid=service
    learn(c,app,'我喜欢先讲结论',observed_at=time.time()-10)
    old=app.state.store.listing(uid)[0]
    learn(c,app,'我以前喜欢详细说明',relation='supersedes',target=old['id'],observed_at=time.time()-1000)
    assert app.state.store.get(uid,old['id'])['status']=='active'
    assert any(m['status']=='candidate' for m in app.state.store.listing(uid,status='candidate'))

def test_expiration_and_archive_metadata(service):
    c,app,uid=service
    m=c.post('/v1/memories',json={'content':'临时测试偏好','kind':'preference','valid_until':time.time()+30}).json()
    c.patch('/v1/memories/'+m['id'],json={'version':m['version'],'valid_until':time.time()-1})
    assert c.get('/v1/search',params={'q':'临时测试'}).json()['items']==[]
    data=c.get('/v1/export').json()
    assert data['format']=='self-agent-v2' and data['metadata']

def test_long_structured_messages_preserve_user_evidence(service):
    c,app,uid=service
    content='偏好原文'*4000
    r=c.post('/v1/sources',json={'project':'a','messages':[{'id':'long','role':'user','content':content,'observed_at':time.time()}]})
    assert r.status_code==202,r.text
    rows=app.state.store.db.execute('SELECT content FROM sources').fetchall()
    assert len(rows)>1
    for row in rows:
        messages=json.loads(row[0]);assert messages[0]['role']=='user' and messages[0]['id'].startswith('long')


def test_archive_v2_restores_relations_and_undo(service):
    from self_agent.archive import restore_user
    c,app,uid=service
    learn(c,app,'我喜欢详细说明')
    old=app.state.store.listing(uid)[0]
    learn(c,app,'以后我喜欢简洁说明',relation='supersedes',target=old['id'])
    archive=c.get('/v1/export').json()
    assert 'user_id' not in json.dumps(archive)
    other=app.state.auth.create_user('other','another-long-password')
    restore_user(app.state.store,other,archive)
    restored=app.state.store.listing(other)[0]
    assert restored['relations'] and restored['evidence']
    cid=next(x['id'] for x in restored['changes'] if x['action']=='replace')
    app.state.store.lifecycle.undo(other,cid)
    assert any(m['content']=='我喜欢详细说明' for m in app.state.store.listing(other))
    # A stale import must not undo the newer local history.
    restore_user(app.state.store,other,archive)
    assert any(m['content']=='我喜欢详细说明' for m in app.state.store.listing(other))


def test_undo_refuses_later_edits_and_other_owner(service):
    c,app,uid=service
    learn(c,app,'我偏好详细回答')
    old=app.state.store.listing(uid)[0]
    learn(c,app,'以后我偏好简短回答',relation='supersedes',target=old['id'])
    current=app.state.store.listing(uid)[0]
    cid=next(x['id'] for x in current['changes'] if x['action']=='replace')
    app.state.store.update(uid,current['id'],content='我偏好简短且有依据的回答')
    assert c.post('/v1/changes/'+cid+'/undo',json={}).status_code==400
    other=app.state.auth.create_user('outsider','another-long-password')
    c.headers['Authorization']='Bearer '+app.state.auth.issue_key(other,'test')
    assert c.post('/v1/changes/'+cid+'/undo',json={}).status_code==404


def test_project_exception_overrides_matching_personal_topic(service):
    c,app,uid=service
    learn(c,app,'我喜欢中文说明',topic='language')
    learn(c,app,'本项目使用英文说明',scope='project',topic='language')
    items=c.get('/v1/search',params={'q':'说明','project':'a'}).json()['items']
    assert len(items)==1 and items[0]['project']=='a'
    items=c.get('/v1/search',params={'q':'说明','project':'b'}).json()['items']
    assert len(items)==1 and items[0]['project']==''


def test_temporary_and_assistant_guess_not_active(service):
    c,app,uid=service
    learn(c,app,'这次回答简短一点',scope='session')
    assert app.state.store.listing(uid)==[]
    learn(c,app,'我猜你可能喜欢蓝色',explicit=False)
    assert app.state.store.listing(uid)==[]
    assert len(app.state.store.listing(uid,status='candidate'))==1


def test_reconciliation_version_guard(service):
    c,app,uid=service
    learn(c,app,'我偏好详细解释')
    old=app.state.store.listing(uid)[0]
    sid,_=app.state.store.source(uid,'a','new','我现在偏好简短解释')
    source=dict(app.state.store.db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone())
    app.state.store.update(uid,old['id'],content='我偏好详细解释并保留依据')
    with pytest.raises(ValueError,match='concurrent'):
        app.state.store.lifecycle.apply(uid,source,{'content':'我现在偏好简短解释','kind':'preference','scope':'personal','explicit':True,'evidence':source['content']},{'relation':'supersedes','target_id':old['id'],'target_version':old['version']},[old])
    assert len(app.state.store.listing(uid))==1


def test_cleanup_is_user_scoped_and_reversible(service):
    c,app,uid=service
    content='我喜欢先看结论'
    old=c.post('/v1/memories',json={'content':content,'kind':'preference','project':'a'}).json()
    other=app.state.auth.create_user('separate','another-long-password')
    foreign=app.state.store.add(other,'a',content,kind='preference')
    app.state.engine.provider=Provider({'content':content,'kind':'preference','explicit':True,'evidence':content,'scope':'personal'})
    jid=c.post('/v1/maintenance/cleanup',json={}).json()['id']
    assert app.state.engine.process_cleanup_one()
    assert app.state.engine.process_cleanup_one()
    moved=app.state.store.get(uid,old['id'])
    assert moved['project']==''
    assert app.state.store.get(other,foreign['id'])['project']=='a'
    cid=moved['changes'][0]['id']
    assert c.post('/v1/changes/'+cid+'/undo',json={}).status_code==200
    assert app.state.store.get(uid,old['id'])['project']=='a'


def test_native_scope_evidence_and_deadline_validation(tmp_path):
    from self_agent.provider import XjtuProvider
    provider=XjtuProvider(Config(tmp_path))
    source=json.dumps([{'id':'u1','role':'user','content':'我喜欢先给结论','observed_at':time.time()}],ensure_ascii=False)
    item={'content':'用户喜欢先给结论','kind':'preference','explicit':True,'evidence':'我喜欢先给结论','scope':'personal','topic':'answer.order'}
    provider.complete=lambda messages:json.dumps({'memories':[item]},ensure_ascii=False)
    assert provider.extract(source)[0]['scope']=='personal'
    provider.complete=lambda messages:json.dumps({'memories':[{**item,'valid_until':time.time()+30,'deadline_evidence':'下个月'}]},ensure_ascii=False)
    with pytest.raises(ValueError):provider.extract(source)


def test_hooks_preserve_utf8_and_redact_credentials(tmp_path,monkeypatch):
    import io
    import self_agent.hooks as hooks
    secret='example-pair-code-that-must-stay-private'
    assert secret not in hooks.redact_secrets('一次性配对码：'+secret)
    assert secret not in hooks.redact_secrets('Bearer '+secret)
    seen=[]
    monkeypatch.setattr(hooks,'handle',lambda client,event:seen.append(event) or {})
    monkeypatch.setattr(hooks.sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps({'prompt':'自然中文 C:\\work'},ensure_ascii=False).encode('utf8')),encoding='cp1252'))
    hooks.main('codex')
    assert seen[0]['prompt']=='自然中文 C:\\work'


def test_topic_is_searchable_without_exact_content_word(service):
    c,app,uid=service
    learn(c,app,'我默认使用英文解释',topic='技术说明语言')
    assert c.get('/v1/search',params={'q':'技术说明语言','project':'b'}).json()['items']


def test_native_date_string_converts_only_when_grounded(tmp_path):
    from self_agent.provider import XjtuProvider
    from datetime import datetime,timezone,timedelta
    provider=XjtuProvider(Config(tmp_path))
    source=json.dumps([{'role':'user','content':'项目联调到2026年11月1日结束'}],ensure_ascii=False)
    item={'content':'联调临时状态','kind':'fact','explicit':True,'evidence':'项目联调到2026年11月1日结束','scope':'project','valid_until':'2026-11-01','deadline_evidence':'2026年11月1日'}
    provider.complete=lambda messages:json.dumps({'memories':[item]},ensure_ascii=False)
    result=provider.extract(source)[0]
    assert datetime.fromtimestamp(result['valid_until'],timezone(timedelta(hours=8))).isoformat()=='2026-11-01T23:59:59+08:00'


def test_native_reconciliation_repairs_invalid_scope_once(tmp_path):
    from self_agent.provider import XjtuProvider
    provider=XjtuProvider(Config(tmp_path))
    old={'id':'old','content':'详细','project':'','status':'active','version':1,'observed_at':1,'topic':'detail','valid_until':None}
    item={'content':'简短','explicit':True,'evidence':'以后简短','scope':'personal','_project':''}
    responses=iter([json.dumps({'relation':'supersedes','target_id':'old','evidence':'以后简短','overrides_id':'old'}),json.dumps({'relation':'supersedes','target_id':'old','evidence':'以后简短','overrides_id':None})])
    provider.complete=lambda messages:next(responses)
    assert provider.reconcile(item,[old])['relation']=='supersedes'


def test_multiple_items_from_one_reply_are_reconciled(service):
    c,app,uid=service
    class Multi(Provider):
        def extract(self,text):return [dict(content='我喜欢中文说明',kind='preference',explicit=True,evidence='我喜欢中文说明',scope='personal'),dict(content='我习惯用中文理解',kind='preference',explicit=True,evidence='我习惯用中文理解',scope='personal')]
        def reconcile(self,item,candidates):return {'relation':'equivalent','target_id':candidates[0]['id'],'target_version':candidates[0]['version']}
    app.state.engine.provider=Multi({})
    c.post('/v1/sources',json={'messages':[{'role':'user','content':'我喜欢中文说明，我习惯用中文理解'}]})
    app.state.engine.process_one()
    assert len(app.state.store.listing(uid))==1
    assert len(app.state.store.listing(uid)[0]['evidence'])==2


def test_projection_scope_change_and_retry_are_idempotent(service):
    from self_agent.index import Index
    c,app,uid=service
    memory=app.state.store.add(uid,'old-project','偏好中文',kind='preference')
    vectors={};next_id=[0]
    class Projection:
        def get(self,mid):return vectors.get(mid)
        def get_all(self,*,filters,top_k):return {'results':[v for v in vectors.values() if v['user_id']==filters['user_id'] and v['metadata']['canonical_id']==filters['canonical_id']]}
        def delete(self,mid):vectors.pop(mid)
        def add(self,content,*,user_id,infer,metadata):
            next_id[0]+=1;mid=str(next_id[0]);vectors[mid]={'id':mid,'user_id':user_id,'metadata':metadata};return {'results':[{'id':mid}]}
    index=Index(Config(app.state.store.filename.parent),app.state.store);index.memory=Projection();index.sync()
    assert len(vectors)==1
    app.state.store.lifecycle.patch(uid,memory['id'],version=1,project='')
    index.sync()
    assert len(vectors)==1 and next(iter(vectors.values()))['user_id']==uid+':'
    # Projection may disappear before an acknowledged sync; retry must rebuild it.
    vectors.clear();app.state.store.update(uid,memory['id'],content='偏好中文且简洁')
    index.sync();assert index.error=='' and len(vectors)==1


def test_partial_hook_upload_resumes_frozen_snapshot(tmp_path,monkeypatch):
    import self_agent.client as client
    monkeypatch.setattr(client,'client_config',lambda:{'local':False})
    import self_agent.hooks as hooks
    import httpx
    private=tmp_path/'private';private.mkdir()
    monkeypatch.setattr(hooks,'private_root',lambda:private)
    monkeypatch.setattr(hooks,'project_id',lambda cwd:'a')
    rows=[{'id':str(i),'role':'user','content':'有依据的长消息'*1000,'observed_at':None} for i in range(3)]
    monkeypatch.setattr(hooks,'normalized_messages',lambda *a:rows.copy())
    seen=[];failed=[False]
    def upload(method,url,**kw):
        number=int(kw['body']['external_id'].rsplit(':',1)[1])
        if number==1 and not failed[0]:failed[0]=True;raise httpx.ConnectTimeout('synthetic network interruption')
        seen.append((kw['body']['external_id'],json.dumps(kw['body']['messages'],sort_keys=True)))
        return {'queued':True}
    monkeypatch.setattr(hooks,'request',upload)
    event={'hook_event_name':'Stop','transcript_path':str(tmp_path/'transcript'),'cwd':str(tmp_path)}
    with pytest.raises(httpx.ConnectTimeout):hooks.handle('codex',event)
    cursor=next((private/'cursors').glob('*.json'));state=json.loads(cursor.read_text())
    assert state['batch_offset']==1 and state['count']==0 and state['pending_end']==3
    # A new message arriving between events cannot alter already accepted batches.
    rows.append({'id':'next','role':'user','content':'后续的新消息','observed_at':None})
    hooks.handle('codex',event)
    state=json.loads(cursor.read_text());assert state=={'count':3}
    assert len({k for k,v in seen})==len(seen)
    hooks.handle('codex',event)
    assert json.loads(cursor.read_text())=={'count':4}
