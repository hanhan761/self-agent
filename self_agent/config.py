from dataclasses import dataclass
from pathlib import Path
import json
import os


def private_root() -> Path:
    fallback = Path.home() / 'AppData' / 'Local' if os.name == 'nt' else Path.home() / '.local' / 'share'
    base = Path(os.environ.get('LOCALAPPDATA', fallback))
    return base / 'self-agent'


@dataclass
class Config:
    data_dir: Path
    host: str = '127.0.0.1'
    port: int = 8766
    secure_cookie: bool = False
    semantic: bool = False
    embedding_model: str = 'BAAI/bge-m3'
    embedding_device: str = 'cpu'
    xjtu_credentials: str = ''
    xjtu_native_config: str = ''
    xjtu_model: str = 'qwen3.8-max'
    xjtu_url: str = 'http://ai.xjtu.edu.cn:30040/'
    allow_campus_http: bool = False
    max_data_bytes: int = 2 * 1024**3

    @classmethod
    def load(cls):
        root = Path(os.environ.get('SELF_AGENT_DATA', private_root()))
        config_file = Path(os.environ.get('SELF_AGENT_CONFIG', root / 'server.json'))
        values = json.loads(config_file.read_text('utf-8')) if config_file.exists() else {}
        values['data_dir'] = root
        return cls(**values)

    def prepare(self):
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != 'nt':
            self.data_dir.chmod(0o700)
