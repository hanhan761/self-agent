import ast
import hashlib
import json
from pathlib import Path
from fastapi.testclient import TestClient
from self_agent.config import Config
from self_agent.server import create_app


def test_generated_instruction_is_authenticated_one_use_and_has_no_long_lived_key(tmp_path):
    app=create_app(Config(tmp_path),start_worker=False)
    uid=app.state.auth.create_user('alice','long-alice-password')
    key=app.state.auth.issue_key(uid,'test')
    with TestClient(app,base_url='https://memory.example.com') as client:
        assert client.post('/api/pairing/agent',json={}).status_code==401
        result=client.post('/api/pairing/agent',json={'client':'auto'},headers={'Authorization':'Bearer '+key})
        assert result.status_code==200
        prompt=result.json()['instruction']
        assert len(prompt.splitlines())>=5 and key not in prompt
        assert 'https://memory.example.com/connect/agent.md' in prompt
        code=next(line.split('：',1)[1] for line in prompt.splitlines() if line.startswith('一次性配对码：'))
        assert not any(code in line for line in prompt.splitlines() if 'https://' in line)
        assert all(code not in row for row in app.state.store.db.iterdump())
        response=client.post('/api/pairing/redeem',json={'code':code})
        assert response.status_code==200
        assert client.post('/api/pairing/redeem',json={'code':code}).status_code==401
        assert client.get('/api/me',headers={'Authorization':'Bearer '+response.json()['token']}).json()['id']==uid


def test_public_agent_guide_and_bootstrap_checksum(tmp_path):
    app=create_app(Config(tmp_path),start_worker=False)
    with TestClient(app,base_url='https://memory.example.com') as client:
        guide=client.get('/connect/agent.md')
        assert guide.status_code==200 and 'https://memory.example.com/connect/manifest.json' in guide.text
        assert 'Do not request' in guide.text and '/hooks' in guide.text
        manifest=client.get('/connect/manifest.json').json()
        script=client.get('/connect/bootstrap.py').content
        assert hashlib.sha256(script).hexdigest()==manifest['sha256']
        tree=ast.parse(script)
        # Pairing data uses a real line separator over stdin, never an argument.
        pipe=[n for n in ast.walk(tree) if isinstance(n,ast.BinOp) and isinstance(n.left,ast.Name) and n.left.id=='pair']
        assert len(pipe)==1 and pipe[0].right.value=='\n'


def test_auto_client_detection_uses_current_profile(tmp_path,monkeypatch):
    import httpx
    import self_agent.onboarding as onboarding
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    monkeypatch.setattr(onboarding.shutil,'which',lambda name:None)
    monkeypatch.setattr(onboarding,'private_root',lambda:tmp_path/'private')
    (tmp_path/'.claude').mkdir()
    real_client=httpx.Client
    device='sa_private-device-test-key'
    def handle(request):
        if request.url.path=='/api/pairing/redeem':return httpx.Response(200,json={'token':device})
        return httpx.Response(200,json={'username':'alice','id':'alice'})
    monkeypatch.setattr(onboarding.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(handle),**kwargs))
    installed=[]
    monkeypatch.setattr(onboarding,'install_client',lambda name:installed.append(name))
    result=onboarding.setup('https://memory.example.com',pair_code='x'*32)
    assert installed==['claude'] and result['clients']==['claude']
    assert Path(result['key_file']).read_text('utf-8')==device
    assert json.loads((tmp_path/'private/client.json').read_text())['token_file']==result['key_file']


def test_auto_client_detection_refuses_unknown_client(tmp_path,monkeypatch):
    import pytest
    import self_agent.onboarding as onboarding
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    monkeypatch.setattr(onboarding.shutil,'which',lambda name:None)
    with pytest.raises(ValueError,match='未检测到'):
        onboarding.setup('https://memory.example.com',pair_code='x'*32)
