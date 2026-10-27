"""One-way user-scoped migration; leave the remote service and its data untouched."""
import hashlib,json,secrets,time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from .archive import encrypt_backup,restore_user
from .spool import atomic_json
from .store import Store
from .xjcode_auth import protect


def migrate(config,previous):
    if previous.get('local'):return {'skipped':True}
    url=previous.get('url','');parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('invalid_migration_source')
    token=Path(previous['token_file']).read_text('utf-8').strip()
    with httpx.Client(trust_env=False,follow_redirects=False,proxy=previous.get('proxy'),timeout=60) as client:
        response=client.get(url.rstrip('/')+'/v1/export',headers={'Authorization':'Bearer '+token})
        response.raise_for_status();data=response.json()
    directory=config.data_dir/'migration-backups';directory.mkdir(parents=True,exist_ok=True)
    stamp=str(time.time_ns());password=secrets.token_urlsafe(32)
    archive=directory/(stamp+'.savault');key=directory/(stamp+'.key.dpapi')
    archive.write_bytes(encrypt_backup(data,password));key.write_bytes(protect(password.encode()))
    store=Store(config.data_dir/'memory.sqlite3')
    try:result=restore_user(store,config.local_user_id,data)
    finally:store.close()
    report={'completed':True,'restored':result['restored'],'sources':result['sources'],
            'source_host':parsed.hostname,'encrypted_backup':str(archive)}
    atomic_json(config.data_dir/'migration.json',report)
    return report
