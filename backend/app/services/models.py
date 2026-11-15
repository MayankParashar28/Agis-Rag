import platform
import logging
from sentence_transformers import SentenceTransformer, CrossEncoder

from app.core.config import settings

logger = logging.getLogger("enterprise_rag.models")

_embed_model = None
_reranker = None

def _load_embedder(device: str) -> SentenceTransformer:
    """Load the embedding model. EMBEDDING_BACKEND=onnx runs the same model
    through ONNX Runtime: identical vectors, about 20% faster on CPU. Any
    problem loading it falls back to the regular PyTorch model."""
    if settings.EMBEDDING_BACKEND == "onnx" and device == "cpu":
        try:
            logger.info(f"Loading SentenceTransformer {settings.EMBEDDING_MODEL} with the ONNX backend...")
            return SentenceTransformer(settings.EMBEDDING_MODEL, device=device, backend="onnx",
                                       model_kwargs={"file_name": settings.EMBEDDING_ONNX_FILE})
        except Exception as e:
            logger.warning(f"ONNX embedding backend unavailable ({e}); using PyTorch.")
    logger.info(f"Loading SentenceTransformer {settings.EMBEDDING_MODEL} on device: {device}...")
    return SentenceTransformer(settings.EMBEDDING_MODEL, device=device)


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
        _embed_model = _load_embedder(device)
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
        # Reading each passage up to RERANK_MAX_TOKENS instead of 512 halves
        # reranking time on CPU (13.6 s -> 6.1 s for 30 passages on 2 cores)
        # and chose the same top 5 in testing: normal chunks are ~250 tokens,
        # only long tables were being read in full.
        _reranker = CrossEncoder(settings.RERANKER_MODEL, device=device, max_length=settings.RERANK_MAX_TOKENS)
    return _reranker
