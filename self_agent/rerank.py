"""Offline BGE weights; pair tokenization, inference and ranking are FlashRank's."""
import hashlib,logging,threading
from pathlib import Path

MODEL_SHA256='dd98f3e67837d23210a6b7550c08cced4f61845b940ac45be3565840a10f3244'
TOKENIZER_SHA256='48564c5c7d3fa64d85d95e65414a542385f88b0f128fd8d4163fd7a57f2be05c'

class OfflineReranker:
    def __init__(self,directory):
        import importlib.metadata
        import onnxruntime as ort
        from flashrank import Ranker
        if importlib.metadata.version('FlashRank')!='0.2.10':raise RuntimeError('unexpected_reranker_version')
        directory=Path(directory)
        for name,expected in [('model_quantized.onnx',MODEL_SHA256),('tokenizer.json',TOKENIZER_SHA256)]:
            with (directory/name).open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=expected:raise RuntimeError('reranker_checksum_mismatch')
        # Upstream __init__ downloads named models and creates an unrestricted CPU session.
        # Supply the verified offline session; all scoring stays in upstream rerank().
        ranker=Ranker.__new__(Ranker);ranker.model_dir=directory
        ranker.logger=logging.getLogger('self_agent.rerank');ranker.llm_model=None
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        ranker.session=ort.InferenceSession(str(directory/'model_quantized.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        ranker.tokenizer=ranker._get_tokenizer(160)
        self.ranker=ranker;self.lock=threading.Lock()

    def score(self,query,memories):
        from flashrank import RerankRequest
        if not memories:return []
        with self.lock:
            hits=self.ranker.rerank(RerankRequest(query=query,passages=[{'id':m['id'],'text':m['content']} for m in memories[:24]]))
        return [{'id':m['id'],'score':float(m['score'])} for m in hits]
