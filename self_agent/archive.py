"""Portable user-scoped backups; no passwords, sessions, API keys or provider secrets."""
import base64
import hashlib
import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .store import words,fingerprint


def export_user(store,uid):
    with store.tx() as db:
        sources=[dict(r) for r in db.execute('SELECT * FROM sources WHERE user_id=?',(uid,))]
        memories=[dict(r) for r in db.execute('SELECT * FROM memories WHERE user_id=?',(uid,))]
        history=[dict(r) for r in db.execute('SELECT v.* FROM versions v JOIN memories m ON m.id=v.memory_id WHERE m.user_id=?',(uid,))]
        metadata=[dict(r) for r in db.execute('SELECT x.* FROM memory_metadata x JOIN memories m ON m.id=x.memory_id WHERE m.user_id=?',(uid,))]
        evidence=[dict(r) for r in db.execute('SELECT e.* FROM memory_evidence e JOIN memories m ON m.id=e.memory_id WHERE m.user_id=?',(uid,))]
        relations=[dict(r) for r in db.execute('SELECT * FROM memory_relations WHERE user_id=?',(uid,))]
        changes=[dict(r) for r in db.execute('SELECT * FROM memory_changes WHERE user_id=?',(uid,))]
    for item in sources+memories:item.pop('user_id',None)
    for row in relations+changes:row.pop('user_id',None)
    for change in changes:
        snapshots=json.loads(change['snapshots'])
        for snapshot in snapshots.values():
            if snapshot:snapshot['memory'].pop('user_id',None)
        change['snapshots']=json.dumps(snapshots)
    return {'format':'self-agent-v2','sources':sources,'memories':memories,'history':history,'metadata':metadata,'evidence':evidence,'relations':relations,'changes':changes}


def restore_user(store,uid,data):
    if not isinstance(data,dict) or data.get('format') not in ('self-agent-v1','self-agent-v2'):raise ValueError('unsupported_backup')
    sources,memories,history=(data.get(k) for k in ('sources','memories','history'))
    if not all(isinstance(x,list) for x in (sources,memories,history)) or len(memories)>50000 or len(sources)>50000:raise ValueError('invalid_backup')
    restored=0
    source_map={}
    memory_map={}
    new_ids=set()
    with store.tx():
        for source in sources:
            if not isinstance(source,dict) or not isinstance(source.get('content'),str) or len(source['content'])>120000:raise ValueError('invalid_source')
            sid,_=store.source(uid,str(source['project'])[:200],str(source['title'])[:200],source['content'],kind='restored',external_id='restore:'+source['id'])
            source_map[source['id']]=sid
        # Tombstones precede active rows to prevent resurrection from stale backups.
        for row in sorted(memories,key=lambda r:0 if r.get('status')=='forgotten' else 1):
            if not isinstance(row,dict) or row.get('status') not in ('active','candidate','superseded','forgotten'):raise ValueError('invalid_memory')
            old=store.db.execute('SELECT id FROM memories WHERE user_id=? AND project=? AND fingerprint=?',(uid,row['project'],fingerprint(row['content']))).fetchone()
            if old:
                memory_map[row['id']]=old['id']
                continue
            item=store.add(uid,row['project'],row['content'],title=row['title'],kind=row['kind'],source_id=source_map.get(row.get('source_id')),status='candidate')
            memory_map[row['id']]=item['id'];new_ids.add(row['id'])
            original=[v for v in history if v.get('memory_id')==row['id']]
            if original:
                store.db.execute('DELETE FROM versions WHERE memory_id=?',(item['id'],))
                for v in original:
                    if not isinstance(v.get('version'),int) or not isinstance(v.get('content'),str):raise ValueError('invalid_history')
                    store.db.execute('INSERT INTO versions VALUES(?,?,?,?,?)',(item['id'],v['version'],v['content'],v['status'],v['changed']))
            store.db.execute('UPDATE memories SET version=?,status=?,created=?,updated=? WHERE id=?',(row['version'],row['status'],row['created'],row['updated'],item['id']))
            if row['status'] not in ('active','candidate'):store.db.execute('DELETE FROM memory_fts WHERE memory_id=?',(item['id'],))
            restored+=1
        if data['format']=='self-agent-v2':
            for key in ('metadata','evidence','relations','changes'):
                if not isinstance(data.get(key,[]),list) or len(data.get(key,[]))>200000:raise ValueError('invalid_backup_metadata')
            for meta in data.get('metadata',[]):
                original=meta['memory_id']
                if original not in memory_map:raise ValueError('foreign_metadata')
                if original in new_ids:
                    store.lifecycle.metadata(memory_map[original],**{k:meta.get(k) for k in ('observed_at','valid_until','topic','reason')})
            for evidence in data.get('evidence',[]):
                mid=evidence['memory_id'];sid=evidence['source_id']
                if mid not in memory_map or sid not in source_map:raise ValueError('foreign_evidence')
                source=store.db.execute('SELECT content FROM sources WHERE id=?',(source_map[sid],)).fetchone()[0]
                quote=evidence['quote']
                try:messages=json.loads(source)
                except ValueError:messages=[]
                texts=[source]+[m.get('content','') for m in messages if isinstance(m,dict)] if isinstance(messages,list) else [source]
                if not isinstance(quote,str) or not any(quote in t for t in texts):raise ValueError('invalid_evidence')
                store.db.execute('INSERT OR IGNORE INTO memory_evidence VALUES(?,?,?,?,?)',(memory_map[mid],source_map[sid],evidence['message_id'],quote,evidence['observed_at']))
            import secrets
            change_map={row['id']:secrets.token_hex(16) for row in data.get('changes',[])}
            for relation in data.get('relations',[]):
                if relation['source_id'] not in memory_map or relation['target_id'] not in memory_map:raise ValueError('foreign_relation')
                if relation['relation'] not in ('merged','superseded','conflict','overrides'):raise ValueError('invalid_relation')
                if relation['source_id'] not in new_ids:continue
                store.db.execute('INSERT INTO memory_relations VALUES(?,?,?,?,?,?)',(secrets.token_hex(16),uid,memory_map[relation['source_id']],memory_map[relation['target_id']],relation['relation'],change_map.get(relation['change_id'],'')))
            for change in data.get('changes',[]):
                snapshots=json.loads(change['snapshots']);after=json.loads(change['after_versions'])
                if not all(mid in memory_map for mid in set(snapshots)|set(after)):raise ValueError('foreign_change')
                if not all(mid in new_ids for mid in after):continue
                mapped={}
                for mid,snapshot in snapshots.items():
                    if snapshot:
                        row=snapshot['memory'];row.update(id=memory_map[mid],user_id=uid,source_id=source_map.get(row.get('source_id')))
                        if snapshot['metadata']:snapshot['metadata']['memory_id']=memory_map[mid]
                    mapped[memory_map[mid]]=snapshot
                store.db.execute('INSERT INTO memory_changes VALUES(?,?,?,?,?,?,?)',(change_map[change['id']],uid,change['action'],json.dumps(mapped),json.dumps({memory_map[mid]:v for mid,v in after.items()}),change['created'],change['undone']))
    store.lifecycle.expire(uid)
    return {'restored':restored,'sources':len(source_map)}


def encrypt_backup(data,password):
    if len(password)<12:raise ValueError('backup_password_too_short')
    salt,nonce=os.urandom(16),os.urandom(12)
    key=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
    plaintext=json.dumps(data,ensure_ascii=False).encode()
    return b'SAVAULT1'+salt+nonce+AESGCM(key).encrypt(nonce,plaintext,b'SAVAULT1')


def decrypt_backup(data,password):
    if not data.startswith(b'SAVAULT1') or len(data)<51:raise ValueError('invalid_archive')
    salt,nonce=data[8:24],data[24:36]
    key=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
    return json.loads(AESGCM(key).decrypt(nonce,data[36:],b'SAVAULT1'))
