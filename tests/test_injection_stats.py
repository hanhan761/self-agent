"""Daily injection metrics count recorded context once, without retaining content."""
import json,sqlite3
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
from self_agent.config import Config
from self_agent.server import create_app
from self_agent.injection_stats import MARKER,daily_injection

class Encoder:
    def encode(self,text,disallowed_special=()):
        return list(text)

def event(role,text,id,at='2026-11-05T15:30:00Z'):
    return {'timestamp':at,'type':'response_item','payload':{'type':'message','role':role,'id':id,'content':[{'type':'input_text','text':text}]}}

def write_rows(path,rows,mode='ab'):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open(mode) as f:
        for row in rows:f.write((json.dumps(row,ensure_ascii=False)+'\n').encode())

def test_incremental_daily_count_deduplicates_and_keeps_no_plaintext(tmp_path):
    home=tmp_path/'home';data=tmp_path/'data';data.mkdir()
    session=home/'.codex/sessions/a/log.jsonl';other=home/'.codex/archived_sessions/other.jsonl'
    meta={'type':'session_meta','payload':{'id':'session-one'}}
    text=MARKER+'\n- private-secret-content [memory:abc]'
    one=event('developer',text,'msg-1')
    write_rows(session,[meta,one,one,event('user',text,'untrusted'),event('developer','other','other')])
    write_rows(other,[meta,one])
    # An incomplete line must be read after it becomes complete.
    two=event('developer',MARKER+'\n- another [memory:def]','msg-2','2026-11-05T16:30:00Z')
    raw=(json.dumps(two,ensure_ascii=False)+'\n').encode()
    with session.open('ab') as f:f.write(raw[:50])
    now=datetime(2026,11,6,12,tzinfo=timezone(timedelta(hours=8))).timestamp()
    first=daily_injection(data,2,home=home,now=now,encoder=Encoder())
    assert [r['messages'] for r in first['items']]==[1,0]
    assert first['items'][0]['tokens']==len(text)
    with session.open('ab') as f:f.write(raw[50:])
    second=daily_injection(data,2,home=home,now=now,encoder=Encoder())
    assert [r['messages'] for r in second['items']]==[1,1]
    assert second['total']==len(text)+len(two['payload']['content'][0]['text'])
    assert daily_injection(data,2,home=home,now=now,encoder=Encoder())==second
    assert b'private-secret-content' not in (data/'injection-stats.sqlite3').read_bytes()

def test_local_owner_only_and_bounded_api(tmp_path,monkeypatch):
    config=Config(tmp_path,local=True)
    app=create_app(config,start_worker=False)
    owner=app.state.auth.create_user('owner','long-enough-password')
    other=app.state.auth.create_user('other','another-long-password')
    config.local_user_id=owner
    import self_agent.injection_stats as module
    monkeypatch.setattr(module,'daily_injection',lambda data_dir,days:{'items':[],'today':42,'total':42} if 1<=days<=90 else (_ for _ in ()).throw(ValueError('range')))
    with TestClient(app,base_url='http://127.0.0.1:8766') as client:
        assert client.get('/v1/stats/injection-tokens').status_code==401
        client.headers['Authorization']='Bearer '+app.state.auth.issue_key(other,'other')
        assert client.get('/v1/stats/injection-tokens').status_code==403
        client.headers['Authorization']='Bearer '+app.state.auth.issue_key(owner,'owner')
        assert client.get('/v1/stats/injection-tokens?days=0').status_code==400
        assert client.get('/v1/stats/injection-tokens?days=14').json()['today']==42
