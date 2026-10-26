"""Read-only CPA identity validation. Never persist or forward a relay key."""
import hashlib
import json
from pathlib import Path
import threading


class RegistryUnavailable(RuntimeError):
    pass


class CpaRegistry:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.stamp = None
        self.active = set()

    @property
    def configured(self):
        return bool(self.config.cpa_config_file and self.config.cpa_permissions_file)

    def _reload(self):
        if not self.configured:
            return set()
        with self.lock:
            try:
                files = [Path(self.config.cpa_config_file), Path(self.config.cpa_permissions_file)]
                stamp = tuple((p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_ino) for p in files)
                if stamp != self.stamp:
                    import yaml
                    config = yaml.safe_load(files[0].read_text('utf-8'))
                    policy = json.loads(files[1].read_text('utf-8'))
                    keys = config.get('api-keys') if isinstance(config, dict) else None
                    if not isinstance(keys, list) or not all(isinstance(k, str) and k for k in keys):
                        raise ValueError('invalid_registry')
                    if policy.get('schema_version') != 1 or not isinstance(policy.get('entries'), dict):
                        raise ValueError('invalid_policy')
                    active = {hashlib.sha256(k.encode()).hexdigest() for k in keys}
                    for fingerprint, entry in policy['entries'].items():
                        if not isinstance(entry, dict) or type(entry.get('enabled')) is not bool:
                            raise ValueError('invalid_policy_entry')
                        if not entry['enabled']:
                            active.discard(fingerprint)
                    self.active, self.stamp = active, stamp
                return self.active.copy()
            except Exception:
                self.active, self.stamp = set(), None
                raise RegistryUnavailable('CPA 密钥认证暂时不可用，请稍后重试') from None

    def identity(self, token):
        if not self.configured or not isinstance(token, str) or not 16 <= len(token) <= 4096:
            return None
        identity = hashlib.sha256(token.encode()).hexdigest()
        return identity if self.allowed(identity) else None

    def allowed(self, identity):
        return identity in self._reload()
