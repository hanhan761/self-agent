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
    def __init__(self, store):
        self.store = store

    def create_user(self, username: str, password: str, admin=False):
        if not username.strip() or len(username) > 64 or len(password) < 12:
            raise ValueError('用户名需为 1–64 字符，密码至少 12 字符')
        uid = secrets.token_hex(16)
        with self.store.tx() as db:
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)',
                       (uid, username.strip(), password_hash(password), int(admin), time.time()))
        return uid

    def login(self, username, password):
        with self.store.tx() as db:
            user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            # Run the same KDF for unknown names to reduce username timing differences.
            stored = user['password_hash'] if user else password_hash('unknown-account')
            if not password_ok(password, stored) or user is None:
                return None
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES(?,?,?)',
                       (digest(token), user['id'], time.time() + 7 * 86400))
        return token

    def user(self, token, api=False):
        with self.store.tx() as db:
            if api:
                row = db.execute('SELECT u.* FROM api_keys k JOIN users u ON u.id=k.user_id WHERE k.hash=?',
                                 (digest(token),)).fetchone()
            else:
                row = db.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.hash=? AND s.expires>?',
                                 (digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def issue_key(self, uid, name):
        token = 'sa_' + secrets.token_urlsafe(32)
        with self.store.tx() as db:
            db.execute('INSERT INTO api_keys VALUES(?,?,?,?,?)',
                       (secrets.token_hex(12), uid, name[:80], digest(token), time.time()))
        return token
