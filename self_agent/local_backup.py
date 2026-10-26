"""Allowlisted, encrypted snapshots of local agent history; never uploads by itself."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import os
import tempfile
import zipfile
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from .config import private_root

PATTERNS={
    '.claude':['projects/**/*.jsonl','CLAUDE.md','skills/**/SKILL.md'],
    '.codex':['sessions/**/*.jsonl','archived_sessions/**/*.jsonl','AGENTS.md','memories/**/*.md','skills/**/SKILL.md'],
}

def inventory(home=None):
    home=Path(home or Path.home())
    found={}
    for directory,patterns in PATTERNS.items():
        base=home/directory
        for pattern in patterns:
            for file in base.glob(pattern):
                if file.is_file() and not file.is_symlink():
                    resolved=file.resolve()
                    if resolved.is_relative_to(base.resolve()):found[str(file.relative_to(home))]=file
    return found

def backup_local(home=None,destination=None):
    files=inventory(home)
    destination=Path(destination or private_root()/'backups')
    destination.mkdir(parents=True,exist_ok=True,mode=0o700)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    keyfile=destination/'local-history.key'
    if not keyfile.exists():
        with keyfile.open('xb') as stream:stream.write(os.urandom(32))
        keyfile.chmod(0o600)
    key=keyfile.read_bytes()
    manifest=[]
    archive=destination/('history-'+stamp+'.savault')
    with tempfile.TemporaryDirectory(dir=destination) as temp:
        zipname=Path(temp)/'history.zip'
        with zipfile.ZipFile(zipname,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            for name,file in sorted(files.items()):
                sha,size=hashlib.sha256(),0
                with file.open('rb') as source,z.open(name,'w',force_zip64=True) as output:
                    while chunk:=source.read(1024**2):
                        sha.update(chunk);size+=len(chunk);output.write(chunk)
                manifest.append({'path':name.replace('\\','/'),'size':size,'sha256':sha.hexdigest()})
            z.writestr('manifest.json',json.dumps({'format':'self-agent-local-history-v1','files':manifest},ensure_ascii=False))
        nonce=os.urandom(12)
        encoder=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
        encoder.authenticate_additional_data(b'SAHISTORY1')
        with archive.open('xb') as output,zipname.open('rb') as source:
            output.write(b'SAHISTORY1'+nonce)
            while chunk:=source.read(1024**2):output.write(encoder.update(chunk))
            output.write(encoder.finalize());output.write(encoder.tag)
    # Manifest contains only paths, hashes and sizes; contents stay encrypted.
    manifest_path=archive.with_suffix('.manifest.json')
    manifest_path.write_text(json.dumps({'archive':archive.name,'files':manifest},ensure_ascii=False,indent=2),'utf-8')
    return {'archive':str(archive),'manifest':str(manifest_path),'files':len(manifest),'bytes':sum(x['size'] for x in manifest),'key_file':str(keyfile)}


def verify_local_backup(archive,keyfile):
    archive,keyfile=Path(archive),Path(keyfile)
    with tempfile.TemporaryDirectory(dir=archive.parent) as temp:
        output=Path(temp)/'verified.zip'
        with archive.open('rb') as source:
            header=source.read(22)
            if header[:10]!=b'SAHISTORY1':raise ValueError('invalid_history_archive')
            source.seek(-16,2);tag=source.read(16);remaining=archive.stat().st_size-22-16
            decoder=Cipher(algorithms.AES(keyfile.read_bytes()),modes.GCM(header[10:],tag)).decryptor()
            decoder.authenticate_additional_data(b'SAHISTORY1')
            source.seek(22)
            with output.open('wb') as dest:
                while remaining:
                    chunk=source.read(min(1024**2,remaining));remaining-=len(chunk)
                    dest.write(decoder.update(chunk))
                dest.write(decoder.finalize())
        with zipfile.ZipFile(output) as z:
            manifest=json.loads(z.read('manifest.json'))
            for item in manifest['files']:
                sha,size=hashlib.sha256(),0
                with z.open(item['path']) as data:
                    while chunk:=data.read(1024**2):sha.update(chunk);size+=len(chunk)
                if sha.hexdigest()!=item['sha256'] or size!=item['size']:raise ValueError('backup_verification_failed')
        return {'verified':True,'files':len(manifest['files'])}
