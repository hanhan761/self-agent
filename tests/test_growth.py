"""Daily growth counts first activation, never updates or current-state snapshots."""
from datetime import datetime,timezone,timedelta
import pytest
from fastapi.testclient import TestClient
from self_agent.config import Config
from self_agent.server import create_app
from self_agent.archive import export_user,restore_user
ZONE=timezone(timedelta(hours=8))
def stamp(value):return datetime.fromisoformat(value).replace(tzinfo=ZONE).timestamp()

@pytest.fixture
def growth(tmp_path):
    app=create_app(Config(tmp_path),start_worker=False)
    uid=app.state.auth.create_user('owner','long-enough-password')
    foreign=app.state.auth.create_user('foreign','another-long-password')
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+app.state.auth.issue_key(uid,'growth-test')
        yield client,app,uid,foreign

def first_at(store,mid,when):
    with store.tx() as db:
        db.execute('UPDATE memories SET created=?,updated=? WHERE id=?',(when,when,mid))
        db.execute('UPDATE versions SET changed=? WHERE memory_id=?',(when,mid))

def test_daily_counts_first_activation_and_fills_local_days(growth):
    c,app,uid,other=growth;s=app.state.store
    a=s.add(uid,'p','最早入库记录');first_at(s,a['id'],stamp('2026-10-28T23:59:59'))
    s.update(uid,a['id'],content='后来编辑的记录')
    s.update(uid,a['id'],status='forgotten')
    s.lifecycle.restore(uid,a['id'],3)
    pending=s.add(uid,'p','待确认记录',status='candidate')
    first_at(s,pending['id'],stamp('2026-10-27T08:00:00'))
    s.update(uid,pending['id'],status='active')
    with s.tx() as db:db.execute('UPDATE versions SET changed=? WHERE memory_id=? AND version=2',(stamp('2026-10-29T00:00:00'),pending['id']))
    s.add(uid,'p','仍然待确认',status='candidate')
    b=s.add(uid,'p','未来的记录');first_at(s,b['id'],stamp('2026-10-30T00:00:00'))
    outsider=s.add(other,'p','其他用户');first_at(s,outsider['id'],stamp('2026-10-29T08:00:00'))
    result=s.daily_growth(uid,days=3,now=stamp('2026-10-29T12:00:00'))
    assert result['timezone']=='Asia/Shanghai'
    assert [x['date'] for x in result['items']]==['2026-10-27','2026-10-28','2026-10-29']
    assert [x['regular'] for x in result['items']]==[0,1,1]
    assert result['totals']=={'regular':2,'imported':0}
    assert result['today']=={'regular':1,'imported':0}

def test_imports_use_admission_time_not_old_observation_date(growth):
    c,app,uid,other=growth;s=app.state.store
    for n,kind,external in [(1,'history','history:v2:fixture'),(2,'conversation','history:explicit-fixture'),(3,'restored','restore:fixture')]:
        sid,_=s.source(uid,'p','补录来源','用户原话',kind=kind,external_id=external)
        m=s.add(uid,'p','补录记忆'+str(n),source_id=sid)
        first_at(s,m['id'],stamp('2026-10-29T08:00:00'))
        s.lifecycle.metadata(m['id'],observed_at=stamp('2026-09-01T08:00:00'))
    result=s.daily_growth(uid,days=2,now=stamp('2026-10-29T12:00:00'))
    assert result['items'][0]=={'date':'2026-10-28','regular':0,'imported':0}
    assert result['items'][1]=={'date':'2026-10-29','regular':0,'imported':3}

def test_duplicate_merge_and_later_removal_do_not_inflate_or_erase_growth(growth):
    c,app,uid,other=growth;s=app.state.store
    original=s.add(uid,'p','同一条记忆')
    first_at(s,original['id'],stamp('2026-10-28T09:00:00'))
    assert s.add(uid,'p','同一条记忆')['id']==original['id']
    s.update(uid,original['id'],status='active')
    s.update(uid,original['id'],status='forgotten')
    result=s.daily_growth(uid,days=2,now=stamp('2026-10-29T12:00:00'))
    assert result['totals']['regular']==1 and result['today']['regular']==0

def test_growth_api_requires_auth_and_rejects_unbounded_windows(growth):
    c,app,uid,other=growth
    for days in (0,91):
        assert c.get('/v1/stats/daily',params={'days':days}).status_code==400
    result=c.get('/v1/stats/daily',params={'days':14})
    assert result.status_code==200 and len(result.json()['items'])==14
    assert all(set(x)=={'date','regular','imported'} for x in result.json()['items'])
    del c.headers['Authorization']
    assert c.get('/v1/stats/daily').status_code==401

def test_restore_preserves_first_activation_dates_and_owner_boundary(growth):
    c,app,uid,other=growth;s=app.state.store
    sid,_=s.source(uid,'p','手动记录','可恢复的统计记录');m=s.add(uid,'p','可恢复的统计记录',source_id=sid);first_at(s,m['id'],stamp('2026-10-28T08:00:00'))
    archive=export_user(s,uid);restore_user(s,other,archive)
    result=s.daily_growth(other,days=2,now=stamp('2026-10-29T12:00:00'))
    assert sum(x['regular']+x['imported'] for x in result['items'])==1
    assert result['items'][0]['imported']==1 and result['items'][1]['imported']==0
