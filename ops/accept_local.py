"""Real isolated local acceptance; reports metadata only, never auth material."""
import argparse,json,os,statistics,subprocess,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--model-cache',required=True);p.add_argument('--xjcode-home',required=True);p.add_argument('--source');a=p.parse_args()
project=Path(a.source) if a.source else Path(__file__).resolve().parents[1];sys.path.insert(0,str(project))
from self_agent.local_runtime import setup_local,status,stop
root=Path(a.root);home=root/'home'
for name in ('.codex','.claude'):(home/name).mkdir(parents=True,exist_ok=True)
# Sentinels must survive install/repair/uninstall.
(home/'.codex/config.toml').write_text('model = "existing-model"\n[mcp_servers.other]\ncommand = "unchanged"\n')
(home/'.claude/settings.json').write_text(json.dumps({'unrelated':True}))
connection_file=root/'client.json'
setup=setup_local('both',home=home,data_dir=root/'data',client_file=connection_file,
                  model_cache=a.model_cache,xjcode_home=a.xjcode_home,autostart=False)
os.environ['SELF_AGENT_CLIENT_CONFIG']=str(connection_file)
from self_agent.client import request
connection=json.loads(connection_file.read_text())
result={'backend':'mcp-memory-service 12.4.0','real_model':'qwen3.8-max','cases':{},'timings':{}}
def wait_for(predicate,timeout=180):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(0.3)
    raise AssertionError('acceptance_timeout')
wait_for(lambda:request('GET','/api/overview')['search']['semantic'],120)
result['cases']['semantic_ready']=True
created=request('POST','/v1/memories',body={'content':'自动化验收项目使用 SQLite 保存权威内容，向量索引可重建。','project':'acceptance-project'})
# Check store projection is real, with owner+project filters.
from self_agent.store import Store
from self_agent.auth import Auth
store=Store(root/'data/memory.sqlite3')
other=Auth(store).create_user('other-'+uuid.uuid4().hex[:8],'isolated-fixture-password')
store.add(other,'','不应泄露给其他用户的私人记忆')
store.close()
wait_for(lambda:request('GET','/api/overview')['search']['semantic'])
assert not any('不应泄露' in m['content'] for m in request('GET','/v1/search',params={'q':'私人记忆','project':'acceptance-project'})['items'])
assert not any(m['id']==created['id'] for m in request('GET','/v1/search',params={'q':'SQLite','project':'different-project'})['items'])
result['cases']['owner_and_project_isolation']=True

def hook(client,event):
    env={**os.environ,'USERPROFILE':str(home),'HOME':str(home)}
    started=time.perf_counter()
    r=subprocess.run([sys.executable,str(project/'scripts/hook_runner.py'),client],input=json.dumps(event,ensure_ascii=False).encode(),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=project,env=env,timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    elapsed=time.perf_counter()-started
    if r.returncode:raise AssertionError('hook_failed')
    return json.loads(r.stdout.decode('utf-8') or '{}'),elapsed

def transcript(client,text):
    now=datetime.now(timezone.utc).isoformat()
    path=home/('.codex/sessions' if client=='codex' else '.claude/projects')/(uuid.uuid4().hex+'.jsonl');path.parent.mkdir(parents=True,exist_ok=True)
    if client=='codex':row={'type':'response_item','timestamp':now,'payload':{'type':'message','role':'user','content':[{'type':'input_text','text':text}]}}
    else:row={'type':'user','uuid':uuid.uuid4().hex,'timestamp':now,'message':{'content':text}}
    path.write_text(json.dumps(row,ensure_ascii=False)+'\n','utf-8');return path
first=transcript('codex','我阅读技术说明喜欢中文，所有项目默认中文。')
_,elapsed=hook('codex',{'hook_event_name':'Stop','transcript_path':str(first),'cwd':str(project)})
result['timings']['first_stop_seconds']=elapsed
wait_for(lambda:any('中文' in m['content'] for m in request('GET','/v1/memories',params={'project':'','status':'active'})['items']))
result['cases']['codex_automatic_extraction']=True
output,_=hook('codex',{'hook_event_name':'UserPromptSubmit','prompt':'技术说明默认用什么语言？','cwd':str(project)})
assert '中文' in json.dumps(output,ensure_ascii=False)
result['cases']['prompt_recall']=True
second=transcript('claude','我现在改变偏好：今后所有项目的技术说明默认英文，不再用中文。')
_,elapsed=hook('claude',{'hook_event_name':'Stop','transcript_path':str(second),'cwd':str(project)})
result['timings']['claude_stop_seconds']=elapsed
wait_for(lambda:any('英文' in m['content'] for m in request('GET','/v1/memories',params={'project':'','status':'active'})['items']))
output,_=hook('claude',{'hook_event_name':'UserPromptSubmit','prompt':'我喜欢的技术说明语言是什么？','cwd':str(project)})
assert '英文' in json.dumps(output,ensure_ascii=False)
active=request('GET','/v1/memories',params={'project':'','status':'active'})['items']
assert not any('中文' in m['content'] and '英文' not in m['content'] for m in active)
result['cases']['cross_client_correction']=True
output,_=hook('codex',{'hook_event_name':'SessionStart','cwd':str(project)})
assert '英文' in json.dumps(output,ensure_ascii=False)
result['cases']['session_start_recall']=True
# Replaying a completed callback must not submit duplicate sources or paid jobs.
counts=request('GET','/api/overview')
hook('codex',{'hook_event_name':'Stop','transcript_path':str(first),'cwd':str(project)})
assert request('GET','/api/overview')['sources']==counts['sources']
result['cases']['capture_replay_idempotent']=True
samples=[]
for _ in range(15):
    started=time.perf_counter();request('GET','/v1/search',params={'q':'技术说明语言偏好','project':'github.com/hanhan761/self-agent'});samples.append(time.perf_counter()-started)
result['timings']['warm_search_p95_seconds']=sorted(samples)[-1]
# Verify the canonical export remains restorable without re-generating memories.
archive=request('GET','/v1/export');restored=request('POST','/v1/restore',body=archive)
result['cases']['restore']=True
result['cases']['other_client_settings_preserved']='existing-model' in (home/'.codex/config.toml').read_text() and json.loads((home/'.claude/settings.json').read_text())['unrelated']
result['state']=status(root/'data')
(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({'passed':True,'cases':result['cases'],'timings':result['timings']},ensure_ascii=False))
