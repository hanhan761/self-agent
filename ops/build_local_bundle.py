"""Build a bounded offline Windows installer from an already prepared private runtime."""
import argparse,hashlib,json,os,subprocess,zipfile,tomllib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--output',default='dist');a=p.parse_args()
root=Path(__file__).resolve().parents[1];runtime=Path(a.runtime).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
version=tomllib.loads((root/'pyproject.toml').read_text('utf-8'))['project']['version']
allowed={'Lib','source','models','bin','licenses'}
files=[]
for f in sorted(runtime.rglob('*')):
    if not f.is_file() or '__pycache__' in f.parts or f.suffix=='.pyc':continue
    rel=f.relative_to(runtime)
    if f.name=='manifest.json':continue
    if rel.parts[0] not in allowed and not (len(rel.parts)==1 and f.suffix.lower() in ('.exe','.dll','.pyd','.zip','._pth','.txt','.cat')):
        raise ValueError('unapproved_runtime_artifact: '+str(rel))
    if f.suffix in ('.sqlite3','.db','.dpapi','.token') or f.suffix=='.pem' and rel.as_posix()!='Lib/site-packages/certifi/cacert.pem':
        raise ValueError('private_material_in_release')
    sha=hashlib.sha256(f.read_bytes()).hexdigest();files.append({'path':rel.as_posix(),'bytes':f.stat().st_size,'sha256':sha})
manifest={'version':version,'python':'3.13.17','backend':'mcp-memory-service 12.4.0','files':files}
release_id=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()[:12]
manifest['release_id']=release_id
(runtime/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
archive=out/('self-agent-local-'+version+'-'+release_id+'-windows-x64.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for entry in files:z.write(runtime/entry['path'],entry['path'])
    z.write(runtime/'manifest.json','manifest.json')
sha=hashlib.sha256(archive.read_bytes()).hexdigest()
source=(root/'ops/LocalSetup.cs').read_text('utf-8').replace('RELEASE_ID',release_id).replace('BUNDLE_SHA256',sha).replace('BUNDLE_VERSION',version)
cs=out/'LocalSetup.generated.cs';cs.write_text(source,'utf-8')
installer=out/('Self-Agent-Local-'+version+'-'+release_id+'-Setup.exe')
csc=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
command=[str(csc),'/nologo','/target:winexe','/platform:x64','/optimize+',
    '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
    '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
    '/reference:Microsoft.CSharp.dll','/out:'+str(installer),'/resource:'+str(archive)+',bundle.zip',str(cs)]
r=subprocess.run(command,capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
if r.returncode:raise RuntimeError(r.stdout+r.stderr)
result={'release_id':release_id,'archive':str(archive),'archive_sha256':sha,'archive_bytes':archive.stat().st_size,
        'installer':str(installer),'installer_sha256':hashlib.sha256(installer.read_bytes()).hexdigest(),
        'installer_bytes':installer.stat().st_size,'files':len(files)}
(out/'local-release.json').write_text(json.dumps(result,indent=2),'utf-8')
(out/'SHA256SUMS.txt').write_text(result['installer_sha256']+'  '+installer.name+'\n'+sha+'  '+archive.name+'\n','utf-8')
print(json.dumps(result))
