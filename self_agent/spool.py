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
    from .hooks import normalized_messages,redact_secrets
    from .messages import batches,timestamp
    filename=event.get('transcript_path')
    if not filename:return
    root=Path(config['local_data_dir'])
    identity=hashlib.sha256((client+':'+str(Path(filename).resolve())).encode()).hexdigest()
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
        for number,batch in enumerate(batches(messages)) if messages else []:
            key=identity+':'+str(count)+':'+str(number)
            destination=root/'inbox'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            atomic_json(destination,{'external_id':key,'project':project,'messages':batch,'client':client})
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
            sid,_=store.source(config.local_user_id,item['project'],item['client']+' 会话增量',
                               text,'conversation',item['external_id'])
            store.enqueue(config.local_user_id,sid)
            file.unlink()
        except (ValueError,KeyError,TypeError):
            quarantine=config.data_dir/'capture-errors';quarantine.mkdir(exist_ok=True)
            file.replace(quarantine/file.name)
        except OSError:
            return
