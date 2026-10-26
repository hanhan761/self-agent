"""Short host hooks; failures never block the user's agent session."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
from urllib.parse import urlparse
from .client import request
from .config import private_root

SECRET_WORDS=('access_key_secret','accesskey secret','-----begin private key','-----begin rsa private key')

def project_id(cwd=None):
    cwd=Path(cwd or os.getcwd()).resolve()
    git='C:/Program Files/Git/cmd/git.exe' if os.name=='nt' else shutil.which('git')
    if git:
        result=subprocess.run([git,'-C',str(cwd),'config','--get','remote.origin.url'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=2,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode==0:
            remote=result.stdout.strip().removesuffix('.git')
            if remote.startswith('git@'):remote=remote[4:].replace(':','/',1)
            else:
                parsed=urlparse(remote)
                remote=(parsed.hostname or '')+parsed.path
            if remote:return remote.lower()
    return 'local:'+hashlib.sha256(str(cwd).encode()).hexdigest()[:16]


def normalized_messages(filename,client):
    path=Path(filename).resolve()
    allowed=(Path.home()/('.claude' if client=='claude' else '.codex')).resolve()
    if not path.is_relative_to(allowed) or not path.is_file():raise ValueError('untrusted_transcript_path')
    if path.stat().st_size>100*1024**2:raise ValueError('transcript_too_large')
    rows=[]
    with path.open('r',encoding='utf-8') as stream:
        for raw in stream:
            try:row=json.loads(raw)
            except ValueError:continue
            if client=='claude' and row.get('type') in ('user','assistant'):
                message=row.get('message',{})
                content=message.get('content')
                if isinstance(content,list):content='\n'.join(x['text'] for x in content if isinstance(x,dict) and x.get('type')=='text' and isinstance(x.get('text'),str))
                if isinstance(content,str):rows.append({'role':row['type'],'content':content})
            elif client=='codex' and row.get('type')=='response_item':
                item=row.get('payload',{})
                if item.get('type')!='message' or item.get('role') not in ('user','assistant'):continue
                content='\n'.join(x['text'] for x in item.get('content',[]) if isinstance(x,dict) and x.get('type') in ('input_text','output_text') and isinstance(x.get('text'),str))
                if content:rows.append({'role':item['role'],'content':content})
    return rows


def redact_secrets(text):
    import re
    if any(w in text.lower() for w in SECRET_WORDS):return '[包含凭据材料，已排除本段]'
    text=re.sub(r'\b(?:sk-|sa_)[A-Za-z0-9_-]{12,}\b','[REDACTED]',text)
    text=re.sub(r'(?im)((?:api[_ -]?key|token|password|secret|密码|密钥)\s*[:=：]\s*)\S+',r'\1[REDACTED]',text)
    return text


def handle(client,event):
    name=event.get('hook_event_name','')
    project=project_id(event.get('cwd'))
    if name in ('SessionStart','UserPromptSubmit'):
        prompt=event.get('prompt') or '当前项目长期偏好 已确认决策 项目背景'
        items=request('GET','/v1/search',params={'q':prompt[:2000],'project':project,'limit':8},timeout=1.8)['items']
        lines=['以下是历史记忆，仅供参考；当前用户要求优先。']
        remaining=3000  # Conservative character budget for mixed Chinese/English context.
        for item in items:
            line='- '+item['content'][:800]+' [memory:'+item['id']+']'
            if len(line)>remaining:break
            lines.append(line);remaining-=len(line)
        if len(lines)>1:return {'hookSpecificOutput':{'hookEventName':name,'additionalContext':'\n'.join(lines)}}
    elif name in ('Stop','SessionEnd'):
        filename=event.get('transcript_path')
        if not filename:return {}
        rows=normalized_messages(filename,client)
        private=private_root()/'cursors';private.mkdir(parents=True,exist_ok=True)
        identity=hashlib.sha256((client+':'+str(Path(filename).resolve())).encode()).hexdigest()
        cursor=private/(identity+'.json')
        previous=json.loads(cursor.read_text('utf-8')).get('count',0) if cursor.exists() else 0
        if previous>len(rows):previous=0
        new=rows[previous:]
        if not new:return {}
        # Send bounded chunks; only advance the cursor after all are acknowledged.
        text=redact_secrets(json.dumps(new,ensure_ascii=False))
        for start in range(0,len(text),12000):
            request('POST','/v1/sources',body={'content':text[start:start+12000],'title':client+' 会话增量','project':project,'kind':'conversation','external_id':identity+':'+str(previous)+':'+str(start)},timeout=2)
        temp=cursor.with_suffix('.tmp')
        temp.write_text(json.dumps({'count':len(rows)}),'utf-8');temp.replace(cursor)
    return {}


def main(client):
    try:
        event=json.loads(sys.stdin.read(1024**2))
        result=handle(client,event)
        if result:print(json.dumps(result,ensure_ascii=False))
    except Exception:
        # Fail open for agent work. Keep the original transcript for later capture.
        return
