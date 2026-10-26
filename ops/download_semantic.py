"""Prepare Linux CPU semantic dependencies off-host, without downloading model weights."""
import json
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
out=root/'dist'/'semantic-wheels';out.mkdir(parents=True,exist_ok=True)
log=root/'dist'/'semantic-download.log'
args=[sys.executable,'-m','pip','download','--disable-pip-version-check','--proxy','http://127.0.0.1:7890',
      '--platform','manylinux_2_28_x86_64','--platform','manylinux2014_x86_64','--python-version','312',
      '--abi','cp312','--abi','abi3','--abi','none','--only-binary=:all:','--dest',str(out),
      '--extra-index-url','https://download.pytorch.org/whl/cpu','torch==2.8.0+cpu','mem0ai==2.2.1',
      'sentence-transformers==6.2.0']
with log.open('w',encoding='utf-8') as stream:
    result=subprocess.run(args,stdout=stream,stderr=stream,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
(root/'dist'/'semantic-download.status.json').write_text(json.dumps({'exit_code':result.returncode}),'utf-8')
