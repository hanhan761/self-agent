"""Stop only controlled acceptance instances, through their authenticated endpoint."""
import json,sys,time
from pathlib import Path
import httpx
base=Path(sys.argv[1]).resolve()
for directory in base.glob('acceptance-*/data'):
    if not directory.resolve().is_relative_to(base):raise ValueError('outside_test_root')
    path=directory/'local-client.json'
    if not path.exists():continue
    client=json.loads(path.read_text('utf-8'))
    try:
        with httpx.Client(trust_env=False,timeout=2) as http:
            r=http.get(client['url']+'/healthz')
            if r.json().get('local_instance_id')!=client['instance_id']:continue
            token=Path(client['token_file']).read_text('utf-8').strip()
            r=http.post(client['url']+'/api/local/stop',json={},headers={'Authorization':'Bearer '+token});r.raise_for_status()
            print(json.dumps({'instance':directory.parent.name,'stop_requested':True}))
    except (httpx.HTTPError,ValueError):pass
    (directory/'launch.json').unlink(missing_ok=True)
time.sleep(3)
