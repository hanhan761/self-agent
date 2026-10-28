"""Explicit historical import: streamed roles, private snapshots, stable replay IDs."""
from pathlib import Path
import hashlib,json,re
from .hooks import canonical_path,redact_secrets
from .messages import timestamp

NOISE=('<codex_internal_context','<user_action','<external_codex_apps_open_page','# AGENTS.md instructions','<environment_context>','<permissions instructions>','<subagent_notification>','<collaboration_','<turn_aborted>','<system-reminder>')
LINE_LIMIT=8*1024**2

def iter_messages(filename,client,*,home=None,stats=None,snapshot_bytes=None):
    path=Path(filename).resolve();base=canonical_path(Path(home or Path.home())/('.codex' if client=='codex' else '.claude'))
    if not canonical_path(path).is_relative_to(base):raise ValueError('untrusted_transcript_path')
    stats=stats if stats is not None else {};remaining=path.stat().st_size if snapshot_bytes is None else snapshot_bytes
    if remaining<0 or client not in ('codex','claude'):raise ValueError('invalid_history_source')
    sha=hashlib.sha256();cwd='';excluded=False;line_number=0
    def count(key,n=1):stats[key]=stats.get(key,0)+n
    with path.open('rb') as stream:
        while remaining:
            raw=stream.readline(min(LINE_LIMIT+1,remaining));remaining-=len(raw);sha.update(raw);line_number+=1
            if not raw:break
            if not raw.endswith(b'\n'):
                if remaining and len(raw)>LINE_LIMIT:
                    count('oversized_lines')
                    while remaining and not raw.endswith(b'\n'):
                        raw=stream.readline(min(LINE_LIMIT,remaining));remaining-=len(raw);sha.update(raw)
                    continue
            prefix=raw[:1024]
            if client=='codex' and not (b'"session_meta"' in prefix or re.search(rb'"type"\s*:\s*"message"',prefix)):
                count('runtime_lines');continue
            try:row=json.loads(raw)
            except (ValueError,UnicodeDecodeError):count('invalid_lines');continue
            if client=='codex':
                if row.get('type')=='session_meta':
                    meta=row.get('payload',{});cwd=meta.get('cwd','');source=meta.get('source')
                    excluded=source=='exec' or isinstance(source,dict) and 'subagent' in source
                    if excluded:count('excluded_automated_sessions');break
                    continue
                item=row.get('payload',{});role=item.get('role')
                if row.get('type')!='response_item' or item.get('type')!='message' or role not in ('user','assistant'):continue
                if role=='assistant' and item.get('phase') not in (None,'final'):continue
                parts=[p['text'] for p in item.get('content',[]) if isinstance(p,dict) and p.get('type') in ('input_text','output_text') and isinstance(p.get('text'),str)]
                parts=[part for part in parts if not part.lstrip().startswith(NOISE)]
                content='\n'.join(parts)
            else:
                if row.get('isSidechain') or row.get('isMeta'):count('automated_rows');continue
                cwd=row.get('cwd') or cwd;role=row.get('type');item=row.get('message',{})
                if role not in ('user','assistant'):continue
                content=item.get('content','')
                if isinstance(content,list):content='\n'.join(p['text'] for p in content if isinstance(p,dict) and p.get('type')=='text' and isinstance(p.get('text'),str))
            if not isinstance(content,str) or not content.strip():continue
            if content.lstrip().startswith(NOISE):count('host_injections');continue
            try:observed=timestamp(row.get('timestamp'),None)
            except ValueError:count('invalid_times');continue
            if observed is None:count('unknown_time');continue
            if not cwd:count('unattributed_messages');continue
            identity=hashlib.sha256(raw).hexdigest()
            if role=='user' and content.startswith('<send_user_message_question_reply>'):
                try:replies=json.loads(content.split('>',1)[1].rsplit('</send_user_message_question_reply>',1)[0])
                except (ValueError,IndexError):count('invalid_question_replies');continue
                for n,reply in enumerate(replies):
                    if not isinstance(reply,dict) or not isinstance(reply.get('answer'),str):continue
                    if isinstance(reply.get('question'),str):yield {'id':identity+':question:'+str(n),'role':'assistant','content':reply['question'],'observed_at':observed,'cwd':cwd,'line':line_number}
                    count('user_messages');yield {'id':identity+':answer:'+str(n),'role':'user','content':reply['answer'],'observed_at':observed,'cwd':cwd,'line':line_number}
                continue
            count(role+'_messages');yield {'id':identity,'role':role,'content':content,'observed_at':observed,'cwd':cwd,'line':line_number}
    stats['prefix_sha256']=sha.hexdigest();stats['snapshot_bytes']=snapshot_bytes if snapshot_bytes is not None else path.stat().st_size


def redact_history(text):
    """Yelp detectors run locally with no verification/network filters."""
    from detect_secrets.settings import transient_settings,get_plugins
    from detect_secrets.core.scan import scan_line
    plugins=[{'name':name} for name in ('AWSKeyDetector','AzureStorageKeyDetector','BasicAuthDetector','GitHubTokenDetector','GitLabTokenDetector','JwtTokenDetector','KeywordDetector','OpenAIDetector','PrivateKeyDetector','SlackDetector','StripeDetector')]
    plugins += [{'name':'Base64HighEntropyString','limit':4.5},{'name':'HexHighEntropyString','limit':3.0}]
    cleaned=redact_secrets(text)
    if cleaned.startswith('[包含凭据材料'):return cleaned
    with transient_settings({'plugins_used':plugins,'filters_used':[]}):
        checks={plugin.secret_type:plugin for plugin in get_plugins()}
        lines=[]
        for line in cleaned.splitlines(keepends=True):
            secrets=set()
            for candidate in scan_line(line):
                value=candidate.secret_value
                if not value:continue
                plugin=checks[candidate.type]
                # Ad-hoc scan_line exposes low-entropy candidates for diagnostics.
                if hasattr(plugin,'calculate_shannon_entropy') and plugin.calculate_shannon_entropy(value)<=plugin.entropy_limit:continue
                secrets.add(value)
            if any(len(value)<8 for value in secrets):
                # Never replace a one-character credential throughout unrelated prose.
                lines.append('[REDACTED]\n')
                continue
            for value in sorted(secrets,key=len,reverse=True):line=line.replace(value,'[REDACTED]')
            lines.append(line)
    return ''.join(lines)



def history_batches(messages,limit=12000):
    """Preserve whole role envelopes and one bounded preceding answer per user turn."""
    from .messages import batches
    previous=None;pending=[];size=2
    for message in messages:
        if message['role']=='assistant':previous=message;continue
        if not message['content'].strip():continue
        pair=[]
        if previous:pair.append({**previous,'content':previous['content'][:1200]})
        pair.append(message);previous=None
        # Reuse the service's role-aware fragmenter; never slice JSON strings.
        for envelope in batches(pair,limit=limit):
            width=len(json.dumps(envelope,ensure_ascii=False))
            if pending and size+width>limit:yield pending;pending=[];size=2
            pending.extend(envelope);size+=width
    if pending:yield pending


def stage_history(config,store,tasks,results,project_labels=None):
    """Install validated extraction checkpoints; live capture never claims these jobs."""
    from .provider import validate_extraction
    from .capacity import Capacity
    if not config.local or not config.local_user_id:raise ValueError('local_import_only')
    uid=config.local_user_id;staged=[]
    with store.tx() as db:
        if not db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():raise ValueError('unknown_import_owner')
        for project,label in (project_labels or {}).items():
            if project and isinstance(label,str) and 0<len(label)<=120:
                db.execute('INSERT OR REPLACE INTO project_labels VALUES(?,?,?)',(uid,project,label))
    for task in tasks:
        if task['id'] not in results:continue
        items=validate_extraction(task['text'],json.dumps({'memories':results[task['id']]},ensure_ascii=False),require_scope=True)
        for personal in (True,False):
            chosen=[m for m in items if m['scope']!='session' and not m.get('temporary') and (m['scope']=='personal')==personal]
            if not chosen:continue
            external='history:v2:'+task['id']+(':+personal' if personal else ':+project')
            with store.tx() as db:
                old=db.execute('SELECT j.id,j.state,x.items FROM sources s JOIN jobs j ON j.source_id=s.id LEFT JOIN job_extractions x ON x.job_id=j.id WHERE s.user_id=? AND s.project=? AND s.external_id=? AND s.hash=?',(uid,task['project'],external,hashlib.sha256(task['text'].encode()).hexdigest())).fetchone()
                if old:
                    if old['items'] is None or json.loads(old['items'])!=chosen:raise ValueError('frozen_history_result_changed')
                    staged.append({'id':old['id'],'scope':'' if personal else task['project'],'observed':max(m.get('observed_at') or 0 for m in chosen),'task':task['id']})
                    continue
            with Capacity(config).reserve(len(task['text'].encode())*3+65536,jobs=1):
                with store.tx() as db:
                    sid,created=store.source(uid,task['project'],'历史对话 · '+(project_labels or {}).get(task['project'],'本机项目'),task['text'],'history',external)
                    if created:db.execute('UPDATE sources SET created=? WHERE id=?',(task['observed'],sid))
                    jid=store.enqueue(uid,sid)
                    db.execute("UPDATE jobs SET state='history_pending' WHERE id=?",(jid,))
                    db.execute('INSERT INTO job_extractions VALUES(?,?,0)',(jid,json.dumps(chosen,ensure_ascii=False)))
            staged.append({'id':jid,'scope':'' if personal else task['project'],'observed':max(m.get('observed_at') or 0 for m in chosen),'task':task['id']})
    return sorted(staged,key=lambda row:(row['observed'],row['id']))
