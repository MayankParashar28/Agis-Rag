"""Build-time check for the ONNX embedding backend.

Downloads the ONNX export of the embedding model into the image and checks
that it produces the same vectors as the PyTorch model. Never fails the
build: if ONNX cannot load or disagrees, it says so, and at runtime the app
falls back to PyTorch on its own (app/services/models.py).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
ONNX_FILE = os.environ.get("EMBEDDING_ONNX_FILE", "onnx/model.onnx")
texts = ["Refunds are accepted within 30 days of purchase.",
         "| Region | Revenue |\n|---|---|\n| North | 1200 |"]

try:
    from sentence_transformers import SentenceTransformer
    try:
        from onnx_embedder import OnnxEmbedder            # copied next to this script in the image
    except ImportError:
        from app.services.onnx_embedder import OnnxEmbedder
    ref = SentenceTransformer(MODEL, device="cpu").encode(texts, normalize_embeddings=True)
    got = OnnxEmbedder(MODEL, ONNX_FILE).encode(texts, normalize_embeddings=True)
    similarity = float(np.min(np.sum(ref * got, axis=1)))
    status = "OK" if similarity > 0.9999 else "MISMATCH"
    print(f"ONNX embedding check: {status} (min cosine {similarity:.6f})")
except Exception as e:  # noqa: BLE001
    print(f"ONNX embedding check: UNAVAILABLE ({type(e).__name__}: {e}); the app will use PyTorch.")
sys.exit(0)
