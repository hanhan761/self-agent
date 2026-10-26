"""Evidence, reversible reconciliation and expiry over authoritative SQLite rows."""
import difflib,json,math,secrets,time

SCHEMA='''
CREATE TABLE IF NOT EXISTS memory_metadata(memory_id TEXT PRIMARY KEY REFERENCES memories(id), observed_at REAL NOT NULL, valid_until REAL, topic TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS memory_evidence(memory_id TEXT NOT NULL REFERENCES memories(id), source_id TEXT NOT NULL REFERENCES sources(id), message_id TEXT NOT NULL, quote TEXT NOT NULL, observed_at REAL NOT NULL, PRIMARY KEY(memory_id,source_id,message_id,quote));
CREATE TABLE IF NOT EXISTS memory_relations(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES memories(id), target_id TEXT NOT NULL REFERENCES memories(id), relation TEXT NOT NULL, change_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_changes(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, action TEXT NOT NULL, snapshots TEXT NOT NULL, after_versions TEXT NOT NULL, created REAL NOT NULL, undone INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS learning_applied(user_id TEXT NOT NULL, source_id TEXT NOT NULL, fingerprint TEXT NOT NULL, memory_id TEXT, PRIMARY KEY(user_id,source_id,fingerprint));
CREATE TABLE IF NOT EXISTS cleanup_jobs(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, state TEXT NOT NULL, cursor TEXT NOT NULL DEFAULT '', processed INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS cleanup_items(job_id TEXT NOT NULL REFERENCES cleanup_jobs(id), memory_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', PRIMARY KEY(job_id,memory_id));
'''

class Lifecycle:
    def __init__(self,store):self.store=store

    def describe(self,row):
        db=self.store.db;mid=row['id'];uid=row['user_id']
        meta=db.execute('SELECT * FROM memory_metadata WHERE memory_id=?',(mid,)).fetchone()
        row.update(dict(meta) if meta else {'observed_at':row['created'],'valid_until':None,'topic':'','reason':''})
        row['scope']='project' if row['project'] else 'personal'
        row['evidence']=[dict(x) for x in db.execute('SELECT e.* FROM memory_evidence e JOIN sources s ON s.id=e.source_id WHERE e.memory_id=? AND s.user_id=? ORDER BY e.observed_at',(mid,uid))]
        row['relations']=[dict(x) for x in db.execute('SELECT id,source_id,target_id,relation,change_id FROM memory_relations WHERE user_id=? AND (source_id=? OR target_id=?)',(uid,mid,mid))]
        row['changes']=[dict(x) for x in db.execute('SELECT id,action,created,undone FROM memory_changes WHERE user_id=? AND EXISTS (SELECT 1 FROM json_each(after_versions) WHERE key=?) ORDER BY created DESC',(uid,mid))]
        row['effective_state']='expired' if row['reason']=='expired' or row['valid_until'] is not None and row['valid_until']<=time.time() else row['status']
        return row

    def metadata(self,mid,*,observed_at=None,valid_until=None,topic='',reason=''):
        if valid_until is not None and (not isinstance(valid_until,(int,float)) or not math.isfinite(valid_until) or valid_until<0):raise ValueError('invalid_valid_until')
        old=self.store.db.execute('SELECT observed_at FROM memory_metadata WHERE memory_id=?',(mid,)).fetchone()
        self.store.db.execute('INSERT OR REPLACE INTO memory_metadata VALUES(?,?,?,?,?)',(mid,observed_at if observed_at is not None else old[0] if old else time.time(),valid_until,topic[:120],reason))
        from .store import words
        row=self.store.db.execute('SELECT content,title,status FROM memories WHERE id=?',(mid,)).fetchone()
        if row:
            self.store.db.execute('DELETE FROM memory_fts WHERE memory_id=?',(mid,))
            if row['status'] in ('active','candidate'):self.store.db.execute('INSERT INTO memory_fts VALUES(?,?)',(mid,words(row['content']+' '+row['title']+' '+topic)))

    def snapshot(self,mid):
        row=self.store.db.execute('SELECT * FROM memories WHERE id=?',(mid,)).fetchone()
        if not row:return None
        meta=self.store.db.execute('SELECT * FROM memory_metadata WHERE memory_id=?',(mid,)).fetchone()
        return {'memory':dict(row),'metadata':dict(meta) if meta else None}

    def record(self,uid,action,before,change_id=None):
        cid=change_id or secrets.token_hex(16)
        after={mid:self.store.db.execute('SELECT version FROM memories WHERE id=?',(mid,)).fetchone()[0] for mid in before}
        self.store.db.execute('INSERT INTO memory_changes VALUES(?,?,?,?,?,?,0)',(cid,uid,action,json.dumps(before),json.dumps(after),time.time()))
        return cid

    def evidence(self,uid,mid,sid,item,observed):
        source=self.store.db.execute('SELECT content FROM sources WHERE id=? AND user_id=?',(sid,uid)).fetchone()
        if not source:raise KeyError(sid)
        quote=item.get('evidence','')
        try:rows=json.loads(source[0])
        except ValueError:rows=[]
        matches=[r for r in rows if isinstance(r,dict) and r.get('role')=='user' and quote and (quote in r.get('content','') or quote in json.dumps(r.get('content',''),ensure_ascii=False))] if isinstance(rows,list) else []
        if item.get('explicit') and not matches and source[0]!=quote:raise ValueError('missing_user_evidence')
        for message in matches:
            self.store.db.execute('INSERT OR IGNORE INTO memory_evidence VALUES(?,?,?,?,?)',(mid,sid,str(message.get('id','legacy')),quote,observed))
        if not matches and quote:
            self.store.db.execute('INSERT OR IGNORE INTO memory_evidence VALUES(?,?,?,?,?)',(mid,sid,'source',quote,observed))

    def candidates(self,uid,project,item,semantic_ids=()):
        from .store import words,fingerprint
        with self.store.tx() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM memories WHERE user_id=? AND project=? AND kind=?',(uid,project,item['kind']))]
        tokens=set(words(item['content']).split());semantic=set(semantic_ids)
        def rank(m):
            same=fingerprint(m['content'])==fingerprint(item['content'])
            terms=set(words(m['content']).split())
            score=len(tokens&terms)/max(1,len(tokens|terms))+difflib.SequenceMatcher(None,item['content'],m['content']).ratio()
            return (same,m['id'] in semantic,score,m['updated'])
        return [self.store.get(uid,r['id']) for r in sorted(rows,key=rank,reverse=True)[:8]]

    def apply(self,uid,source,item,decision,candidates,*,legacy=None,legacy_version=None):
        from .store import fingerprint
        project='' if item.get('scope')=='personal' else source['project']
        from .messages import timestamp
        try:messages=json.loads(source['content'])
        except ValueError:messages=[]
        times=[timestamp(m.get('observed_at'),source['created']) for m in messages if isinstance(m,dict) and m.get('role')=='user' and item.get('evidence','') in m.get('content','')] if isinstance(messages,list) else []
        observed=max(times) if times else item.get('observed_at') or source['created']
        fp=fingerprint(item['content']);db=self.store.db
        with self.store.tx():
            if legacy and self.store.get(uid,legacy)['version']!=legacy_version:raise ValueError('concurrent_memory_change')
            applied=db.execute('SELECT memory_id FROM learning_applied WHERE user_id=? AND source_id=? AND fingerprint=?',(uid,source['id'],fp)).fetchone()
            if applied and not legacy:return self.store.get(uid,applied[0]) if applied[0] else None
            if item.get('scope')=='session' or item.get('temporary'):return None
            targets={m['id']:m for m in candidates}
            relation=decision.get('relation','independent');tid=decision.get('target_id');old=targets.get(tid)
            if relation not in ('equivalent','supersedes','independent','ambiguous'):raise ValueError('invalid_reconciliation')
            if relation!='independent' and tid and not old:raise ValueError('foreign_reconciliation_target')
            if old:
                latest=self.store.get(uid,tid)
                if latest['version']!=decision.get('target_version'):raise ValueError('concurrent_memory_change')
                if latest['project']!=project or latest['kind']!=item['kind']:raise ValueError('cross_scope_reconciliation')
                old=latest
            exact=db.execute('SELECT id FROM memories WHERE user_id=? AND project=? AND fingerprint=?',(uid,project,fp)).fetchone()
            if exact and (not legacy or exact[0]!=legacy):
                old=self.store.get(uid,exact[0]);tid=old['id'];relation='equivalent'
            before={};cid=secrets.token_hex(16)
            if old and old['status']=='forgotten' and relation in ('equivalent','supersedes'):
                db.execute('INSERT OR IGNORE INTO learning_applied VALUES(?,?,?,?)',(uid,source['id'],fp,old['id']))
                return old
            # A previously superseded equivalent must not become active again.
            if relation=='equivalent' and old:
                if item.get('valid_until')!=old.get('valid_until') and (not item.get('explicit') or observed<old['observed_at']):raise ValueError('deadline_conflict')
                result=old;before[old['id']]=self.snapshot(old['id'])
                self.evidence(uid,old['id'],source['id'],item,observed)
                self.store.update(uid,old['id'],status='active' if old['status']=='candidate' and item.get('explicit') and observed>=old['observed_at'] else None,version=old['version'])
                self.metadata(old['id'],observed_at=max(observed,old['observed_at']),valid_until=item.get('valid_until'),topic=old['topic'] or item.get('topic',''),reason=old['reason'])
                if legacy and legacy!=old['id']:
                    before[legacy]=self.snapshot(legacy);self.store.update(uid,legacy,status='superseded')
                    self.metadata(legacy,observed_at=source['created'],reason='merged')
                    db.execute('INSERT INTO memory_relations VALUES(?,?,?,?,?,?)',(secrets.token_hex(16),uid,legacy,old['id'],'merged',cid))
            else:
                active=bool(item.get('explicit'))
                if relation=='ambiguous' or relation=='supersedes' and (not old or observed<=old['observed_at'] or old['status']!='active'):active=False
                if relation=='equivalent' and old:active=False # Different deadlines need review.
                if legacy:
                    existing=self.store.get(uid,legacy);before[legacy]=self.snapshot(legacy)
                    if existing['status']=='forgotten':return existing
                    if project!=existing['project']:
                        duplicate=db.execute('SELECT id FROM memories WHERE user_id=? AND project=? AND fingerprint=?',(uid,project,fp)).fetchone()
                        if duplicate:raise ValueError('scope_change_duplicate')
                        db.execute('UPDATE memories SET project=? WHERE id=?',(project,legacy))
                    result=self.store.update(uid,legacy,content=item['content'],status='active' if active else 'candidate')
                else:
                    result=self.store.add(uid,project,item['content'],kind=item['kind'],source_id=source['id'],status='active' if active else 'candidate')
                    before[result['id']]=None
                self.metadata(result['id'],observed_at=observed,valid_until=item.get('valid_until'),topic=item.get('topic',''),reason='conflict' if not active and old else '')
                self.evidence(uid,result['id'],source['id'],item,observed)
                if relation=='supersedes' and old and active:
                    before[old['id']]=self.snapshot(old['id'])
                    self.store.update(uid,old['id'],status='superseded',version=old['version'])
                    self.metadata(old['id'],observed_at=old['observed_at'],valid_until=old['valid_until'],topic=old['topic'],reason='replaced')
                    db.execute('INSERT INTO memory_relations VALUES(?,?,?,?,?,?)',(secrets.token_hex(16),uid,old['id'],result['id'],'superseded',cid))
                elif old and relation in ('ambiguous','supersedes','equivalent'):
                    db.execute('INSERT INTO memory_relations VALUES(?,?,?,?,?,?)',(secrets.token_hex(16),uid,result['id'],old['id'],'conflict',cid))
            override=targets.get(decision.get('overrides_id'))
            if override:
                if not project or override['project'] or override['status']!='active':raise ValueError('invalid_personal_default')
                db.execute('INSERT INTO memory_relations VALUES(?,?,?,?,?,?)',(secrets.token_hex(16),uid,result['id'],override['id'],'overrides',cid))
            self.record(uid,'merge' if relation=='equivalent' else 'replace' if relation=='supersedes' and active else 'learn',before,cid)
            db.execute('INSERT OR REPLACE INTO learning_applied VALUES(?,?,?,?)',(uid,source['id'],fp,result['id']))
            return self.store.get(uid,result['id'])

    def expire(self,uid=None):
        with self.store.tx() as db:
            sql="SELECT m.id,m.user_id FROM memories m JOIN memory_metadata x ON x.memory_id=m.id WHERE m.status='active' AND x.valid_until<=?"
            args=[time.time()]
            if uid:sql+=' AND m.user_id=?';args.append(uid)
            for row in list(db.execute(sql,args)):
                mid=row['id'];before={mid:self.snapshot(mid)}
                self.store.update(row['user_id'],mid,status='superseded')
                db.execute("UPDATE memory_metadata SET reason='expired' WHERE memory_id=?",(mid,))
                self.record(row['user_id'],'expire',before)

    def undo(self,uid,cid):
        from .store import words
        with self.store.tx() as db:
            change=db.execute('SELECT * FROM memory_changes WHERE id=? AND user_id=?',(cid,uid)).fetchone()
            if not change:raise KeyError(cid)
            if change['undone']:return {'undone':True}
            before=json.loads(change['snapshots']);after=json.loads(change['after_versions'])
            for mid,version in after.items():
                row=self.store.get(uid,mid)
                if row['status']=='forgotten' or row['version']!=version:raise ValueError('记忆已有后续修改，不能覆盖；请查看历史后修订')
            for mid,snapshot in before.items():
                current=self.store.get(uid,mid)
                if snapshot:
                    old=snapshot['memory'];meta=snapshot['metadata']
                    self.store.update(uid,mid,content=old['content'],status=old['status'],version=current['version'])
                    db.execute('UPDATE memories SET project=?,title=? WHERE id=?',(old['project'],old['title'],mid))
                    db.execute('DELETE FROM memory_metadata WHERE memory_id=?',(mid,))
                    if meta:self.metadata(mid,**{k:meta[k] for k in ('observed_at','valid_until','topic','reason')})
                else:
                    self.store.update(uid,mid,status='superseded',version=current['version'])
                    db.execute("UPDATE memory_metadata SET reason='reverted' WHERE memory_id=?",(mid,))
            db.execute('DELETE FROM memory_relations WHERE change_id=? AND user_id=?',(cid,uid))
            db.execute('UPDATE memory_changes SET undone=1 WHERE id=?',(cid,))
        return {'undone':True}

    def patch(self,uid,mid,*,version,content=None,status=None,project=None,valid_until=None,deadline_set=False):
        with self.store.tx() as db:
            old=self.store.get(uid,mid)
            if old['version']!=version:raise ValueError('记忆已被更新，请刷新后重试')
            before={mid:self.snapshot(mid)}
            if project is not None:
                if old['status']=='forgotten':raise ValueError('已忘记的记忆不能恢复')
                db.execute('UPDATE memories SET project=? WHERE id=?',(project,mid))
            result=self.store.update(uid,mid,content=content,status=status,version=version)
            until=valid_until if deadline_set else old['valid_until']
            if status=='active' and until is not None and until<=time.time():raise ValueError('请先修正已到期的有效期')
            self.metadata(mid,observed_at=time.time() if content else old['observed_at'],valid_until=until,topic=old['topic'],reason='' if status=='active' or deadline_set else old['reason'])
            self.record(uid,'edit',before)
        self.expire(uid)
        return self.store.get(uid,mid)
