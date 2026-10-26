"""Checksum-verified, no-build installation/update. Use pinned yun control."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
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
    parser.add_argument('--bootstrap')
    parser.add_argument('--service-file',required=True)
    parser.add_argument('--semantic',action='store_true')
    args=parser.parse_args()
    artifact=Path(args.artifact).resolve()
    if not artifact.is_relative_to(BASE/'incoming'):raise ValueError('artifact_outside_incoming')
    if hashlib.sha256(artifact.read_bytes()).hexdigest()!=args.sha256:raise ValueError('artifact_digest_mismatch')
    with (BASE/'deploy.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        previous=(BASE/'current').resolve() if (BASE/'current').is_symlink() else None
        with zipfile.ZipFile(artifact) as archive:
            expanded=sum(i.file_size for i in archive.infolist())
            if artifact.stat().st_size>512*1024**2 or expanded>2*1024**3:raise RuntimeError('artifact_exceeds_small_service_budget')
            if shutil.disk_usage(BASE).free-expanded<100*1024**3:raise RuntimeError('insufficient_project_disk_reserve')
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
                content=archive.read(item)
                if item.filename!='release.json' and hashlib.sha256(content).hexdigest()!=manifest['files'].get(item.filename):raise ValueError('release_file_digest_mismatch')
                target=release/relative;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(content)
        env=os.environ.copy()
        env.update(PYTHONPATH=str(release/'vendor')+':'+str(release),
                   PYTHONDONTWRITEBYTECODE='1',SELF_AGENT_DATA=str(BASE/'state'),
                   SELF_AGENT_CONFIG=str(BASE/'config/server.json'))
        command([str(PYTHON),'-c','from self_agent.server import create_app;import jieba,cryptography,uvicorn'],env=env,cwd=release)
        config_file=BASE/'config/server.json'
        config_file.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        old_config=config_file.read_bytes() if config_file.exists() else None
        config=json.loads(old_config) if old_config else {
            'host':'100.95.110.75','port':8766,'semantic':False,'allow_campus_http':True,
            'xjtu_native_config':'/home/codex-admin/services/jiaoxiaozhi-router/experiment-native.json',
            'xjtu_model':'qwen3.8-max','max_data_bytes':512*1024**2}
        if args.semantic:
            # This exact encoder is already cached; never fetch model weights on-host.
            config.update(semantic=True,embedding_model='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                          embedding_dims=384,embedding_device='cpu')
        config_file.write_text(json.dumps(config,indent=2));config_file.chmod(0o600)
        state=BASE/'state';state.mkdir(exist_ok=True,mode=0o700)
        database=state/'memory.sqlite3'
        if previous and database.exists():
            backups=state/'backups';backups.mkdir(exist_ok=True,mode=0o700)
            with sqlite3.connect(database) as source,sqlite3.connect(backups/('before-'+revision[:12]+'.sqlite3')) as destination:
                source.backup(destination)
        if not previous:
            if not args.bootstrap:raise ValueError('first_install_requires_bootstrap')
            bootstrap=Path(args.bootstrap).resolve()
            if not bootstrap.is_relative_to(BASE/'incoming'):raise ValueError('invalid_bootstrap_path')
            seed="""import json,sys,time
from pathlib import Path
from self_agent.config import Config
from self_agent.store import Store
from self_agent.auth import Auth,digest
c=Config.load();c.prepare();s=Store(c.data_dir/'memory.sqlite3')
d=json.loads(Path(sys.argv[1]).read_text())
if s.db.execute('SELECT count(*) FROM users').fetchone()[0]:raise RuntimeError('bootstrap_requires_empty_users')
uid=Auth(s).create_user(d['username'],d['password'],True)
with s.tx() as db:db.execute('INSERT INTO api_keys VALUES(?,?,?,?,?)',(d['key_id'],uid,'initial-client',digest(d['token']),time.time()))
s.close()
"""
            command([str(PYTHON),'-c',seed,str(bootstrap)],env=env,cwd=release)
            bootstrap.unlink()
        service=Path(args.service_file).resolve()
        prior_service=Path('/etc/systemd/system/self-agent.service')
        prior_unit=prior_service.read_bytes() if prior_service.exists() else None
        stage=BASE/'current.next'
        if stage.is_symlink():stage.unlink()
        stage.symlink_to(release);stage.replace(BASE/'current')
        try:
            command(['sudo','-n','systemd-analyze','verify',str(service)])
            command(['sudo','-n','install','-m','0644',str(service),str(prior_service)])
            command(['sudo','-n','systemctl','daemon-reload'])
            command(['sudo','-n','systemctl','enable','self-agent.service'])
            command(['sudo','-n','systemctl','restart','self-agent.service'])
            health='http://100.95.110.75:8766/healthz'
            for attempt in range(30):
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(health,timeout=2) as response:
                        if json.load(response).get('status')=='ok':break
                except Exception:
                    if attempt==29:raise
                    time.sleep(1)
            record={'active_release':revision,'artifact_sha256':args.sha256,'rollback_release':str(previous) if previous else None,
                    'origin_health':'ok','host_binding':'tailscale-only','runtime_build':False}
            (state/'deployment.json').write_text(json.dumps(record,indent=2))
            print(json.dumps(record))
        except BaseException:
            if old_config:config_file.write_bytes(old_config)
            if previous:
                (BASE/'current').unlink();(BASE/'current').symlink_to(previous)
                if prior_unit:
                    saved=BASE/'incoming/rollback.service';saved.write_bytes(prior_unit)
                    command(['sudo','-n','install','-m','0644',str(saved),str(prior_service)])
                command(['sudo','-n','systemctl','daemon-reload'])
                command(['sudo','-n','systemctl','restart','self-agent.service'])
            else:command(['sudo','-n','systemctl','disable','--now','self-agent.service'])
            raise

if __name__=='__main__':main()
