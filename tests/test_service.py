import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from self_agent.config import Config
from self_agent.server import create_app
from self_agent.archive import export_user,restore_user,encrypt_backup,decrypt_backup
from self_agent.provider import XjtuProvider
from self_agent.local_backup import backup_local,verify_local_backup
from self_agent.install import install_client

@pytest.fixture
def service(tmp_path):
    app=create_app(Config(tmp_path),start_worker=False)
    auth=app.state.auth
    alice=auth.create_user('alice','long-password-alice',True)
    bob=auth.create_user('bob','long-password-for-bob')
    token=auth.issue_key(alice,'test')
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+token
        yield client,app,alice,bob

def add(client,content='中文说明更方便',project='',**values):
    response=client.post('/v1/memories',json={'content':content,'project':project,**values})
    assert response.status_code==201,response.text
    return response.json()

def test_authentication(service):
    c,app,alice,bob=service
    assert c.get('/api/me').json()['id']==alice
    del c.headers['Authorization']
    assert c.get('/v1/memories').status_code==401
    assert c.post('/api/login',json={'username':'alice','password':'wrong'}).status_code==401
    assert c.post('/api/login',json={'username':'alice','password':'long-password-alice'}).status_code==200
    assert c.get('/api/me').json()['id']==alice
    assert c.cookies.get('sa_session')

def test_owner_isolation(service):
    c,app,alice,bob=service
    item=add(c)
    c.headers['Authorization']='Bearer '+app.state.auth.issue_key(bob,'bob')
    assert c.get('/v1/memories/'+item['id']).status_code==404
    assert c.patch('/v1/memories/'+item['id'],json={'content':'changed','version':1}).status_code==404
    assert not c.get('/v1/search',params={'q':'中文'}).json()['items']
    assert c.get('/v1/export').json()['memories']==[]
    assert c.get('/v1/sources/'+item['source_id']).status_code==404

def test_project_scope(service):
    c,app,alice,bob=service
    personal=add(c,'所有项目都使用中文说明')
    a=add(c,'项目A使用 sqlite 数据库','project-a')
    b=add(c,'项目B使用 sqlite 数据库','project-b')
    ids={m['id'] for m in c.get('/v1/search',params={'q':'sqlite 中文','project':'project-a'}).json()['items']}
    assert a['id'] in ids and personal['id'] in ids and b['id'] not in ids

def test_update_versions_and_conflict(service):
    c,*_=service
    item=add(c,'报告先给出结论')
    response=c.patch('/v1/memories/'+item['id'],json={'content':'报告先给出摘要','version':1})
    assert response.status_code==200,response.text
    assert response.json()['version']==2
    assert len(response.json()['history'])==2
    assert c.patch('/v1/memories/'+item['id'],json={'content':'stale','version':1}).status_code==400
    assert not c.get('/v1/search',params={'q':'结论'}).json()['items']

def test_forget_and_stale_restore(service):
    c,app,alice,bob=service
    item=add(c,'长期偏好不需要弹窗')
    old=c.get('/v1/export').json()
    assert c.delete('/v1/memories/'+item['id']).status_code==200
    assert not c.get('/v1/search',params={'q':'弹窗'}).json()['items']
    assert c.post('/v1/restore',json=old).status_code==200
    assert app.state.store.get(alice,item['id'])['status']=='forgotten'
    old['memories'][0]['fingerprint']='tampered'
    assert c.post('/v1/restore',json=old).status_code==200
    assert app.state.store.get(alice,item['id'])['status']=='forgotten'
    assert add(c,'长期偏好不需要弹窗')['status']=='forgotten'

def test_candidate_not_recalled(service):
    c,app,alice,bob=service
    item=app.state.store.add(alice,'','用户可能喜欢蓝色',status='candidate')
    assert not c.get('/v1/search',params={'q':'蓝色'}).json()['items']
    assert c.patch('/v1/memories/'+item['id'],json={'status':'active','version':1}).status_code==200
    assert c.get('/v1/search',params={'q':'蓝色'}).json()['items']

def test_duplicate_and_ingest_idempotence(service):
    c,*_=service
    one=add(c,'偏好 中文 说明')
    two=add(c,'偏好中文说明')
    assert one['id']==two['id']
    body={'content':'一条明确的项目讨论','external_id':'event-1','project':'a'}
    one=c.post('/v1/sources',json=body).json()
    two=c.post('/v1/sources',json=body).json()
    assert one['jobs']==two['jobs']

def test_export_restore_versions_and_rollback(service):
    c,app,alice,bob=service
    one=add(c,'保存事实与来源')
    c.patch('/v1/memories/'+one['id'],json={'content':'保存事实与版本来源','version':1})
    data=c.get('/v1/export').json()
    payload=json.dumps(data)
    assert 'password_hash' not in payload and 'api_keys' not in payload
    result=restore_user(app.state.store,bob,data)
    assert result['restored']==1
    restored=app.state.store.listing(bob)[0]
    assert restored['version']==2
    assert len(app.state.store.get(bob,restored['id'])['history'])==2
    assert restore_user(app.state.store,bob,data)['restored']==0
    malformed={**data,'memories':[{'status':'nonsense'}]}
    before=app.state.store.overview(bob)['sources']
    with pytest.raises(ValueError):restore_user(app.state.store,bob,malformed)
    assert app.state.store.overview(bob)['sources']==before

def test_encrypted_export_integrity():
    value={'format':'self-agent-v1','memories':[]}
    encrypted=encrypt_backup(value,'long-backup-password')
    assert decrypt_backup(encrypted,'long-backup-password')==value
    with pytest.raises(Exception):decrypt_backup(encrypted,'wrong-long-password')
    with pytest.raises(Exception):decrypt_backup(encrypted[:-1]+bytes([encrypted[-1]^1]),'long-backup-password')

def test_origin_and_keys(service):
    c,*_=service
    assert c.post('/v1/memories',json={'content':'test'},headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post('/v1/memories',content='text',headers={'Content-Type':'text/plain'}).status_code==415
    token=c.post('/api/keys',json={'name':'second'}).json()['token']
    listing=c.get('/api/keys').json()['items']
    assert all('hash' not in row and 'token' not in row for row in listing)
    kid=next(row['id'] for row in listing if row['name']=='second')
    assert c.delete('/api/keys/'+kid).status_code==200
    assert c.get('/api/me',headers={'Authorization':'Bearer '+token}).status_code==401

def test_jobs_validation_and_uncertain(service):
    c,app,alice,bob=service
    class Provider:
        configured=True
        def extract(self,text):raise TimeoutError()
    app.state.engine.provider=Provider()
    job=c.post('/v1/sources',json={'content':'背景资料'}).json()['jobs'][0]
    app.state.engine.process_one()
    with app.state.store.tx() as db:assert db.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()[0]=='uncertain'
    app.state.engine.process_one()
    with app.state.store.tx() as db:assert db.execute('SELECT attempts FROM jobs WHERE id=?',(job,)).fetchone()[0]==1
    assert c.post('/v1/jobs/'+job+'/retry',json={}).status_code==200

@pytest.mark.parametrize('payload',[
    'not json','{}','{"memories":null}',
    '{"memories":[{"content":"虚构事实","kind":"fact","evidence":"不存在","explicit":true}]}',
    '{"memories":[{"content":"事实","kind":"bad","evidence":"真实","explicit":true}]}',
])
def test_native_json_validation(tmp_path,payload):
    provider=XjtuProvider(Config(tmp_path))
    provider.complete=lambda messages:payload
    with pytest.raises(ValueError):provider.extract('真实原文')

def test_backup_allowlist_and_verification(tmp_path):
    home=tmp_path/'home'
    (home/'.codex'/'sessions').mkdir(parents=True)
    (home/'.codex'/'sessions'/'one.jsonl').write_text('{"type":"message"}\n','utf-8')
    (home/'.codex'/'auth.json').write_text('private credential','utf-8')
    destination=tmp_path/'backups'
    result=backup_local(home,destination)
    assert result['files']==1
    assert verify_local_backup(result['archive'],result['key_file'])=={'verified':True,'files':1}
    assert 'auth.json' not in Path(result['manifest']).read_text('utf-8')
    assert b'private credential' not in Path(result['archive']).read_bytes()

@pytest.mark.parametrize('client',['claude','codex'])
def test_install_preserves_existing_config(tmp_path,monkeypatch,client):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'private'))
    home=tmp_path/'home';(home/'.claude').mkdir(parents=True);(home/'.codex').mkdir()
    settings={'hooks':{'Stop':[{'hooks':[{'type':'command','command':'keep-this-hook'}]}]},'permissions':{'allow':['Read']}}
    (home/'.claude'/'settings.json').write_text(json.dumps(settings),'utf-8')
    (home/'.codex'/'config.toml').write_text('model = "keep-this-model"\n','utf-8')
    (home/'.codex'/'hooks.json').write_text(json.dumps(settings),'utf-8')
    install_client(client,home)
    install_client(client,home)
    hook_file=home/('.claude/settings.json' if client=='claude' else '.codex/hooks.json')
    saved=json.loads(hook_file.read_text('utf-8'))
    assert saved['permissions']==settings['permissions']
    assert len(saved['hooks']['Stop'])==2
    assert saved['hooks']['Stop'][0]['hooks'][0]['command']=='keep-this-hook'
    assert 'keep-this-model' in (home/'.codex'/'config.toml').read_text('utf-8')

CASES=[
('中文写作','说明文档优先使用中文','文档 中文'),
('结论先行','项目报告先展示核心结论','报告 结论'),
('字体','中文字体使用微软雅黑','中文 字体'),
('无弹窗','后台命令不要弹出终端窗口','后台 终端'),
('日期','文件名使用年月日日期','文件名 日期'),
('来源','知识结论必须保留原始来源','结论 来源'),
('备份','每周导出知识库备份','知识库 备份'),
('数据库','项目数据库采用SQLite','数据库 SQLite'),
('接口','所有客户端使用统一API接口','客户端 API'),
('分离','项目A与项目B知识要隔离','知识 隔离'),
('审查','代码提交前检查修改差异','代码 差异'),
('邮件','邮件发送前确认收件人','邮件 收件人'),
('预算','实验需要设定预算上限','实验 预算'),
('测试','发布前必须通过验收测试','发布 测试'),
('回滚','部署时保留上一版用于回滚','部署 回滚'),
('模型','记忆提炼调用交晓智API','提炼 交晓智'),
('安全','凭据只保存在私有目录','凭据 私有'),
('版本','每次纠错都保留版本历史','纠错 历史'),
('事实','助手猜测不能作为用户事实','助手 猜测'),
('导入','先备份再精选导入近期会话','备份 会话'),
('原文','搜索结果可以追溯原文','搜索 原文'),
('个人','个人偏好在多个项目共用','个人 偏好'),
('候选','不确定的记忆先进入候选区','记忆 候选'),
('知识','笔记作为知识库的输入资料','笔记 输入'),
('迁移','换账号之后继续使用历史知识','账号 历史'),
('撤销','客户端密钥可以单独撤销','密钥 撤销'),
('权限','未登录用户不能读取知识库','登录 读取'),
('流程','标准操作流程写成独立条目','流程 条目'),
('恢复','恢复备份时校验内容完整性','恢复 完整性'),
('指标','统计检索命中率与提炼成功数','统计 命中率'),
]
@pytest.mark.parametrize('title,content,query',CASES)
def test_chinese_top_five_retrieval(service,title,content,query):
    c,app,alice,bob=service
    for name,text,q in CASES:app.state.store.add(alice,'',text,title=name)
    expected=next(x for x in app.state.store.listing(alice) if x['title']==title)
    found=c.get('/v1/search',params={'q':query,'limit':5}).json()['items']
    assert expected['id'] in {r['id'] for r in found}


def test_confirmed_format_repair_and_role_provenance(tmp_path):
    source=json.dumps([{'role':'user','content':'请记住，我更喜欢中文。'}],ensure_ascii=False)
    good=json.dumps({'memories':[{'content':'用户喜欢中文','kind':'preference','evidence':'我更喜欢中文','explicit':True}]},ensure_ascii=False)
    provider=XjtuProvider(Config(tmp_path))
    replies=iter(['not-json',good])
    provider.complete=lambda messages:next(replies)
    assert provider.extract(source)[0]['explicit'] is True
    provider.complete=lambda messages:good
    assert provider.extract('助手建议：我更喜欢中文')[0]['explicit'] is False

def test_foreign_semantic_result_cannot_escape_owner(service):
    c,app,alice,bob=service
    other=app.state.store.add(bob,'','其他用户的私密知识')
    app.state.engine.index.search_ids=lambda *args:[other['id']]
    assert c.get('/v1/search',params={'q':'私密知识'}).json()['items']==[]


def test_extraction_quotes_match_decoded_transcript(tmp_path):
    source=json.dumps([{'role':'user','content':'请记住路径 C:\\work\\notes，\n后续复用。'}],ensure_ascii=False)
    reply=json.dumps({'memories':[{'content':'知识路径为 C:\\work\\notes','kind':'fact','evidence':'路径 C:\\work\\notes，\n后续复用','explicit':True}]},ensure_ascii=False)
    provider=XjtuProvider(Config(tmp_path))
    provider.complete=lambda messages:reply
    assert provider.extract(source)[0]['explicit'] is True
