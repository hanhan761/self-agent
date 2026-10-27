"""Merge only self-agent-owned config; preserve all other tools and hooks."""
from datetime import datetime,timezone
from pathlib import Path
import json
import os
import sys
from .config import private_root


def save_json(file,value):
    file.parent.mkdir(parents=True,exist_ok=True)
    temp=file.with_name(file.name+'.self-agent.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n','utf-8')
    temp.replace(file)

def backup(file,root):
    if file.exists():
        root.mkdir(parents=True,exist_ok=True,mode=0o700)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target=root/(file.name+'.'+stamp)
        target.write_bytes(file.read_bytes())
        target.chmod(0o600)

def owned_runner(filename, expected):
    try:
        return Path(filename).is_file() and Path(filename).read_bytes() == Path(expected).read_bytes()
    except (OSError, ValueError):
        return False


def owned_hook(item, client, runner):
    import re
    for hook in item.get('hooks', []):
        match = re.fullmatch(r'"[^"]+" ("(?:[^"\\]|\\.)*") ' + client, hook.get('command', ''))
        if match:
            try:
                if owned_runner(json.loads(match[1]), runner):
                    return True
            except ValueError:
                pass
        # Codex's Windows shell is PowerShell: quoted executable paths require &.
        match = re.fullmatch(r"(?:\$env:PATHEXT = '\.COM;\.EXE;\.BAT;\.CMD'; )?& '(?:[^']|'')*' '((?:[^']|'')*)' " + re.escape(client), hook.get('command', ''))
        if match and owned_runner(match[1].replace("''", "'"), runner):
            return True
    return False


def hook_command(client,python,runner):
    if os.name=='nt' and client=='codex':
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        return "$env:PATHEXT = '.COM;.EXE;.BAT;.CMD'; & "+quote(python)+' '+quote(runner)+' '+client
    return json.dumps(str(python))+' '+json.dumps(str(runner))+' '+client


def install_client(client,home=None,repo=None,python=None):
    home=Path(home or Path.home())
    repo=Path(repo or Path(__file__).resolve().parents[1]).resolve()
    python=str(python or sys.executable)
    # pythonw preserves redirected hook pipes without allocating a console.
    if os.name=='nt':
        candidate=Path(python).with_name('pythonw.exe')
        if candidate.exists():python=str(candidate)
    runner=str(repo/'scripts'/'hook_runner.py')
    mcp_runner=str(repo/'scripts'/'mcp_runner.py')
    command=hook_command(client,python,runner)
    backups=private_root()/'config-backups'
    if client=='claude':
        file=home/'.claude.json'
        data=json.loads(file.read_text('utf-8')) if file.exists() else {}
        servers=data.setdefault('mcpServers',{})
        expected={'command':python,'args':[mcp_runner]}
        previous=servers.get('self_agent')
        ours=previous and isinstance(previous.get('args'),list) and len(previous['args'])==1 and owned_runner(previous['args'][0],mcp_runner)
        if previous and previous!=expected and not ours:raise ValueError('已有 self_agent MCP 配置，请先核对')
        backup(file,backups);servers['self_agent']=expected;save_json(file,data)
        hook_file=home/'.claude'/'settings.json'
    else:
        file=home/'.codex'/'config.toml'
        text=file.read_text('utf-8') if file.exists() else ''
        begin,end='# self-agent:begin','# self-agent:end'
        block=begin+'\n[mcp_servers.self_agent]\ncommand = '+json.dumps(python)+'\nargs = ['+json.dumps(mcp_runner)+']\n'+end+'\n'
        if begin in text:
            if end not in text:raise ValueError('self_agent 配置标记不完整')
            start=text.index(begin);finish=text.index(end,start)+len(end)
            text=text[:start]+block+text[finish:].lstrip('\n')
        else:
            if '[mcp_servers.self_agent]' in text:raise ValueError('已有 self_agent MCP 配置，请先核对')
            text=text.rstrip()+'\n\n'+block
        backup(file,backups);file.parent.mkdir(parents=True,exist_ok=True);file.write_text(text,'utf-8')
        hook_file=home/'.codex'/'hooks.json'
    hooks=json.loads(hook_file.read_text('utf-8')) if hook_file.exists() else {}
    root_hooks=hooks.setdefault('hooks',{})
    for event in ('SessionStart','UserPromptSubmit','Stop'):
        entries=root_hooks.setdefault(event,[])
        kept=[]
        for item in entries:
            handlers=[h for h in item.get('hooks',[]) if h.get('command')!=command and not owned_hook({'hooks':[h]},client,runner)]
            if handlers:kept.append({**item,'hooks':handlers})
        entries[:]=kept
        entries.append({'hooks':[{'type':'command','command':command,'timeout':6 if event!='Stop' else 12}]})
    backup(hook_file,backups);save_json(hook_file,hooks)
    return {'client':client,'configured':True,'backup_directory':str(backups),'hook_review_required':client=='codex'}


def remove_client(client,home=None,repo=None):
    """Remove this installation's entries only. Never restore an entire old user config."""
    home=Path(home or Path.home());repo=Path(repo or Path(__file__).resolve().parents[1]).resolve()
    runner=str(repo/'scripts/hook_runner.py');mcp_runner=str(repo/'scripts/mcp_runner.py')
    backups=private_root()/'config-backups'
    if client=='claude':
        file=home/'.claude.json'
        if file.exists():
            data=json.loads(file.read_text('utf-8'));server=data.get('mcpServers',{}).get('self_agent')
            if server and server.get('args')==[mcp_runner]:
                backup(file,backups);del data['mcpServers']['self_agent'];save_json(file,data)
        hook_file=home/'.claude/settings.json'
    else:
        file=home/'.codex/config.toml'
        if file.exists():
            import tomllib
            text=file.read_text('utf-8');server=tomllib.loads(text).get('mcp_servers',{}).get('self_agent',{})
            begin,end='# self-agent:begin','# self-agent:end'
            if server.get('args')==[mcp_runner] and begin in text and end in text:
                start=text.index(begin);finish=text.index(end,start)+len(end)
                backup(file,backups);file.write_text(text[:start]+text[finish:],'utf-8')
        hook_file=home/'.codex/hooks.json'
    if hook_file.exists():
        data=json.loads(hook_file.read_text('utf-8'))
        changed=False
        for event,items in data.get('hooks',{}).items():
            kept=[]
            for item in items:
                handlers=[h for h in item.get('hooks',[]) if not owned_hook({'hooks':[h]},client,runner)]
                changed=changed or len(handlers)!=len(item.get('hooks',[]))
                if handlers:kept.append({**item,'hooks':handlers})
            data['hooks'][event]=kept
        if changed:backup(hook_file,backups);save_json(hook_file,data)
    return {'client':client,'removed':True}
