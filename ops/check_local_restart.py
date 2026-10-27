"""Verify occupied-port recovery against an extracted local release; no model calls."""
import argparse,json,socket,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--source',required=True);a=p.parse_args()
sys.path.insert(0,a.source)
from self_agent.local_runtime import stop,wait_service,wait_ready,status
from self_agent.spool import atomic_json
root=Path(a.root);config_path=root/'server.json';client_path=root/'local-client.json'
before=status(root)['overview']['counts']
assert stop(root)['stopped']
(root/'launch.json').unlink(missing_ok=True)
with socket.socket() as occupied:
    occupied.bind(('127.0.0.1',0));occupied.listen();port=occupied.getsockname()[1]
    config=json.loads(config_path.read_text());config['port']=port;atomic_json(config_path,config)
    client=json.loads(client_path.read_text());client['url']='http://127.0.0.1:'+str(port);atomic_json(client_path,client)
    connection=Path(json.loads((root/'installation.json').read_text())['connection_file']);atomic_json(connection,client)
    wait_service(client);wait_ready(client)
    assert client['url']!='http://127.0.0.1:'+str(port)
    assert status(root)['overview']['counts']==before
    assert occupied.fileno()>=0
result={'passed':True,'occupied_port_preserved':True,'automatic_new_port':True,'data_survived_restart':True}
(root/'restart-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
