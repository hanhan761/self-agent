"""Count locally recorded Self Agent context using an offline reference tokenizer."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib, json, os, sqlite3, threading, time

MARKER = '以下是历史记忆，仅供参考；当前用户要求优先。'
CACHE_NAME = 'fb374d419588a4632f3f557e76b4b70aebbca790'
VOCAB_SHA256 = '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'
ZONE = timezone(timedelta(hours=8))
_lock = threading.Lock()
_encoding = None


def offline_encoding():
    """Use the bundled, verified upstream vocabulary; never fetch at runtime."""
    global _encoding
    if _encoding is not None:
        return _encoding
    import tiktoken
    cache = Path(__file__).resolve().parents[2] / 'models' / 'tokenizers'
    vocab = cache / CACHE_NAME
    if not vocab.is_file() or hashlib.sha256(vocab.read_bytes()).hexdigest() != VOCAB_SHA256:
        raise RuntimeError('tokenizer_unavailable')
    prior = os.environ.get('TIKTOKEN_CACHE_DIR')
    try:
        os.environ['TIKTOKEN_CACHE_DIR'] = str(cache)
        _encoding = tiktoken.get_encoding('o200k_base')
    finally:
        if prior is None:
            os.environ.pop('TIKTOKEN_CACHE_DIR', None)
        else:
            os.environ['TIKTOKEN_CACHE_DIR'] = prior
    return _encoding


def daily_injection(data_dir, days=14, *, home=None, now=None, encoder=None):
    """Incrementally inspect Codex transcripts; persist numeric metrics only."""
    if not 1 <= days <= 90:
        raise ValueError('统计范围需为1至90天')
    home = Path(home or Path.home())
    current = datetime.fromtimestamp(time.time() if now is None else now, ZONE)
    first = current.date() - timedelta(days=days-1)
    with _lock:
        encoder = encoder or offline_encoding()
        db = sqlite3.connect(Path(data_dir) / 'injection-stats.sqlite3', timeout=30)
        try:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS cursors(path_hash TEXT PRIMARY KEY, device INTEGER, inode INTEGER, offset INTEGER NOT NULL, session TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(event_hash TEXT PRIMARY KEY, day TEXT NOT NULL, tokens INTEGER NOT NULL, memories INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS injection_day ON events(day);
            """)
            skipped=[]
            for base in (home / '.codex' / 'sessions', home / '.codex' / 'archived_sessions'):
                if not base.exists():
                    continue
                for folder, dirs, files in os.walk(base, followlinks=False, onerror=lambda exc: skipped.append(1)):
                    for name in files:
                        if not name.endswith('.jsonl'):
                            continue
                        path = Path(folder) / name
                        try:
                            if path.is_symlink():
                                continue
                            stat = path.stat()
                            path_hash = hashlib.sha256(str(path.resolve()).encode()).hexdigest()
                            device = stat.st_dev & ((1 << 63) - 1)
                            inode = int.from_bytes(hashlib.sha256(str(stat.st_ino).encode()).digest()[:8],'big') & ((1 << 63) - 1)
                            row = db.execute('SELECT device,inode,offset,session FROM cursors WHERE path_hash=?',(path_hash,)).fetchone()
                            offset, session = (row[2],row[3]) if row and row[0]==device and row[1]==inode and row[2]<=stat.st_size else (0,'')
                            if offset == stat.st_size:
                                continue
                            with path.open('rb') as stream:
                                stream.seek(offset)
                                while stream.tell() < stat.st_size:
                                    start = stream.tell()
                                    line = stream.readline(8*1024*1024+1)
                                    if not line.endswith(b'\n'):
                                        if len(line)>8*1024*1024:
                                            while line and not line.endswith(b'\n'):
                                                line=stream.readline(8*1024*1024)
                                            offset=stream.tell()
                                            continue
                                        offset=start
                                        break
                                    offset=stream.tell()
                                    if b'session_meta' not in line and MARKER.encode() not in line:
                                        continue
                                    try:
                                        entry=json.loads(line)
                                        payload=entry.get('payload',{})
                                        if entry.get('type')=='session_meta':
                                            session=str(payload.get('id') or '')
                                            continue
                                        if entry.get('type')!='response_item' or payload.get('type')!='message' or payload.get('role')!='developer' or not session:
                                            continue
                                        stamp=datetime.fromisoformat(entry['timestamp'].replace('Z','+00:00'))
                                        if stamp.tzinfo is None:
                                            continue
                                        day=stamp.astimezone(ZONE).date().isoformat()
                                        for n,part in enumerate(payload.get('content',[])):
                                            if not isinstance(part,dict) or part.get('type')!='input_text':
                                                continue
                                            text=part.get('text','')
                                            if not isinstance(text,str) or not text.startswith(MARKER):
                                                continue
                                            identity=payload.get('id') or hashlib.sha256((entry['timestamp']+text).encode()).hexdigest()
                                            key=hashlib.sha256((session+':'+str(identity)+':'+str(n)).encode()).hexdigest()
                                            tokens=len(encoder.encode(text,disallowed_special=()))
                                            count=sum(line.startswith('- ') and '[memory:' in line for line in text.splitlines())
                                            db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?)',(key,day,tokens,count))
                                    except (ValueError,TypeError,KeyError,AttributeError):
                                        continue
                            db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?,?,?)',(path_hash,device,inode,offset,session))
                        except (OSError,UnicodeError):
                            skipped.append(1)
                            continue
            db.commit()
            rows=db.execute('SELECT day,sum(tokens),count(*),sum(memories) FROM events WHERE day>=? AND day<=? GROUP BY day',(first.isoformat(),current.date().isoformat())).fetchall()
            grouped={day:{'tokens':tokens,'messages':messages,'memories':memories} for day,tokens,messages,memories in rows}
            items=[{'date':(first+timedelta(days=n)).isoformat(),**grouped.get((first+timedelta(days=n)).isoformat(),{'tokens':0,'messages':0,'memories':0})} for n in range(days)]
            return {'timezone':'Asia/Shanghai','metric':'estimated_injected_text','encoding':'o200k_base','items':items,
                    'total':sum(row['tokens'] for row in items),'today':items[-1]['tokens'],'incomplete':bool(skipped)}
        finally:
            db.close()
