"""Durable local capture. Hooks only fsync new, redacted batches; the worker ingests them."""
import hashlib
import json
import os
import time
from pathlib import Path
from .lock import ProcessLock


def atomic_json(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_name(path.name+'.tmp')
    with temp.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False)
        stream.flush();os.fsync(stream.fileno())
    temp.replace(path)


def capture(config,client,event,project):
    from .hooks import canonical_path,normalized_messages,redact_secrets
    from .messages import batches,timestamp
    filename=event.get('transcript_path')
    if not filename:return
    root=Path(config['local_data_dir'])
    identity=hashlib.sha256((client+':'+str(canonical_path(filename))).encode()).hexdigest()
    cursor=root/'cursors'/(identity+'.json')
    cursor.parent.mkdir(parents=True,exist_ok=True)
    with ProcessLock(cursor.with_suffix('.lock')):
        state=json.loads(cursor.read_text('utf-8')) if cursor.exists() else {'count':0}
        rows=normalized_messages(filename,client)
        count=state.get('count',0)
        if count>len(rows):count=0
        # Do not harvest pre-install transcripts or unknown timestamps implicitly.
        since=config['local_started_at']
        messages=[{**m,'content':redact_secrets(m['content'])} for m in rows[count:]
                  if timestamp(m.get('observed_at'),0)>=since]
        # Keep one bounded prior answer so a new user confirmation has context.
        if messages and any(m['role']=='user' for m in messages):
            previous=next((m for m in reversed(rows[:count]) if m['role']=='assistant' and timestamp(m.get('observed_at'),0)>=since),None)
            if previous:messages.insert(0,{**previous,'content':redact_secrets(previous['content'][:1200])})
        if not messages and state.get('count')==len(rows):return
        pending=[];growth=0;new_files=0
        for number,batch in enumerate(batches(messages)) if messages else []:
            key=identity+':'+str(count)+':'+str(number)
            destination=root/'inbox'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            value={'external_id':key,'project':project,'messages':batch,'client':client}
            size=len(json.dumps(value,ensure_ascii=False).encode('utf-8'))
            previous_size=destination.stat().st_size if destination.exists() else 0
            growth+=max(0,size-previous_size);new_files+=not destination.exists();pending.append((destination,value))
        from .capacity import Capacity
        with Capacity.for_root(root).reserve(growth+4096,batches=new_files,capture_bytes=growth):
            for destination,value in pending:atomic_json(destination,value)
            # Advance only after every batch is durably published. Replay is idempotent.
            atomic_json(cursor,{'count':len(rows)})


def drain(config,store):
    from .messages import batches
    inbox=config.data_dir/'inbox'
    if not inbox.exists():return
    for file in sorted(inbox.glob('*.json'))[:20]:
        try:
            if file.stat().st_size>1024**2:raise ValueError('oversized_capture')
            item=json.loads(file.read_text('utf-8'))
            envelopes=list(batches(item['messages']))
            if len(envelopes)!=1:raise ValueError('invalid_capture_batch')
            text=json.dumps(item['messages'],ensure_ascii=False)
            has_user=any(m['role']=='user' for m in item['messages'])
            with store.tx() as db:
                old=db.execute('SELECT s.id,j.id job FROM sources s LEFT JOIN jobs j ON j.source_id=s.id AND j.user_id=s.user_id WHERE s.user_id=? AND s.project=? AND s.external_id=? AND s.hash=?',(config.local_user_id,item['project'],item['external_id'],hashlib.sha256(text.encode()).hexdigest())).fetchone()
            if old and (not has_user or old['job']):file.unlink();continue
            from .capacity import Capacity
            with Capacity(config).reserve(len(text.encode())*3+65536,jobs=int(has_user)):
                sid,_=store.source(config.local_user_id,item['project'],item['client']+' 会话增量',text,'conversation',item['external_id'])
                # Assistant-only replies remain available as sources, without an LLM request.
                if has_user:store.enqueue(config.local_user_id,sid)
                file.unlink()
        except (ValueError,KeyError,TypeError):
            quarantine=config.data_dir/'capture-errors';quarantine.mkdir(exist_ok=True)
            file.replace(quarantine/file.name)
        except OSError:
            return
