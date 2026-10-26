import pytest
from fastapi.testclient import TestClient
from self_agent.config import Config
from self_agent.server import create_app
from ops.public_access import ingress_candidate, TUNNEL_ID


def test_https_login_and_key_access(tmp_path):
    app = create_app(Config(tmp_path, secure_cookie=True), start_worker=False)
    uid = app.state.auth.create_user('public-user', 'long-public-password')
    key = app.state.auth.issue_key(uid, 'laptop')
    with TestClient(app, base_url='https://memory.example.com') as client:
        assert client.get('/v1/memories').status_code == 401
        response = client.post('/api/login', json={'username': 'public-user', 'password': 'long-public-password'})
        assert response.status_code == 200
        cookie = response.headers['set-cookie'].lower()
        assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        assert response.headers['strict-transport-security'] == 'max-age=31536000'
        assert client.get('/api/me').json()['id'] == uid
        client.cookies.clear()
        assert client.get('/api/me', headers={'Authorization': 'Bearer ' + key}).json()['id'] == uid
        assert client.post('/v1/memories', json={'content': 'forged'}, headers={'Origin': 'https://evil.example.com'}).status_code == 403


def test_ingress_preserves_existing_routes():
    original = 'tunnel: ' + TUNNEL_ID + '\ningress:\n  - hostname: existing.example.com\n    service: http://127.0.0.1:8500\n  - service: http_status:404\n'
    candidate = ingress_candidate(original, 'memory.example.com')
    addition = '  - hostname: memory.example.com\n    service: http://127.0.0.1:8766\n'
    assert candidate.replace(addition, '') == original
    assert candidate.index('memory.example.com') < candidate.index('http_status:404')
    with pytest.raises(ValueError):
        ingress_candidate(candidate, 'memory.example.com')
    with pytest.raises(ValueError):
        ingress_candidate(original, 'bad/path.example.com')
    with pytest.raises(ValueError):
        ingress_candidate(original.replace(TUNNEL_ID, 'other-tunnel'), 'memory.example.com')
