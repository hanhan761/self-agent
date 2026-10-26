"""No-build activation of an already verified artifact. Run only through pinned yun."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

BASE=Path('/home/codex-admin/services/self-agent')
PYTHON=Path('/home/codex-admin/.local/share/uv/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12')

def command(args,**kwargs):
    return subprocess.run(args,check=True,capture_output=True,text=True,**kwargs)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('artifact')
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--bootstrap',required=True)
    parser.add_argument('--service-file',required=True)
    args=parser.parse_args()
    artifact=Path(args.artifact).resolve()
    if not artifact.is_relative_to(BASE/'incoming'):raise ValueError('artifact_outside_incoming')
    if hashlib.sha256(artifact.read_bytes()).hexdigest()!=args.sha256:raise ValueError('artifact_digest_mismatch')
    BASE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (BASE/'deploy.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        free=shutil.disk_usage(BASE).free
        with zipfile.ZipFile(artifact) as archive:
            expanded=sum(i.file_size for i in archive.infolist())
            # Small-service capacity policy: no model download; bounded artifact/data,
            # and at least 100 GiB remains after staging.
            if artifact.stat().st_size>64*1024**2 or expanded>256*1024**2:raise RuntimeError('artifact_exceeds_small_service_budget')
            if free-expanded<100*1024**3:raise RuntimeError('insufficient_project_disk_reserve')
            manifest=json.loads(archive.read('release.json'))
            revision=manifest['source_revision']
            if not revision.isalnum():raise ValueError('invalid_release_id')
            release=BASE/'releases'/revision[:12]
            if release.exists():raise ValueError('release_already_exists')
            release.mkdir(parents=True)
            for item in archive.infolist():
                relative=Path(item.filename)
                if relative.is_absolute() or '..' in relative.parts:raise ValueError('unsafe_archive_member')
                if item.is_dir():continue
                if item.filename!='release.json' and hashlib.sha256(archive.read(item)).hexdigest()!=manifest['files'].get(item.filename):raise ValueError('release_file_digest_mismatch')
                target=release/relative;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.read(item))
        env=os.environ.copy()
        env['PYTHONPATH']=str(release/'vendor')+':'+str(release)
        env['PYTHONDONTWRITEBYTECODE']='1'
        env['SELF_AGENT_DATA']=str(BASE/'state')
        env['SELF_AGENT_CONFIG']=str(BASE/'config/server.json')
        # Import check only. No dependency installation, compilation or model loading.
        command([str(PYTHON),'-c','from self_agent.server import create_app; from self_agent.config import Config; import jieba,cryptography,uvicorn'],env=env,cwd=release)
        bootstrap=Path(args.bootstrap).resolve()
        if not bootstrap.is_relative_to(BASE/'incoming'):raise ValueError('invalid_bootstrap_path')
        config_dir=BASE/'config';config_dir.mkdir(mode=0o700,exist_ok=True)
        config_file=config_dir/'server.json'
        config={'host':'100.95.110.75','port':8766,'semantic':False,'allow_campus_http':True,'xjtu_native_config':'/home/codex-admin/services/jiaoxiaozhi-router/experiment-native.json','xjtu_model':'qwen3.8-max','max_data_bytes':512*1024**2}
        if config_file.exists():raise ValueError('existing_configuration_requires_review')
        config_file.write_text(json.dumps(config,indent=2));config_file.chmod(0o600)
        seed_script="""import json,sys
from pathlib import Path
from self_agent.config import Config
from self_agent.store import Store
from self_agent.auth import Auth,digest,password_hash
c=Config.load();c.prepare();s=Store(c.data_dir/'memory.sqlite3')
d=json.loads(Path(sys.argv[1]).read_text())
if s.db.execute('SELECT count(*) FROM users').fetchone()[0]:raise RuntimeError('bootstrap_requires_empty_users')
a=Auth(s);uid=a.create_user(d['username'],d['password'],True)
with s.tx() as db:
 db.execute('INSERT INTO api_keys VALUES(?,?,?,?,?)',(d['key_id'],uid,'initial-client',digest(d['token']),__import__('time').time()))
s.close()
"""
        command([str(PYTHON),'-c',seed_script,str(bootstrap)],env=env,cwd=release)
        bootstrap.unlink()
        old=(BASE/'current').resolve() if (BASE/'current').is_symlink() else None
        stage=BASE/'current.next'
        if stage.is_symlink():stage.unlink()
        stage.symlink_to(release);stage.replace(BASE/'current')
        service=Path(args.service_file).resolve()
        try:
            command(['sudo','-n','install','-m','0644',str(service),'/etc/systemd/system/self-agent.service'])
            command(['sudo','-n','systemctl','daemon-reload'])
            command(['sudo','-n','systemctl','enable','--now','self-agent.service'])
            health='http://100.95.110.75:8766/healthz'
            for attempt in range(30):
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(health,timeout=2) as response:
                        if json.load(response).get('status')=='ok':break
                except Exception:
                    if attempt==29:raise
                    time.sleep(1)
            record={'active_release':revision,'artifact_sha256':args.sha256,'rollback_release':str(old) if old else None,'first_install_rollback':'sudo systemctl disable --now self-agent.service','origin_health':'ok','host_binding':'tailscale-only','runtime_build':False}
            (BASE/'state'/'deployment.json').write_text(json.dumps(record,indent=2))
            print(json.dumps(record))
        except BaseException:
            command(['sudo','-n','systemctl','disable','--now','self-agent.service'])
            if old:
                (BASE/'current').unlink();(BASE/'current').symlink_to(old)
            raise

if __name__=='__main__':main()
