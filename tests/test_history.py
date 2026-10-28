import json,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from self_agent.history import iter_messages,history_batches,redact_history
from self_agent.config import Config
from self_agent.store import Store
from self_agent.auth import Auth
from self_agent.engine import Engine

def transcript(home,rows,tail=b''):
    path=home/'.codex/sessions/fixture.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'\n'.join(json.dumps(r).encode() for r in rows)+tail)
    return path

def meta(source='cli'):
    return {'type':'session_meta','payload':{'cwd':'C:/fixture/project','source':source}}

def message(role,text,phase=None):
    row={'type':'response_item','timestamp':'2026-01-01T10:00:00Z','payload':{'type':'message','role':role,'content':[{'type':'input_text' if role=='user' else 'output_text','text':text}]}}
    if phase:row['payload']['phase']=phase
    return row

def test_history_streams_large_tool_lines_without_parsing_them(tmp_path):
    path=transcript(tmp_path,[meta(),message('user','明确要求使用本地知识库')],tail=b'\n')
    with path.open('ab') as f:
        f.write(b'{"type":"response_item","payload":{"type":"function_call_output","output":"')
        for _ in range(9):f.write(b'x'*1024**2)
        f.write(b'"}}\n'+json.dumps(message('user','保留消息原始时间')).encode()+b'\n')
    stats={};rows=list(iter_messages(path,'codex',home=tmp_path,stats=stats))
    assert [r['content'] for r in rows]==['明确要求使用本地知识库','保留消息原始时间']
    assert stats['oversized_lines']==1 and rows[0]['observed_at']<time.time()

def test_history_excludes_host_noise_and_keeps_old_final_answer_and_actual_reply(tmp_path):
    reply='<send_user_message_question_reply>'+json.dumps([{'question':'所有项目的说明使用什么语言？','answer':'中文'}],ensure_ascii=False)+'</send_user_message_question_reply>'
    path=transcript(tmp_path,[meta(),message('user','# AGENTS.md instructions\nhost rules'),message('assistant','没有 phase 的旧版回复'),message('assistant','工具运行中','commentary'),message('user',reply)])
    rows=list(iter_messages(path,'codex',home=tmp_path))
    assert [r['content'] for r in rows]==['没有 phase 的旧版回复','所有项目的说明使用什么语言？','中文']
    assert rows[-2]['role']=='assistant' and rows[-1]['role']=='user'

@pytest.mark.parametrize('source',['exec',{'subagent':'review'}])
def test_automated_tasks_are_not_user_facts(tmp_path,source):
    path=transcript(tmp_path,[meta(source),message('user','由父智能体生成的子任务')],tail=b'\n')
    assert not list(iter_messages(path,'codex',home=tmp_path))

def test_history_scope_and_partial_append_are_rejected(tmp_path):
    outside=tmp_path/'outside.jsonl';outside.write_text('{}')
    with pytest.raises(ValueError,match='untrusted'):list(iter_messages(outside,'codex',home=tmp_path))
    path=transcript(tmp_path,[meta(),message('user','完整的消息')],tail=b'\n{"type":"response_item"')
    assert len(list(iter_messages(path,'codex',home=tmp_path)))==1

def test_role_envelopes_are_never_cut_as_serialized_json():
    rows=[{'id':'a','role':'assistant','content':'方案说明'*1000,'observed_at':1},
          {'id':'u','role':'user','content':'长期数据存储要求'*2000,'observed_at':2}]
    batches=list(history_batches(rows))
    assert len(batches)>1
    assert all(len(json.dumps(batch,ensure_ascii=False))<=12000 for batch in batches)
    assert ''.join(m['content'] for b in batches for m in b if m['role']=='user')==rows[1]['content']
    assert sum(len(m['content']) for b in batches for m in b if m['role']=='assistant')==1200

def test_mature_secret_detectors_are_offline_and_preserve_requirements(monkeypatch):
    pytest.importorskip('detect_secrets')
    import socket
    def forbidden(*a,**kw):raise AssertionError('network verification forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    token='ghp_'+('aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4')
    text='数据库保存在 D 盘。\nGitHub token '+token
    cleaned=redact_history(text)
    assert token not in cleaned and '[REDACTED]' in cleaned and '数据库保存在 D 盘' in cleaned

def test_targeted_history_jobs_reuse_checkpoint_and_cannot_overwrite_new_preference(tmp_path):
    store=Store(tmp_path/'memory.sqlite3');uid=Auth(store).create_user('owner','long-fixture-password')
    old=store.add(uid,'p','数据保存在 D 盘',kind='preference')
    with store.tx():store.lifecycle.metadata(old['id'],observed_at=time.time())
    observed=time.time()-100000
    messages=[{'id':'past','role':'user','content':'数据保存在 E 盘','observed_at':observed}]
    sid,_=store.source(uid,'p','history',json.dumps(messages,ensure_ascii=False),'conversation');jid=store.enqueue(uid,sid)
    item={'content':'数据保存在 E 盘','kind':'preference','scope':'project','explicit':True,'evidence':'数据保存在 E 盘','valid_until':None}
    with store.tx() as db:
        db.execute("update jobs set state='history_pending' where id=?",(jid,))
        db.execute('insert into job_extractions values(?,?,0)',(jid,json.dumps([item])))
    class Provider:
        configured=True
        def extract(self,*a):raise AssertionError('completed extraction must not be repeated')
        def reconcile(self,item,candidates):return {'relation':'supersedes','target_id':old['id'],'target_version':old['version']}
    engine=Engine(Config(tmp_path,local=True,local_user_id=uid),store,Provider())
    assert not engine.process_one()
    assert engine.process_one(jid)
    assert store.get(uid,old['id'])['status']=='active'
    assert not any('E' in m['content'] for m in store.listing(uid))
    assert store.db.execute('select state from jobs where id=?',(jid,)).fetchone()[0]=='done'
    other=Auth(store).create_user('other','another-fixture-password');sid,_=store.source(other,'p','foreign','foreign');foreign=store.enqueue(other,sid)
    with store.tx() as db:db.execute("update jobs set state='history_pending' where id=?",(foreign,))
    assert not engine.process_one(foreign)
    engine.close();store.close()

def test_native_failure_preserves_real_stage_and_status_without_echoed_secrets():
    from http.server import BaseHTTPRequestHandler,HTTPServer
    import threading
    from self_agent.xjtu_top import TopClient,Credentials,TopError
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length',0)))
            body=json.dumps({'ResponseMetadata':{'Error':{'Code':'UpstreamLimited','Message':'private-fixture-secret'}}}).encode()
            self.send_response(500);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers()
            self.wfile.write(body);self.wfile.flush()
        def log_message(self,*a):pass
    server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        client=TopClient(Credentials('fixture-id','private-fixture-secret','account','workspace','model'),url='http://127.0.0.1:'+str(server.server_port))
        with pytest.raises(TopError) as error:client.call('CreateConversation',{})
        assert error.value.action=='CreateConversation'
        assert error.value.http_status==500  # Never infer 429 from an error string.
        assert error.value.upstream_code=='UpstreamLimited'
        assert 'private-fixture-secret' not in str(error.value)
    finally:server.shutdown();server.server_close();thread.join()


def test_import_checkpoint_staging_is_idempotent_and_preserves_observation(tmp_path):
    from self_agent.history import stage_history
    store=Store(tmp_path/'memory.sqlite3');uid=Auth(store).create_user('owner','long-fixture-password');cfg=Config(tmp_path,local=True,local_user_id=uid)
    observed=time.time()-10000;messages=[{'id':'u','role':'user','content':'以后所有说明都使用中文','observed_at':observed}]
    task={'id':'frozen-fixture','project':'p','text':json.dumps(messages,ensure_ascii=False),'observed':observed}
    results={'frozen-fixture':[{'content':'以后所有说明都使用中文','kind':'preference','scope':'personal','explicit':True,'evidence':'以后所有说明都使用中文','valid_until':None}]}
    jobs=stage_history(cfg,store,[task],results,{'p':'测试项目'})
    assert len(jobs)==1 and store.db.execute('select state from jobs').fetchone()[0]=='history_pending'
    assert stage_history(cfg,store,[task],results,{'p':'测试项目'})==jobs
    assert store.db.execute('select count(*) from jobs').fetchone()[0]==1
    assert store.overview(uid)['project_names']=={'p':'测试项目'}
    other=Auth(store).create_user('other','another-fixture-password')
    assert not store.overview(other)['project_names']
    engine=Engine(cfg,store,SimpleNamespace(configured=True))
    assert engine.process_one(jobs[0]['id'])
    memory=store.listing(uid)[0];assert memory['observed_at']==observed and memory['project']==''
    store.update(uid,memory['id'],status='forgotten')
    stage_history(cfg,store,[task],results)
    assert not engine.process_one(jobs[0]['id']) and not store.listing(uid)
    engine.close();store.close()

def test_historical_ingestion_time_does_not_displace_recent_startup_defaults(tmp_path):
    store=Store(tmp_path/'memory.sqlite3');uid=Auth(store).create_user('owner','long-fixture-password')
    current=store.add(uid,'','最近确认的交互规则',kind='preference')
    for n in range(12):
        past=store.add(uid,'','较早的个人规则'+str(n),kind='preference')
        with store.tx():store.lifecycle.metadata(past['id'],observed_at=time.time()-10000-n)
    engine=Engine(Config(tmp_path),store,SimpleNamespace(configured=False))
    assert engine.context(uid,limit=1)[0]['id']==current['id']
    engine.close();store.close()


def test_wrapped_rate_receipt_is_strict_and_does_not_report_http429():
    from self_agent.native_rate import rate_receipt,WRAPPED_MESSAGE
    body=json.dumps({'ResponseMetadata':{'Error':{'Code':'InternalError.Error','Message':WRAPPED_MESSAGE}}})
    receipt=rate_receipt(500,body)
    assert receipt['limited'] and receipt['gateway_http_status']==500 and receipt['upstream_reported_status']==429
    assert not rate_receipt(500,json.dumps({'ResponseMetadata':{'Error':{'Code':'InternalError.Error','Message':'some unrelated 429 string'}}}))['limited']
    assert 'Message' not in receipt and 'body_sha256' in receipt

def test_individual_user_parts_survive_host_bootstrap_and_internal_context_is_omitted(tmp_path):
    row=message('user','')
    row['payload']['content']=[{'type':'input_text','text':'# AGENTS.md instructions\nlong host rules'},{'type':'input_text','text':'我喜欢先看结论'}]
    path=transcript(tmp_path,[meta(),message('user','<codex_internal_context>old tool context</codex_internal_context>'),row])
    result=list(iter_messages(path,'codex',home=tmp_path))
    assert len(result)==1 and result[0]['content']=='我喜欢先看结论'

def test_explicit_recent_import_keeps_role_envelopes_and_original_time(tmp_path,monkeypatch):
    from self_agent import importer
    when=time.time()-100
    row=message('user','以后所有项目都使用中文说明')
    row['timestamp']=when
    path=transcript(tmp_path,[meta(),row],tail=b'\n')
    monkeypatch.setattr(importer,'inventory',lambda *a:{'session':path})
    monkeypatch.setattr(importer,'project_id',lambda *a:'fixture-project')
    calls=[]
    monkeypatch.setattr(importer,'request',lambda *a,**kw:calls.append(kw['body']))
    result=importer.import_recent('C:/fixture/project',30,home=tmp_path)
    assert result['queued_packets']==1 and isinstance(calls[0]['messages'],list)
    assert calls[0]['messages'][0]['observed_at']==when and calls[0]['project']=='fixture-project'
    assert not importer.import_recent('C:/different-project',30,home=tmp_path)['queued_packets']

@pytest.mark.parametrize('limited',[True,False])
def test_import_only_retries_a_confirmed_rate_rejection(tmp_path,limited):
    from self_agent.history import stage_history
    from self_agent.xjtu_top import TopError
    store=Store(tmp_path/'memory.sqlite3');uid=Auth(store).create_user('owner','long-fixture-password')
    cfg=Config(tmp_path,local=True,local_user_id=uid)
    store.add(uid,'p','已有项目偏好',kind='preference')
    messages=[{'id':'u','role':'user','content':'新增项目偏好','observed_at':time.time()}]
    task={'id':'rate-fixture','project':'p','text':json.dumps(messages,ensure_ascii=False),'observed':time.time()}
    result={'rate-fixture':[{'content':'新增项目偏好','kind':'preference','scope':'project','explicit':True,'evidence':'新增项目偏好','valid_until':None}]}
    jid=stage_history(cfg,store,[task],result)[0]['id']
    class Provider:
        configured=True
        def reconcile(self,*a):raise TopError('request failed',action='Chat',http_status=500,rate_receipt={'limited':limited,'retry_after_seconds':0})
        def extract(self,*a):raise AssertionError('checkpoint must be reused')
    engine=Engine(cfg,store,Provider());assert engine.process_one(jid)
    row=store.db.execute('select state,next_at from jobs where id=?',(jid,)).fetchone()
    assert row['state']==('history_pending' if limited else 'uncertain')
    if limited:assert row['next_at']>time.time()+60
    engine.close();store.close()


def test_invalid_confirmed_history_relation_is_quarantined_without_blocking_batch(tmp_path):
    from self_agent.history import stage_history
    from self_agent.provider import ReconciliationError
    store=Store(tmp_path/'memory.sqlite3');uid=Auth(store).create_user('owner','long-fixture-password')
    cfg=Config(tmp_path,local=True,local_user_id=uid)
    old=store.add(uid,'p','保留原有规则',kind='preference')
    text='新增规则甲；新增规则乙'
    task={'id':'invalid-relation','project':'p','text':json.dumps([{'id':'u','role':'user','content':text,'observed_at':time.time()}],ensure_ascii=False),'observed':time.time()}
    results={task['id']:[dict(content=x,kind='preference',scope='project',explicit=True,evidence=x,valid_until=None) for x in ('新增规则甲','新增规则乙')]}
    jid=stage_history(cfg,store,[task],results)[0]['id']
    class Provider:
        configured=True
        def extract(self,*a):raise AssertionError('must not re-extract')
        def reconcile(self,item,candidates):
            if item['content']=='新增规则甲':raise ReconciliationError('reconciliation_validation_failed')
            return {'relation':'independent'}
    engine=Engine(cfg,store,Provider())
    assert engine.process_one(jid)
    assert store.db.execute('select state from jobs where id=?',(jid,)).fetchone()[0]=='done'
    assert store.db.execute('select next_item from job_extractions where job_id=?',(jid,)).fetchone()[0]==2
    assert store.get(uid,old['id'])['status']=='active'
    candidate=store.listing(uid,status='candidate')[0]
    assert candidate['content']=='新增规则甲' and candidate['reason']=='unvalidated_reconciliation' and candidate['evidence']
    assert any(m['content']=='新增规则乙' for m in store.listing(uid))
    assert not engine.process_one(jid)
    engine.close();store.close()
