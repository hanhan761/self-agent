"""Hash unrelated settings without exporting their values."""
import argparse,hashlib,json,sys,tomllib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('mode',choices=['before','after']);p.add_argument('--report',required=True);a=p.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from self_agent.install import owned_hook
home=Path.home();runner=str(Path(__file__).resolve().parents[1]/'scripts/hook_runner.py')
values={}
for client,rel,kind in [('codex','.codex/config.toml','toml'),('claude','.claude.json','json'),('codex','.codex/hooks.json','json'),('claude','.claude/settings.json','json')]:
    path=home/rel
    if not path.exists():values[rel]=None;continue
    raw=path.read_text('utf-8');data=tomllib.loads(raw) if kind=='toml' else json.loads(raw)
    for key in ('mcp_servers','mcpServers'):
        if key in data:data[key].pop('self_agent',None)
    for event,items in data.get('hooks',{}).items():
        if not isinstance(items,list):continue
        result=[]
        for item in items:
            remaining=[hook for hook in item.get('hooks',[]) if not owned_hook({'hooks':[hook]},client,runner)]
            if remaining:result.append({**item,'hooks':remaining})
        data['hooks'][event]=result
    values[rel]=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
file=Path(a.report)
if a.mode=='before':file.write_text(json.dumps(values,indent=2));print(json.dumps({'snapshot_created':True,'files':len(values)}))
else:
    assert json.loads(file.read_text())==values,'unrelated_settings_changed'
    print(json.dumps({'unrelated_settings_preserved':True,'files':len(values)}))
