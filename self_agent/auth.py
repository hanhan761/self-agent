import hashlib
import hmac
import secrets
import time


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(value: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    result = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + result


def password_ok(value: str, stored: str) -> bool:
    try:
        return hmac.compare_digest(password_hash(value, stored.split(':')[0]), stored)
    except (ValueError, TypeError):
        return False


class Auth:
    def __init__(self, store, registry=None):
        self.store, self.registry = store, registry

    def create_user(self, username: str, password: str, admin=False):
        if not username.strip() or len(username) > 64 or len(password) < 12:
            raise ValueError('用户名需为 1–64 字符，密码至少 12 字符')
        uid = secrets.token_hex(16)
        with self.store.tx() as db:
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)',
                       (uid, username.strip(), password_hash(password), int(admin), time.time()))
        return uid

    def session(self, uid, identity=None):
        token = secrets.token_urlsafe(32)
        with self.store.tx() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), uid, time.time() + 7 * 86400))
            if identity:
                db.execute('INSERT INTO session_identities VALUES(?,?,?)', (digest(token), *identity))
        return token

    def login(self, username, password):
        with self.store.tx() as db:
            user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            stored = user['password_hash'] if user else password_hash('unknown-account')
            if not password_ok(password, stored) or user is None:
                return None
            return self.session(user['id'])

    def _allowed(self, identity):
        if not identity:
            return True
        provider, fingerprint = identity
        if provider == 'cpa':
            return bool(self.registry and self.registry.allowed(fingerprint))
        if provider == 'local':
            with self.store.tx() as db:
                return bool(db.execute('SELECT 1 FROM api_keys WHERE hash=?', (fingerprint,)).fetchone())
        return False

    def _external_user(self, fingerprint):
        with self.store.tx() as db:
            row = db.execute('SELECT user_id FROM external_identities WHERE provider=? AND identity_hash=?', ('cpa', fingerprint)).fetchone()
            if row:
                uid = row['user_id']
            else:
                uid = self.create_user('cpa_' + secrets.token_hex(6), secrets.token_urlsafe(32))
                db.execute('INSERT INTO external_identities VALUES(?,?,?)', ('cpa', fingerprint, uid))
            return db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()

    def user(self, token, api=False):
        if not token or len(token) > 4096:
            return None
        identity = None
        with self.store.tx() as db:
            if api:
                row = db.execute('SELECT u.* FROM api_keys k JOIN users u ON u.id=k.user_id WHERE k.hash=?', (digest(token),)).fetchone()
                binding = db.execute('SELECT provider,identity_hash FROM api_key_identities WHERE key_hash=?', (digest(token),)).fetchone()
            else:
                row = db.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.hash=? AND s.expires>?', (digest(token), time.time())).fetchone()
                binding = db.execute('SELECT provider,identity_hash FROM session_identities WHERE session_hash=?', (digest(token),)).fetchone()
            if binding:
                identity = (binding['provider'], binding['identity_hash'])
            if not row and api and self.registry:
                fingerprint = self.registry.identity(token)
                if fingerprint:
                    row, identity = self._external_user(fingerprint), ('cpa', fingerprint)
            if not row or not self._allowed(identity):
                return None
            result = dict(row)
            result['_identity'] = identity
            # CPA authentication never grants administrator privileges.
            if identity and identity[0] == 'cpa':
                result['admin'] = 0
            return result

    def login_key(self, token):
        user = self.user(token, api=True)
        if not user:
            return None
        return self.session(user['id'], user['_identity'] or ('local', digest(token)))

    def link_cpa(self, uid, token):
        fingerprint = self.registry.identity(token) if self.registry else None
        if not fingerprint:
            raise ValueError('CPA 密钥无效或已停用')
        with self.store.tx() as db:
            existing = db.execute('SELECT user_id FROM external_identities WHERE provider=? AND identity_hash=?', ('cpa', fingerprint)).fetchone()
            if existing and existing['user_id'] != uid:
                previous=existing['user_id']
                occupied=any(db.execute('SELECT 1 FROM '+table+' WHERE user_id=? LIMIT 1',(previous,)).fetchone() for table in ('memories','sources','jobs'))
                if occupied:raise ValueError('这把 CPA 密钥已关联有资料的其他知识空间，不能覆盖')
                db.execute('UPDATE external_identities SET user_id=? WHERE provider=? AND identity_hash=?',(uid,'cpa',fingerprint))
                db.execute('UPDATE sessions SET user_id=? WHERE hash IN (SELECT session_hash FROM session_identities WHERE provider=? AND identity_hash=?)',(uid,'cpa',fingerprint))
                db.execute('UPDATE api_keys SET user_id=? WHERE hash IN (SELECT key_hash FROM api_key_identities WHERE provider=? AND identity_hash=?)',(uid,'cpa',fingerprint))
                db.execute('UPDATE pairing_codes SET user_id=? WHERE provider=? AND identity_hash=?',(uid,'cpa',fingerprint))
            db.execute('INSERT OR IGNORE INTO external_identities VALUES(?,?,?)', ('cpa', fingerprint, uid))
        return True

    def issue_key(self, uid, name, identity=None):
        token = 'sa_' + secrets.token_urlsafe(32)
        with self.store.tx() as db:
            db.execute('INSERT INTO api_keys VALUES(?,?,?,?,?)', (secrets.token_hex(12), uid, name[:80], digest(token), time.time()))
            if identity:
                db.execute('INSERT INTO api_key_identities VALUES(?,?,?)', (digest(token), *identity))
        return token

    def pair(self, user, name):
        code = secrets.token_urlsafe(24)
        identity = user.get('_identity') or ('', '')
        with self.store.tx() as db:
            db.execute('DELETE FROM pairing_codes WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO pairing_codes VALUES(?,?,?,?,?,?)', (digest(code), user['id'], name[:80], time.time() + 600, *identity))
        return code

    def redeem(self, code):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM pairing_codes WHERE hash=? AND expires>?', (digest(code), time.time())).fetchone()
            if not row:
                return None
            identity = (row['provider'], row['identity_hash']) if row['provider'] else None
            if not self._allowed(identity):
                return None
            db.execute('DELETE FROM pairing_codes WHERE hash=?', (digest(code),))
            token = self.issue_key(row['user_id'], row['name'], identity)
            return {'token': token}
