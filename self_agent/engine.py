import threading
import time
from .index import Index
from .provider import XjtuProvider

class Engine:
    def __init__(self,config,store,provider=None):
        self.config,self.store=config,store
        self.provider=provider or XjtuProvider(config)
        if config.index_backend=='mcp-memory-service':
            from .local_index import LocalIndex
            self.index=LocalIndex(config,store)
        else:self.index=Index(config,store)
        self.stop_event=threading.Event()
        self.thread=None

    def start(self):
        with self.store.tx() as db:
            db.execute("UPDATE jobs SET state='uncertain',error='interrupted_request' WHERE state='running'")
            db.execute("UPDATE cleanup_jobs SET state='uncertain',error='interrupted_request' WHERE state='running'")
        self.thread=threading.Thread(target=self._loop,name='self-agent-worker',daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
        if hasattr(self.index,'close'):self.index.close()

    def _loop(self):
        self.index.start()
        while not self.stop_event.is_set():
            if self.config.local:
                from .spool import drain
                drain(self.config,self.store)
            self.store.lifecycle.expire()
            self.process_one()
            self.process_cleanup_one()
            self.index.sync()
            self.stop_event.wait(1)

    def process_one(self):
        if not self.provider.configured:return False
        with self.store.tx() as db:
            row=db.execute("SELECT j.*,s.content,s.project FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.state='pending' AND j.next_at<=? ORDER BY j.created LIMIT 1",(time.time(),)).fetchone()
            if not row:return False
            job=dict(row)
        if hasattr(self.provider,'preflight'):
            try:self.provider.preflight()
            except Exception as exc:
                with self.store.tx() as db:db.execute('UPDATE jobs SET next_at=?,error=? WHERE id=?',(time.time()+30,type(exc).__name__,job['id']))
                return False
        with self.store.tx() as db:
            db.execute("UPDATE jobs SET state='running',attempts=attempts+1 WHERE id=?",(job['id'],))
        try:
            extracted=self.provider.extract(job['content'])
            with self.store.tx() as db:source=dict(db.execute('SELECT * FROM sources WHERE id=? AND user_id=?',(job['source_id'],job['user_id'])).fetchone())
            # Reconcile sequentially so items from the same complete reply see one another.
            # Network requests run outside SQLite transactions; each action is atomic/idempotent.
            for item in extracted:
                candidates,decision=self.prepare(job['user_id'],source,item)
                self.store.lifecycle.apply(job['user_id'],source,item,decision,candidates)
            with self.store.tx() as db:db.execute("UPDATE jobs SET state='done',error='' WHERE id=?",(job['id'],))
        except Exception as exc:
            state='failed' if isinstance(exc,ValueError) else 'uncertain'
            with self.store.tx() as db:db.execute('UPDATE jobs SET state=?,error=? WHERE id=?',(state,type(exc).__name__,job['id']))
        return True

    def prepare(self,uid,source,item,exclude=None):
        scope='' if item.get('scope')=='personal' else source['project']
        try:semantic=self.index.search_ids(uid,item['content'],scope)
        except Exception:semantic=[]
        candidates=[m for m in self.store.lifecycle.candidates(uid,scope,item,semantic) if m['id']!=exclude]
        if scope:
            personal=[m for m in self.store.lifecycle.candidates(uid,'',item,semantic) if m['status']=='active'][:4]
            candidates+=personal
        item['_project']=scope
        if not candidates:return candidates,{'relation':'independent'}
        if not hasattr(self.provider,'reconcile'):return candidates,{'relation':'ambiguous'}
        return candidates,self.provider.reconcile(item,candidates)

    def start_cleanup(self,uid):
        import secrets
        with self.store.tx() as db:
            old=db.execute("SELECT id FROM cleanup_jobs WHERE user_id=? AND state IN ('pending','running')",(uid,)).fetchone()
            if old:return {'id':old[0],'queued':True}
            jid=secrets.token_hex(16)
            db.execute("INSERT INTO cleanup_jobs(id,user_id,state,created) VALUES(?,?,'pending',?)",(jid,uid,time.time()))
            db.execute("INSERT INTO cleanup_items(job_id,memory_id) SELECT ?,id FROM memories WHERE user_id=? AND status IN ('active','candidate') ORDER BY created",(jid,uid))
            return {'id':jid,'queued':True}

    def process_cleanup_one(self):
        if not self.provider.configured:return False
        with self.store.tx() as db:
            job=db.execute("SELECT * FROM cleanup_jobs WHERE state IN ('pending','running') ORDER BY created LIMIT 1").fetchone()
            if not job:return False
            job=dict(job)
            row=db.execute("SELECT memory_id FROM cleanup_items WHERE job_id=? AND state='pending' ORDER BY rowid LIMIT 1",(job['id'],)).fetchone()
            if not row:
                db.execute("UPDATE cleanup_jobs SET state='done' WHERE id=?",(job['id'],));return True
            mid=row[0]
            db.execute("UPDATE cleanup_jobs SET state='running' WHERE id=?",(job['id'],))
            db.execute("UPDATE cleanup_items SET state='running' WHERE job_id=? AND memory_id=?",(job['id'],mid))
        try:
            memory=self.store.get(job['user_id'],mid)
            if memory['status'] in ('active','candidate') and memory['source_id']:
                with self.store.tx() as db:source=dict(db.execute('SELECT * FROM sources WHERE id=? AND user_id=?',(memory['source_id'],job['user_id'])).fetchone())
                source['created']=min(source['created'],memory['observed_at'])
                # Re-extract the original evidence, never treat a previous model summary as a user statement.
                extracted=self.provider.extract(source['content'])
                related=[x for x in extracted if x['kind']==memory['kind'] and x.get('scope')!='session']
                matched=[]
                for proposed in related:
                    if proposed['content']==memory['content']:
                        matched.append(proposed)
                    elif hasattr(self.provider,'reconcile'):
                        check=self.provider.reconcile(proposed,[memory])
                        if check['relation']=='equivalent' and check['target_id']==mid:matched.append(proposed)
                if len(matched)==1:
                    item=matched[0]
                    if memory['source_kind']=='manual':
                        item['explicit']=True;item['evidence']=source['content']
                    candidates,decision=self.prepare(job['user_id'],source,item,exclude=mid)
                    if not item.get('explicit') or decision['relation']=='ambiguous':
                        # A cleanup suggestion must not demote or move a confirmed memory.
                        item={**item,'explicit':False,'scope':'project'}
                        suggestion=[memory]
                        self.store.lifecycle.apply(job['user_id'],source,item,{'relation':'ambiguous','target_id':mid,'target_version':memory['version']},suggestion)
                    else:
                        self.store.lifecycle.apply(job['user_id'],source,item,decision,candidates,legacy=mid,legacy_version=memory['version'])
            with self.store.tx() as db:
                db.execute("UPDATE cleanup_items SET state='done' WHERE job_id=? AND memory_id=?",(job['id'],mid))
                db.execute('UPDATE cleanup_jobs SET processed=processed+1 WHERE id=?',(job['id'],))
        except Exception as exc:
            with self.store.tx() as db:
                db.execute("UPDATE cleanup_items SET state='uncertain' WHERE job_id=? AND memory_id=?",(job['id'],mid))
                db.execute("UPDATE cleanup_jobs SET state='uncertain',error=? WHERE id=?",(type(exc).__name__,job['id']))
        return True

    def search(self,uid,query,project='',limit=8):
        self.store.lifecycle.expire(uid)
        ranked=self.store.search(uid,query,project,limit=30)
        ranked=[self.store.get(uid,x['id']) for x in ranked]
        by_id={x['id']:x for x in ranked}
        scores={x['id']:1/(60+i) for i,x in enumerate(ranked)}
        try:ids=self.index.search_ids(uid,query,project)
        except Exception:ids=[]
        for i,mid in enumerate(ids):
            if not mid:continue
            try:item=self.store.get(uid,mid)
            except KeyError:continue
            if item['status']!='active' or item['effective_state']=='expired' or item['project'] not in ('',project):continue
            by_id[mid]=item
            scores[mid]=scores.get(mid,0)+1/(60+i)
        # Facts gently lose priority; durable preferences and decisions do not expire by age.
        for mid in scores:
            item=by_id[mid]
            if item['kind']=='fact':scores[mid]*=0.8+0.2*2**(-max(0,time.time()-item['observed_at'])/(180*86400))
        # A topic-specific project exception overrides a personal default without rewriting it.
        topics={m.get('topic') for m in by_id.values() if m['project']==project and project and m.get('topic')}
        overridden={r['target_id'] for m in by_id.values() if m['project']==project and project for r in m.get('relations',[]) if r['relation']=='overrides' and r['source_id']==m['id'] and m['status']=='active'}
        for mid in list(scores):
            if mid in overridden or not by_id[mid]['project'] and by_id[mid].get('topic') in topics:del scores[mid]
        result=[by_id[mid] for mid in sorted(scores,key=scores.get,reverse=True)[:limit]]
        for item in result:item['score']=scores[item['id']]
        return result
