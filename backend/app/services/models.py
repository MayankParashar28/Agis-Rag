import platform
import logging
from sentence_transformers import SentenceTransformer, CrossEncoder

logger = logging.getLogger("enterprise_rag.models")

_embed_model = None
_reranker = None

def get_embedding_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        device = "cpu"
        if platform.system() == "Darwin":
            try:
                import torch
                if torch.backends.mps.is_available():
                    device = "mps"
            except ImportError:
                pass
        logger.info(f"Loading SentenceTransformer BAAI/bge-large-en-v1.5 on device: {device}...")
        _embed_model = SentenceTransformer("BAAI/bge-large-en-v1.5", device=device)
    return _embed_model

def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        device = "cpu"
        if platform.system() == "Darwin":
            try:
                import torch
                if torch.backends.mps.is_available():
                    device = "mps"
            except ImportError:
                pass
        logger.info(f"Loading CrossEncoder BAAI/bge-reranker-large on device: {device}...")
        _reranker = CrossEncoder("BAAI/bge-reranker-large", device=device)
    return _reranker
