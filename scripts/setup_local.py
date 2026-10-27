"""Installer entry: no console, user data or credentials in the release."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from self_agent.config import private_root
from self_agent.local_runtime import setup_local
root=private_root()/'local';root.mkdir(parents=True,exist_ok=True)
try:
    result=setup_local('auto')
    (root/'setup-result.json').write_text(json.dumps({'ok':True,'hook_review_required':result['hook_review_required'],'reload_required':True}),'utf-8')
except Exception as exc:
    (root/'setup-result.json').write_text(json.dumps({'ok':False,'error':type(exc).__name__}),'utf-8')
    raise SystemExit(1)
