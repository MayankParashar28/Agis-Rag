import platform
import logging
from sentence_transformers import SentenceTransformer, CrossEncoder

from app.core.config import settings

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
        logger.info(f"Loading SentenceTransformer {settings.EMBEDDING_MODEL} on device: {device}...")
        _embed_model = SentenceTransformer(settings.EMBEDDING_MODEL, device=device)
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
        logger.info(f"Loading CrossEncoder {settings.RERANKER_MODEL} on device: {device}...")
        _reranker = CrossEncoder(settings.RERANKER_MODEL, device=device)
    return _reranker
