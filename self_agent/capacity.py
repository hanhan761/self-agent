"""Local resource policy, with mature cross-process locking and durable pause state."""
from contextlib import contextmanager,closing
from pathlib import Path
import json,shutil,sqlite3,time
from filelock import FileLock,Timeout
from .config import Config

class Backpressure(OSError):
    def __init__(self,reason):self.reason=reason;super().__init__(reason)

class Capacity:
    def __init__(self,config):self.config=config;self.root=Path(config.data_dir).resolve()

    @classmethod
    def for_root(cls,root):
        root=Path(root);path=root/'server.json'
        values=json.loads(path.read_text('utf-8')) if path.exists() else {}
        keys=('max_data_bytes','min_free_bytes','max_capture_batches','max_capture_bytes','max_pending_jobs')
        return cls(Config(root,**{k:values[k] for k in keys if k in values}))

    def _save(self,state):
        from .spool import atomic_json
        try:atomic_json(self.root/'capacity-state.json',state)
        except OSError:pass  # A full disk must not overwrite sources or advance capture cursors.

    def _snapshot(self,force=False):
        path=self.root/'capacity-state.json'
        try:state=json.loads(path.read_text('utf-8'))
        except (OSError,ValueError):state={}
        if not force and time.time()-state.get('checked_at',0)<2:return state
        used=0
        for p in self.root.rglob('*'):
            try:
                if p.is_file() and not p.is_symlink():used+=p.stat().st_size
            except FileNotFoundError:pass
        files=list((self.root/'inbox').glob('*.json'));queued_bytes=0
        for p in files:
            try:queued_bytes+=p.stat().st_size
            except FileNotFoundError:pass
        pending=0;oldest=None;database=self.root/'memory.sqlite3'
        if database.exists():
            try:
                with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
                    pending,oldest=db.execute("SELECT count(*),min(created) FROM jobs WHERE state IN ('pending','running','history_pending','history_running')").fetchone()
            except sqlite3.Error:raise Backpressure('queue_unavailable') from None
        return {'checked_at':time.time(),'bytes_used':used,'capture_batches':len(files),'capture_bytes':queued_bytes,
                'pending_jobs':pending,'oldest_pending_at':oldest,'blocked_reason':state.get('blocked_reason','')}

    def _reason(self,state,incoming=0,batches=0,jobs=0,capture_bytes=0):
        c=self.config
        if state['bytes_used']+incoming>=c.max_data_bytes:return 'data_limit'
        if shutil.disk_usage(self.root.resolve()).free-incoming<c.min_free_bytes:return 'disk_low'
        if state['capture_batches']+batches>c.max_capture_batches or state['capture_bytes']+capture_bytes>c.max_capture_bytes:return 'capture_queue_full'
        if state['pending_jobs']+jobs>c.max_pending_jobs:return 'processing_queue_full'
        return ''

    @contextmanager
    def reserve(self,incoming=0,*,batches=0,jobs=0,capture_bytes=0):
        self.root.mkdir(parents=True,exist_ok=True)
        try:
            with FileLock(str(self.root/'capacity.lock'),timeout=1):
                state=self._snapshot();reason=self._reason(state,incoming,batches,jobs,capture_bytes)
                if reason:
                    state['blocked_reason']=reason;state['blocked_at']=time.time();self._save(state);raise Backpressure(reason)
                state.update(bytes_used=state['bytes_used']+max(0,incoming),capture_batches=state['capture_batches']+batches,
                             capture_bytes=state['capture_bytes']+capture_bytes,pending_jobs=state['pending_jobs']+jobs,blocked_reason='')
                self._save(state)
                yield
        except Timeout:raise Backpressure('capture_busy') from None

    def check(self,incoming=0,**kwargs):
        with self.reserve(incoming,**kwargs):pass

    def status(self):
        self.root.mkdir(parents=True,exist_ok=True)
        try:
            with FileLock(str(self.root/'capacity.lock'),timeout=.2):
                state=self._snapshot(force=True);state['blocked_reason']=self._reason(state) or state.get('blocked_reason','');self._save(state)
        except Timeout:state=self._snapshot()
        return {**state,'data_limit_bytes':self.config.max_data_bytes,'disk_free_bytes':shutil.disk_usage(self.root.resolve()).free,
                'minimum_free_bytes':self.config.min_free_bytes,'max_pending_jobs':self.config.max_pending_jobs,
                'max_capture_batches':self.config.max_capture_batches}
