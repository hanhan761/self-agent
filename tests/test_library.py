"""Management views use exact scope; recall still combines global and project context."""
import pytest
from fastapi.testclient import TestClient
from self_agent.config import Config
from self_agent.server import create_app

@pytest.fixture
def library(tmp_path):
    app=create_app(Config(tmp_path),start_worker=False)
    uid=app.state.auth.create_user('owner','long-enough-password')
    other=app.state.auth.create_user('other','another-long-password')
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+app.state.auth.issue_key(uid,'library-test')
        yield c,app,uid,other

def add(c,text,project='',kind='preference'):
    r=c.post('/v1/memories',json={'content':text,'project':project,'kind':kind})
    assert r.status_code==201
    return r.json()

def test_exact_management_scope_preserves_legacy_recall(library):
    c,app,uid,other=library
    g=add(c,'通用中文说明');p=add(c,'项目中文说明','p')
    assert len(c.get('/v1/memories',params={'project':'p'}).json()['items'])==2
    result=c.get('/v1/memories',params={'project':'p','exact_project':True}).json()
    assert result['total']==1 and result['items'][0]['id']==p['id']
    assert {x['id'] for x in c.get('/v1/search',params={'q':'中文说明','project':'p'}).json()['items']}=={g['id'],p['id']}

def test_count_type_sort_topic_and_project_name_filters(library):
    c,app,uid,other=library
    first=add(c,'先确认输入','p','procedure');second=add(c,'明确期望输出','p','decision')
    app.state.store.lifecycle.metadata(first['id'],topic='建模约束')
    with app.state.store.tx() as db:
        db.execute('INSERT INTO project_labels VALUES(?,?,?)',(uid,'p','力学项目'))
    result=c.get('/v1/memories',params={'kind':'procedure','q':'建模约束','limit':1}).json()
    assert result['total']==1 and result['items'][0]['id']==first['id']
    assert c.get('/v1/memories',params={'q':'力学项目'}).json()['total']==2
    page=c.get('/v1/memories',params={'limit':1,'sort':'oldest'}).json()
    assert page['total']==2 and page['items'][0]['id']==first['id']
    assert c.get('/v1/memories',params={'kind':'invalid'}).status_code==400

def test_navigation_counts_are_owner_and_status_scoped(library):
    c,app,uid,other=library
    add(c,'全局偏好');p=add(c,'项目约定','p')
    app.state.store.add(other,'p','其他人的全局与项目均不可见',kind='preference')
    candidate=app.state.store.add(uid,'p','存疑的原文',status='candidate')
    overview=c.get('/api/overview').json()
    assert overview['scope_counts']['global']['active']==1
    assert overview['scope_counts']['project']['active']==1
    assert overview['project_counts']['p']=={'active':1,'candidate':1}
    assert overview['counts']['active']==2

def test_bulk_scope_change_requires_versions_and_is_atomic(library):
    c,app,uid,other=library
    a=add(c,'通用可复用方法甲','p');b=add(c,'通用可复用方法乙','p')
    app.state.store.update(uid,b['id'],content='后来修订的方法乙')
    items=[{'id':a['id'],'version':a['version']},{'id':b['id'],'version':b['version']}]
    r=c.post('/v1/memories/bulk',json={'items':items,'action':'move','project':''})
    assert r.status_code==400
    assert app.state.store.get(uid,a['id'])['project']=='p'
    items[1]['version']=2
    result=c.post('/v1/memories/bulk',json={'items':items,'action':'move','project':''})
    assert result.status_code==200,result.text
    assert result.json()['updated']==2
    for row in result.json()['items']:
        assert row['project']=='' and row['evidence'] and row['changes']
        change=row['changes'][0]['id']
        assert c.post('/v1/changes/'+change+'/undo',json={}).status_code==200
        assert app.state.store.get(uid,row['id'])['project']=='p'

def test_bulk_cannot_cross_owner_or_resurrect_forgotten(library):
    c,app,uid,other=library
    a=add(c,'自己的记忆','p');foreign=app.state.store.add(other,'p','其他人的记忆')
    r=c.post('/v1/memories/bulk',json={'items':[{'id':a['id'],'version':1},{'id':foreign['id'],'version':1}],'action':'forget'})
    assert r.status_code==404 and app.state.store.get(uid,a['id'])['status']=='active'
    c.delete('/v1/memories/'+a['id'])
    for action in ('move','activate'):
        r=c.post('/v1/memories/bulk',json={'items':[{'id':a['id'],'version':2}],'action':action,'project':''})
        assert r.status_code==400
    assert app.state.store.get(uid,a['id'])['status']=='forgotten'

def test_bulk_activation_is_explicit_and_candidates_only(library):
    c,app,uid,other=library
    item=app.state.store.add(uid,'p','待确认的记忆',status='candidate')
    r=c.post('/v1/memories/bulk',json={'items':[{'id':item['id'],'version':1}],'action':'activate'})
    assert r.status_code==200 and r.json()['items'][0]['status']=='active'
    assert c.post('/v1/memories/bulk',json={'items':[{'id':item['id'],'version':2}]*2,'action':'forget'}).status_code==400

def test_project_names_are_editable_without_changing_scope_and_owner(library):
    c,app,uid,other=library
    item=add(c,'项目里的记忆','p');app.state.store.add(other,'private','不可访问')
    r=c.patch('/v1/projects/name',json={'project':'p','label':'可读项目名'})
    assert r.status_code==200 and c.get('/api/overview').json()['project_names']['p']=='可读项目名'
    assert app.state.store.get(uid,item['id'])['project']=='p'
    assert c.patch('/v1/projects/name',json={'project':'private','label':'泄漏'}).status_code==404


def test_bulk_duplicate_scope_collision_rolls_back_every_row(library):
    c,app,uid,other=library
    a=add(c,'同一条完整记忆','p');b=add(c,'同一条完整记忆','q')
    result=c.post('/v1/memories/bulk',json={'items':[{'id':a['id'],'version':1},{'id':b['id'],'version':1}],'action':'move','project':''})
    assert result.status_code==409
    assert app.state.store.get(uid,a['id'])['project']=='p'
    assert app.state.store.get(uid,b['id'])['project']=='q'
    assert app.state.store.get(uid,a['id'])['version']==1
