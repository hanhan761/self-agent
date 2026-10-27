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
    cpa_config_file: str = ''
    cpa_permissions_file: str = ''
    local: bool = False
    local_instance_id: str = ''
    local_user_id: str = ''
    local_started_at: float = 0
    index_backend: str = 'mem0'
    model_cache: str = ''
    xjcode_home: str = ''
    xjtu_account_fingerprint: str = ''
    semantic: bool = False
    embedding_model: str = 'BAAI/bge-m3'
    embedding_device: str = 'cpu'
    embedding_dims: int = 1024
    xjtu_credentials: str = ''
    xjtu_native_config: str = ''
    xjtu_model: str = 'qwen3.8-max'
    xjtu_url: str = 'http://ai.xjtu.edu.cn:30040/'
    allow_campus_http: bool = False
    max_data_bytes: int = 2 * 1024**3
    min_free_bytes: int = 512 * 1024**2
    max_capture_batches: int = 1000
    max_capture_bytes: int = 64 * 1024**2
    max_pending_jobs: int = 1000
    min_recall_similarity: float = 0.55
    min_lexical_coverage: float = 0.25
    min_rerank_score: float = 0.2
    projection_batch_size: int = 128

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
