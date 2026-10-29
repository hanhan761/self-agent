from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, admin INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS project_labels(user_id TEXT NOT NULL REFERENCES users(id),project TEXT NOT NULL,label TEXT NOT NULL,PRIMARY KEY(user_id,project));
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, hash TEXT UNIQUE NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), project TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, kind TEXT NOT NULL, external_id TEXT NOT NULL, hash TEXT NOT NULL, created REAL NOT NULL, UNIQUE(user_id,project,external_id,hash));
CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), project TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, source_id TEXT REFERENCES sources(id), status TEXT NOT NULL, version INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, fingerprint TEXT NOT NULL, UNIQUE(user_id,project,fingerprint));
CREATE TABLE IF NOT EXISTS versions(memory_id TEXT NOT NULL REFERENCES memories(id), version INTEGER NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, changed REAL NOT NULL, PRIMARY KEY(memory_id,version));
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), source_id TEXT NOT NULL REFERENCES sources(id), state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', created REAL NOT NULL, UNIQUE(source_id));
CREATE TABLE IF NOT EXISTS projections(memory_id TEXT PRIMARY KEY REFERENCES memories(id), version INTEGER NOT NULL, external_id TEXT, error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS job_extractions(job_id TEXT PRIMARY KEY REFERENCES jobs(id),items TEXT NOT NULL,next_item INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, event TEXT NOT NULL, entity_id TEXT NOT NULL, at REAL NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(memory_id UNINDEXED, words, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS external_identities(provider TEXT NOT NULL, identity_hash TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(provider,identity_hash));
CREATE TABLE IF NOT EXISTS session_identities(session_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, identity_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS api_key_identities(key_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, identity_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pairing_codes(hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, expires REAL NOT NULL, provider TEXT NOT NULL, identity_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS memory_owner ON memories(user_id,project,status);
CREATE INDEX IF NOT EXISTS memory_listing ON memories(user_id,status,updated DESC);
CREATE INDEX IF NOT EXISTS memory_project_listing ON memories(user_id,project,status,updated DESC);
CREATE INDEX IF NOT EXISTS memory_candidates ON memories(user_id,project,kind,updated DESC);
CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(state,next_at,created);
'''


def words(text):
    import jieba
    return ' '.join(jieba.cut_for_search(text.lower()))


# Function words must not make unrelated memories look like keyword matches.
STOP_WORDS=set('的 了 是 我 你 他 她 它 我们 你们 这个 那个 这些 那些 请 一下 什么 怎么 如何 可以 应该 需要 一个 进行 以及 或者 和 与 在 对 用 有 吗 呢 吧 现在 the a an is are to of and or for on in it this that'.split())
def search_terms(text):
    return list(dict.fromkeys(t for t in re.findall(r'[\w]+',words(text)) if t not in STOP_WORDS))[:32]


def fingerprint(content):
    return hashlib.sha256(re.sub(r'\s+', '', content).casefold().encode()).hexdigest()


class Store:
    def __init__(self, filename: Path):
        filename.parent.mkdir(parents=True, exist_ok=True)
        self.filename = filename
        self.lock = threading.RLock()
        self.depth = 0
        self.db = sqlite3.connect(filename, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        from .lifecycle import Lifecycle,SCHEMA as LIFECYCLE_SCHEMA
        self.db.executescript(SCHEMA+LIFECYCLE_SCHEMA)
        self.lifecycle=Lifecycle(self)
        self.db.commit()

    @contextmanager
    def tx(self):
        with self.lock:
            self.depth += 1
            try:
                yield self.db
                if self.depth == 1:
                    self.db.commit()
            except BaseException:
                if self.depth == 1:
                    self.db.rollback()
                raise
            finally:
                self.depth -= 1

    def close(self):
        self.db.close()

    def source(self, uid, project, title, content, kind='manual', external_id=''):
        sid, now = secrets.token_hex(16), time.time()
        external_id = external_id or sid
        sha = hashlib.sha256(content.encode()).hexdigest()
        with self.tx() as db:
            row = db.execute('SELECT id FROM sources WHERE user_id=? AND project=? AND external_id=? AND hash=?',
                             (uid, project, external_id, sha)).fetchone()
            if row:
                return row['id'], False
            db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?)',
                       (sid, uid, project, title, content, kind, external_id, sha, now))
        return sid, True

    def add(self, uid, project, content, *, title='', kind='fact', source_id=None, status='active'):
        if not content.strip() or len(content) > 12000:
            raise ValueError('记忆内容需为 1–12000 字符')
        if kind not in ('preference','fact','decision','procedure') or status not in ('active','candidate'):
            raise ValueError('无效记忆类型或状态')
        mid, now, fp = secrets.token_hex(16), time.time(), fingerprint(content)
        with self.tx() as db:
            if source_id and not db.execute('SELECT id FROM sources WHERE id=? AND user_id=?', (source_id, uid)).fetchone():
                raise KeyError('source')
            old = db.execute('SELECT id FROM memories WHERE user_id=? AND project=? AND fingerprint=?', (uid, project, fp)).fetchone()
            if old:
                return self.get(uid, old['id'])
            db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (mid, uid, project, kind, title or content[:60], content, source_id, status, 1, now, now, fp))
            db.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (mid,1,content,status,now))
            db.execute('INSERT INTO memory_fts VALUES(?,?)', (mid,words(content+' '+title)))
            db.execute('INSERT INTO audit(user_id,event,entity_id,at) VALUES(?,?,?,?)', (uid,'created',mid,now))
        return self.get(uid, mid)

    def get(self, uid, mid):
        with self.tx() as db:
            row = db.execute('SELECT m.*,s.title source_title,s.kind source_kind FROM memories m LEFT JOIN sources s ON s.id=m.source_id WHERE m.id=? AND m.user_id=?', (mid,uid)).fetchone()
            if not row:
                raise KeyError(mid)
            result = dict(row)
            result['history'] = [dict(x) for x in db.execute('SELECT version,content,status,changed FROM versions WHERE memory_id=? ORDER BY version DESC', (mid,))]
            return self.lifecycle.describe(result)

    def brief(self,uid,mid):
        """Bounded search/list records; full evidence and history stay behind get()."""
        with self.tx() as db:
            row=db.execute('SELECT m.*,s.title source_title,s.kind source_kind,x.observed_at,x.valid_until,x.topic,x.reason FROM memories m LEFT JOIN sources s ON s.id=m.source_id LEFT JOIN memory_metadata x ON x.memory_id=m.id WHERE m.id=? AND m.user_id=?',(mid,uid)).fetchone()
            if not row:raise KeyError(mid)
            result=dict(row);result['memory_id']=mid;result['observed_at']=result['observed_at'] or result['created']
            result['topic']=result['topic'] or '';result['reason']=result['reason'] or '';result['scope']='project' if result['project'] else 'personal'
            result['effective_state']='expired' if result['reason']=='expired' or result['valid_until'] is not None and result['valid_until']<=time.time() else result['status']
            result['relations']=[dict(r) for r in db.execute("SELECT source_id,target_id,relation FROM memory_relations WHERE user_id=? AND source_id=? AND relation='overrides'",(uid,mid))]
            return result

    def update(self, uid, mid, *, content=None, status=None, version=None, explicit_restore=False):
        with self.tx() as db:
            old = self.get(uid, mid)
            if version is not None and old['version'] != version:
                raise ValueError('记忆已被更新，请刷新后重试')
            content = old['content'] if content is None else content.strip()
            status = old['status'] if status is None else status
            if not content or len(content)>12000 or status not in ('active','candidate','superseded','forgotten'):
                raise ValueError('无效内容或状态')
            if old['status']=='forgotten' and status!='forgotten' and not explicit_restore:
                raise ValueError('已忘记的记忆不能自动恢复')
            v,now=old['version']+1,time.time()
            title=content[:60] if old['title']==old['content'][:60] else old['title']
            db.execute('UPDATE memories SET title=?,content=?,status=?,version=?,updated=?,fingerprint=? WHERE id=?', (title,content,status,v,now,fingerprint(content),mid))
            db.execute('INSERT INTO versions VALUES(?,?,?,?,?)',(mid,v,content,status,now))
            db.execute('DELETE FROM memory_fts WHERE memory_id=?',(mid,))
            if status in ('active','candidate'):
                db.execute('INSERT INTO memory_fts VALUES(?,?)',(mid,words(content+' '+title)))
            db.execute('INSERT INTO audit(user_id,event,entity_id,at) VALUES(?,?,?,?)',(uid,status,mid,now))
        return self.get(uid,mid)

    def listing(self, uid, *, project=None, status='active', limit=100, offset=0, query='', details=True):
        sql,params='SELECT m.*,s.title source_title FROM memories m LEFT JOIN sources s ON s.id=m.source_id WHERE m.user_id=? AND m.status=?',[uid,status]
        if project is not None:
            sql+=' AND m.project IN (?,?)';params+=['',project]
        if query.strip():
            sql+=" AND instr(lower(m.content||' '||m.title||' '||m.project),lower(?))>0";params.append(query.strip())
        sql+=' ORDER BY m.updated DESC LIMIT ? OFFSET ?';params += [min(limit,200),max(offset,0)]
        with self.tx() as db:
            return [(self.get if details else self.brief)(uid,x['id']) for x in db.execute(sql,params)]

    def memory_page(self,uid,*,project=None,status='active',offset=0,limit=100,query='',kind='',sort='updated',exact_project=False):
        """Owner-scoped management filters; exact project browsing does not change recall."""
        if status not in ('active','candidate','superseded','forgotten') or kind not in ('','preference','procedure','decision','fact'):raise ValueError('无效记忆筛选')
        orders={'updated':'m.updated DESC,m.id','oldest':'m.created ASC,m.id','observed':'COALESCE(x.observed_at,m.created) DESC,m.id'}
        if sort not in orders or not 1<=limit<=200:raise ValueError('无效排序或分页')
        joins=' FROM memories m LEFT JOIN memory_metadata x ON x.memory_id=m.id LEFT JOIN project_labels p ON p.user_id=m.user_id AND p.project=m.project'
        where=' WHERE m.user_id=? AND m.status=?';params=[uid,status]
        if project is not None:
            where+=' AND m.project=?' if exact_project else ' AND m.project IN (?,?)'
            params += [project] if exact_project else ['',project]
        if kind:where+=' AND m.kind=?';params.append(kind)
        if query.strip():
            where+=" AND instr(lower(m.content||' '||m.title||' '||m.project||' '||COALESCE(x.topic,'')||' '||COALESCE(p.label,'')),lower(?))>0";params.append(query.strip())
        with self.tx() as db:
            total=db.execute('SELECT count(*)'+joins+where,params).fetchone()[0]
            ids=[r[0] for r in db.execute('SELECT m.id'+joins+where+' ORDER BY '+orders[sort]+' LIMIT ? OFFSET ?',params+[limit,max(0,offset)])]
            return {'items':[self.brief(uid,mid) for mid in ids],'total':total,'offset':max(0,offset),'limit':limit}

    def search(self, uid, query, project='', limit=8):
        terms=search_terms(query)
        if not terms:return []
        expression=' OR '.join('"'+t+'"' for t in terms)
        with self.tx() as db:
            rows=db.execute('SELECT m.*,s.title source_title,f.rank rank FROM memory_fts f CROSS JOIN memories m ON m.id=f.memory_id LEFT JOIN sources s ON s.id=m.source_id WHERE memory_fts MATCH ? AND m.user_id=? AND m.project IN (?,?) AND m.status=? ORDER BY rank LIMIT ?', (expression,uid,'',project,'active',min(limit,50)))
            return [dict(x) for x in rows]

    def enqueue(self, uid, source_id):
        jid=secrets.token_hex(16)
        with self.tx() as db:
            old=db.execute('SELECT id FROM jobs WHERE source_id=? AND user_id=?',(source_id,uid)).fetchone()
            if old:return old['id']
            if not db.execute('SELECT id FROM sources WHERE id=? AND user_id=?',(source_id,uid)).fetchone():raise KeyError(source_id)
            db.execute('INSERT INTO jobs(id,user_id,source_id,state,created) VALUES(?,?,?,?,?)',(jid,uid,source_id,'pending',time.time()))
        return jid

    def overview(self, uid):
        with self.tx() as db:
            counts={r['status']:r['n'] for r in db.execute('SELECT status,count(*) n FROM memories WHERE user_id=? GROUP BY status',(uid,))}
            projects=[r[0] for r in db.execute('SELECT DISTINCT project FROM memories WHERE user_id=? AND project!=? ORDER BY project',(uid,''))]
            jobs=[dict(r) for r in db.execute('SELECT id,state,attempts,error,created FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT 30',(uid,))]
            sources=db.execute('SELECT count(*) FROM sources WHERE user_id=?',(uid,)).fetchone()[0]
            captured=db.execute("SELECT max(created) FROM sources WHERE user_id=? AND kind='conversation'",(uid,)).fetchone()[0]
            labels={r['project']:r['label'] for r in db.execute('SELECT project,label FROM project_labels WHERE user_id=?',(uid,))}
            scope_counts={'global':{},'project':{}};project_counts={}
            for row in db.execute('SELECT project,status,count(*) n FROM memories WHERE user_id=? GROUP BY project,status',(uid,)):
                scope='project' if row['project'] else 'global'
                scope_counts[scope][row['status']]=scope_counts[scope].get(row['status'],0)+row['n']
                if row['project']:project_counts.setdefault(row['project'],{})[row['status']]=row['n']
        return {'scope_counts':scope_counts,'project_counts':project_counts,'counts':counts,'projects':projects,'project_names':labels,'jobs':jobs,'sources':sources,'last_captured_at':captured}
