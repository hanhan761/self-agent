"""Isolated, real native-provider acceptance. No production user content or keys."""
from dataclasses import replace
from pathlib import Path
import json,secrets,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from self_agent.config import Config
from self_agent.store import Store
from self_agent.auth import Auth
from self_agent.engine import Engine


def main():
    config=Config.load()
    directory=config.data_dir/'acceptance'/('learning-'+secrets.token_hex(8))
    directory.mkdir(parents=True,mode=0o700)
    config=replace(config,data_dir=directory,semantic=False)
    store=Store(directory/'memory.sqlite3')
    uid=Auth(store).create_user('synthetic-learning-test',secrets.token_urlsafe(24))
    engine=Engine(config,store)
    calls=[];complete=engine.provider.complete
    def measured(messages):
        started=time.time()
        answer=complete(messages)
        calls.append({'confirmed':True,'seconds':round(time.time()-started,2)})
        (directory/('native-'+str(len(calls))+'.json')).write_text(json.dumps({'messages':messages,'response':answer},ensure_ascii=False),'utf8')
        return answer
    engine.provider.complete=measured
    stages=[]
    def learn(name,text,project='alpha'):
        content=json.dumps([{'id':name,'role':'user','content':text,'observed_at':time.time()}],ensure_ascii=False)
        sid,_=store.source(uid,project,name,content,'conversation',name)
        jid=store.enqueue(uid,sid);engine.process_one()
        state=store.db.execute('SELECT state,error FROM jobs WHERE id=?',(jid,)).fetchone()
        assert state['state']=='done',name+':'+state['state']+':'+state['error']
        stages.append(name);print(json.dumps({'stage':name,'state':'done'}),flush=True)
    try:
        learn('personal','我平时阅读技术说明喜欢中文，所有项目默认都用中文。这是一项长期偏好。')
        personal=store.listing(uid)
        assert len(personal)==1 and personal[0]['project']=='','personal_scope'
        first=personal[0]['id']
        learn('equivalent','我一贯更习惯用中文看技术解释，作为跨项目的默认习惯。')
        assert len(store.listing(uid))==1,'equivalent_merge'
        assert len(store.get(uid,first)['evidence'])>=2,'multiple_evidence'
        learn('replacement','我改变主意了：以后所有项目默认都用英文解释，不再以中文为默认。这是新的长期偏好。')
        assert store.get(uid,first)['status']=='superseded','explicit_replacement'
        active=store.listing(uid)
        assert len(active)==1 and '英文' in active[0]['content'],'new_preference'
        learn('project_exception','只在项目 alpha：技术说明请用中文。其他项目继续我的英文默认偏好。')
        found=engine.search(uid,'技术说明语言',project='alpha')
        assert any(m['project']=='alpha' for m in found),'project_memory'
        assert all(m['project']=='alpha' for m in found),'project_override'
        found=engine.search(uid,'技术说明语言',project='beta')
        assert found and all(not m['project'] for m in found),'cross_project_personal'
        before=len(store.listing(uid))
        learn('temporary','这次请先用中文快速回答一下，之后仍按长期偏好来。')
        assert len(store.listing(uid))==before,'temporary_not_durable'
        learn('deadline','请记住，项目 alpha 的联调状态为 staging，仅适用到2026年11月1日，之后不再作为有效状态。')
        deadlines=[m for m in store.listing(uid) if m['valid_until'] is not None]
        assert deadlines and all(m['valid_until']>time.time() for m in deadlines),'explicit_deadline'
        report={'passed':True,'model':config.xjtu_model,'confirmed_native_calls':len(calls),'stages':stages,'calls':calls,'test_data_isolated':True}
    except Exception as exc:
        report={'passed':False,'model':config.xjtu_model,'confirmed_native_calls':len(calls),'stages':stages,'failure':str(exc),'test_data_isolated':True}
        (directory/'report.json').write_text(json.dumps(report,indent=2),'utf8')
        print(json.dumps(report),flush=True);raise
    finally:store.close()
    (directory/'report.json').write_text(json.dumps(report,indent=2),'utf8')
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
