"""Build the small public client archive off-host, excluding state and secrets."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def build_client():
    output=ROOT/'self_agent/web/downloads'
    output.mkdir(parents=True,exist_ok=True)
    archive=output/'client.zip'
    files=[ROOT/'pyproject.toml',ROOT/'README.md']
    for folder in ['self_agent','scripts']:
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts
                     and p.suffix in ('.py','.html','.css','.js','.ps1') and 'downloads' not in p.parts)
    # Only client runners from scripts, never deploy/control-plane adapters.
    files=[p for p in files if p.parent.name!='scripts' or p.name in ('hook_runner.py','mcp_runner.py')]
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as target:
        for file in sorted(set(files)):
            target.writestr(file.relative_to(ROOT).as_posix(),file.read_bytes())
    manifest={'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size,'python_minimum':'3.11','files':len(set(files))}
    (output/'client-manifest.json').write_text(json.dumps(manifest,indent=2),'utf-8')
    return manifest

if __name__=='__main__':
    print(json.dumps(build_client()))
