import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root');a=p.parse_args();root=Path(a.root).resolve()
manifest=json.loads((root/'manifest.json').read_text('utf-8'))
for entry in manifest['files']:
    path=(root/entry['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('release_file_missing')
    if path.stat().st_size!=entry['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
        raise ValueError('release_checksum_mismatch')
print(json.dumps({'verified':True,'files':len(manifest['files']),'release_id':manifest['release_id']}))
