import json,time
import pytest
from self_agent.value import low_value_reason
from self_agent.config import Config
from self_agent.store import Store
from self_agent.auth import Auth
from self_agent.engine import Engine
from self_agent.archive import export_user,restore_user

@pytest.mark.parametrize('content',['采用更高级的方案','用户希望采用更高级的方案','按照这个方案','我刚重启了Codex','已登录交晓智','每天记录一下','修改生产域名DNS','关闭或替换现有生产服务','总数还是50个','剩下26个节点我们可以用','达到上限的，可以适当增加上限','失败的处理一下断点续算','没有实现，没有对齐的，你逐一实现一下'])
def test_context_free_or_momentary_text_is_not_automatic_memory(content):
    assert low_value_reason(content) in ('vague','one_off')

@pytest.mark.parametrize('content',['默认中文回答','后台执行不要弹出控制台','界面要做得简单一点','窗口晃动时鼠标仍要能用','这个项目必须实时保存','D盘存储知识库','复用已登录交晓智的授权凭据','以后写Word必须用修订模式','采用更高级的有限元单元方案','修改生产域名DNS之前必须取得确认','体重网页需要每天记录体重并显示折线图'])
def test_specific_preferences_and_project_constraints_remain_useful(content):
    assert low_value_reason(content) is None

@pytest.fixture
def records(tmp_path):
    store=Store(tmp_path/'db');uid=Auth(store).create_user('owner','long-safe-password')
    sid,_=store.source(uid,'project','conversation','采用更高级的方案','conversation')
    row=store.add(uid,'project','采用更高级的方案',source_id=sid,kind='decision')
    store.lifecycle.metadata(row['id'],observed_at=100,topic='原始主题')
    yield store,uid,row,sid
    store.close()

def test_automatic_gate_skips_reconciliation_but_manual_write_stays(records):
    store,uid,row,sid=records
    source=dict(store.db.execute('select * from sources where id=?',(sid,)).fetchone())
    item={'content':'采用更高级的方案','evidence':'采用更高级的方案','scope':'project','explicit':True,'kind':'decision'}
    class Provider:
        configured=True
        def reconcile(self,*a):pytest.fail('low-value automatic item should not need model reconciliation')
    engine=Engine(Config(store.filename.parent),store,Provider())
    candidates,decision=engine.prepare(uid,source,item)
    assert store.lifecycle.apply(uid,source,item,decision,candidates) is None
    assert store.get(uid,row['id'])['version']==1
    manual,_=store.source(uid,'project','manual note','按照这个方案','manual')
    manual_source=dict(store.db.execute('select * from sources where id=?',(manual,)).fetchone())
    assert store.lifecycle.apply(uid,manual_source,{**item,'content':'按照这个方案','evidence':'按照这个方案'}, {'relation':'independent'},[]) is not None

@pytest.mark.parametrize('original_status',['active','candidate'])
def test_archive_preserves_original_content_and_can_restore_exact_state(records,original_status):
    store,uid,row,sid=records
    if original_status=='candidate':row=store.update(uid,row['id'],status='candidate')
    original=store.get(uid,row['id']);operation=store.lifecycle.archive_low_value(uid,[{'id':row['id'],'version':row['version'],'reason':'vague'}])
    archived=store.get(uid,row['id'])
    assert archived['status']=='superseded' and archived['reason']=='low_value:vague'
    assert archived['content']==original['content'] and archived['observed_at']==100
    assert not store.search(uid,'高级','project')
    store.lifecycle.undo(uid,operation['changes'][0]['change_id'])
    restored=store.get(uid,row['id'])
    assert restored['status']==original_status and restored['reason']==original['reason']
    assert restored['observed_at']==100 and restored['topic']=='原始主题'

def test_archive_owner_version_and_manual_guards_are_atomic(records):
    store,uid,row,sid=records
    other=Auth(store).create_user('other','long-safe-password')
    with pytest.raises(KeyError):store.lifecycle.archive_low_value(other,[{'id':row['id'],'version':1,'reason':'vague'}])
    manual,_=store.source(uid,'project','manual','用户手写内容','manual')
    note=store.add(uid,'project','用户手写内容',source_id=manual)
    with pytest.raises(ValueError,match='manual_memory_protected'):
        store.lifecycle.archive_low_value(uid,[{'id':row['id'],'version':1,'reason':'vague'},{'id':note['id'],'version':1,'reason':'vague'}])
    assert store.get(uid,row['id'])['version']==1 and store.get(uid,row['id'])['status']=='active'
    store.update(uid,row['id'],content='已由用户修改的具体要求')
    with pytest.raises(ValueError,match='concurrent'):
        store.lifecycle.archive_low_value(uid,[{'id':row['id'],'version':1,'reason':'vague'}])

def test_portable_restore_keeps_retirement_and_later_undo_guard(records):
    store,uid,row,sid=records
    stale=export_user(store,uid)
    op=store.lifecycle.archive_low_value(uid,[{'id':row['id'],'version':1,'reason':'vague'}])
    restore_user(store,uid,stale)
    assert store.get(uid,row['id'])['status']=='superseded'
    portable=export_user(store,uid);other=Auth(store).create_user('other','long-safe-password')
    restore_user(store,other,portable)
    assert store.listing(other,status='superseded')[0]['reason']=='low_value:vague'
    store.update(uid,row['id'],content='后续用户修改')
    with pytest.raises(ValueError):store.lifecycle.undo(uid,op['changes'][0]['change_id'])

def test_assistant_reports_do_not_accumulate_as_candidate_user_memories():
    from self_agent.provider import validate_extraction
    source=json.dumps([{'role':'assistant','content':'所有配图已经完成'},{'role':'user','content':'以后作图用微软雅黑'}],ensure_ascii=False)
    reply=json.dumps({'memories':[
        {'content':'所有配图已经完成','kind':'fact','evidence':'所有配图已经完成','explicit':True,'scope':'project'},
        {'content':'以后作图用微软雅黑','kind':'preference','evidence':'以后作图用微软雅黑','explicit':True,'scope':'personal'}]},ensure_ascii=False)
    result=validate_extraction(source,reply,require_scope=True)
    assert len(result)==1 and result[0]['content']=='以后作图用微软雅黑'
