import json,os,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]);source=Path(sys.argv[2]);python=sys.argv[3]
home=root/'home';transcript=next((home/'.codex/sessions').glob('*.jsonl'))
env={**os.environ,'SELF_AGENT_CLIENT_CONFIG':str(root/'client.json'),'USERPROFILE':str(home),'HOME':str(home)}
samples=[]
for _ in range(20):
    start=time.perf_counter()
    p=subprocess.run([python,str(source/'scripts/hook_runner.py'),'codex'],input=json.dumps({'hook_event_name':'Stop','transcript_path':str(transcript),'cwd':str(source)}).encode(),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,cwd=source,timeout=12,creationflags=subprocess.CREATE_NO_WINDOW)
    assert p.returncode==0;samples.append(time.perf_counter()-start)
result={'samples':len(samples),'p95_seconds':sorted(samples)[18],'max_seconds':max(samples),'no_new_model_requests':True}
(root/'stop-benchmark.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
