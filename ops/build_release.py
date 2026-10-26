"""Build a bounded Linux release on the development machine; never include runtime state."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--revision',required=True)
    parser.add_argument('--include-semantic',action='store_true')
    args=parser.parse_args()
    target=ROOT/'dist'/'release'
    if target.exists():
        # Only the declared, generated release directory may be replaced.
        if target.resolve()!=ROOT.resolve()/'dist'/'release':raise ValueError('invalid_build_path')
        shutil.rmtree(target)
    target.mkdir(parents=True)
    vendor=target/'vendor';vendor.mkdir()
    wheels={w.name:w for w in (ROOT/'dist'/'wheels').glob('*.whl')}
    if args.include_semantic:
        wheels.update({w.name:w for w in (ROOT/'dist'/'semantic-wheels').glob('*.whl')})
    for wheel in wheels.values():
        with zipfile.ZipFile(wheel) as archive:
            for item in archive.infolist():
                p=Path(item.filename)
                if p.is_absolute() or '..' in p.parts:raise ValueError('invalid_wheel_path')
                if '.data' in p.parts[0]:
                    if len(p.parts)>2 and p.parts[1] in ('purelib','platlib'):p=Path(*p.parts[2:])
                    else:continue
                destination=vendor/p
                if item.is_dir():destination.mkdir(parents=True,exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    destination.write_bytes(archive.read(item))
    for folder in ['self_agent']:
        shutil.copytree(ROOT/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    manifest={'version':1,'source_revision':args.revision,'built_at':datetime.now(timezone.utc).isoformat(),'architecture':'linux-x86_64-cpython312','files':{}}
    for file in sorted(target.rglob('*')):
        if file.is_file():manifest['files'][file.relative_to(target).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    (target/'release.json').write_text(json.dumps(manifest,indent=2),'utf-8')
    output=ROOT/'dist'/('self-agent-'+args.revision[:12]+'.zip')
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for file in sorted(target.rglob('*')):
            if file.is_file():archive.write(file,file.relative_to(target).as_posix())
    result={'artifact':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'bytes':output.stat().st_size,'expanded_bytes':sum(p.stat().st_size for p in target.rglob('*') if p.is_file()),'source_revision':args.revision}
    output.with_suffix('.manifest.json').write_text(json.dumps(result,indent=2),'utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
