"""Build a small immutable source layer over a verified full release."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    from build_client import build_client
    build_client()
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',required=True)
    parser.add_argument('--revision',required=True)
    args=parser.parse_args()
    with zipfile.ZipFile(args.base) as base:
        manifest=json.loads(base.read('release.json'))
    parent=manifest['source_revision']
    manifest.update(base_release=parent,source_revision=args.revision,built_at=datetime.now(timezone.utc).isoformat())
    files={}
    for file in (ROOT/'self_agent').rglob('*'):
        if file.is_file() and '__pycache__' not in file.parts and file.suffix!='.pyc':
            name=file.relative_to(ROOT).as_posix()
            files[name]=file.read_bytes()
    for name in list(manifest['files']):
        if name.startswith('self_agent/') and name not in files:del manifest['files'][name]
    changed={}
    for name,content in files.items():
        sha=hashlib.sha256(content).hexdigest()
        if manifest['files'].get(name)!=sha:changed[name]=content
        manifest['files'][name]=sha
    artifact=ROOT/'dist'/('self-agent-patch-'+args.revision[:12]+'.zip')
    with zipfile.ZipFile(artifact,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('release.json',json.dumps(manifest,indent=2))
        for name,content in changed.items():archive.writestr(name,content)
    result={'artifact':str(artifact),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'source_revision':args.revision,'base_release':parent,'bytes':artifact.stat().st_size,'changed_files':list(changed)}
    artifact.with_suffix('.manifest.json').write_text(json.dumps(result,indent=2),'utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
