from pathlib import Path
import hashlib,json,time
from .client import request
from .hooks import project_id,redact_secrets,canonical_path
from .local_backup import inventory
from .history import iter_messages,history_batches,redact_history


def import_recent(project_dir,days=30,home=None):
    root=canonical_path(project_dir)
    if not 1<=days<=36500:raise ValueError('invalid_history_days')
    cutoff=time.time()-days*86400
    imported,skipped,packets=0,0,0
    for name,file in inventory(home).items():
        if file.suffix=='.md' and file.name in ('AGENTS.md','CLAUDE.md'):
            request('POST','/v1/sources',body={'content':redact_history(file.read_text('utf-8'))[:120000],'project':'','title':file.name,'kind':'rules','external_id':'rules:'+name})
            imported+=1
            continue
        if file.suffix!='.jsonl' or file.stat().st_mtime<cutoff:continue
        client='claude' if '.claude' in file.parts else 'codex'
        groups={}
        for row in iter_messages(file,client,home=home):
            recorded=canonical_path(row['cwd'])
            if recorded!=root and not recorded.is_relative_to(root):continue
            if row['role']=='user' and row['observed_at']<cutoff:continue
            content=redact_history(row['content'][:1200] if row['role']=='assistant' else row['content'])
            if content.startswith('[包含凭据材料') or content.strip()=='[REDACTED]':continue
            scope=project_id(recorded)
            groups.setdefault(scope,[]).append({**row,'content':content})
        count=0
        for scope,rows in groups.items():
            for batch in history_batches(rows):
                identity=hashlib.sha256((client+':'+str(canonical_path(file))+':'+json.dumps(batch,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()
                request('POST','/v1/sources',body={'messages':batch,'project':scope,'title':client+' 历史会话','kind':'conversation','external_id':'history:'+identity},timeout=30)
                count+=1
        if count:imported+=1;packets+=count
        else:skipped+=1
    return {'queued_files':imported,'queued_packets':packets,'skipped_unrelated_or_unattributed':skipped,'days':days}
