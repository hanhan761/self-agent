"""Console-free local service entry point; safe for pythonw and bundled Python."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from self_agent.local_runtime import serve,load_local,local_client,ensure_service
p=argparse.ArgumentParser();p.add_argument('action',choices=['serve','ensure']);p.add_argument('--root',required=True)
a=p.parse_args()
try:
    if a.action=='serve':serve(Path(a.root))
    else:ensure_service(local_client(load_local(a.root)))
except Exception as exc:
    (Path(a.root)/'service-error.json').write_text(json.dumps({'error':type(exc).__name__}),'utf-8')
    raise
