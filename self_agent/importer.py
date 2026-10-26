from pathlib import Path
from datetime import datetime,timezone,timedelta
import json
import time
from .client import request
from .hooks import normalized_messages,project_id,redact_secrets
from .local_backup import inventory


def import_recent(project_dir,days=30,home=None):
    root=Path(project_dir).resolve()
    cutoff=time.time()-days*86400
    files=inventory(home)
    imported,skipped=0,0
    # Long-term rules explicitly belong to the personal scope.
    for name,file in files.items():
        if file.suffix=='.md' and file.name in ('AGENTS.md','CLAUDE.md'):
            request('POST','/v1/sources',body={'content':redact_secrets(file.read_text('utf-8'))[:120000],'project':'','title':file.name,'kind':'rules','external_id':'rules:'+name})
            imported+=1
        elif file.suffix=='.jsonl' and file.stat().st_mtime>=cutoff:
            client='claude' if '.claude' in str(file) else 'codex'
            cwd=None
            with file.open('r',encoding='utf-8') as stream:
                for i,raw in enumerate(stream):
                    if i>50:break
                    try:row=json.loads(raw)
                    except ValueError:continue
                    cwd=row.get('cwd') or row.get('payload',{}).get('cwd')
                    if cwd:break
            if not cwd:
                skipped+=1;continue
            recorded=Path(cwd).resolve()
            if not (recorded==root or recorded.is_relative_to(root)):
                skipped+=1;continue
            rows=normalized_messages(file,client)
            content=redact_secrets(json.dumps(rows,ensure_ascii=False))
            for start in range(0,len(content),120000):
                request('POST','/v1/sources',body={'content':content[start:start+120000],'project':project_id(root),'title':client+' 历史会话','kind':'conversation','external_id':'history:'+name+':'+str(start)},timeout=30)
            imported+=1
    return {'imported_files':imported,'skipped_unrelated_or_unattributed':skipped,'days':days}
