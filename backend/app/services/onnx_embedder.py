"""Sentence embeddings through ONNX Runtime, without the optimum package.

Runs the ONNX export that ships with the embedding model (for example
BAAI/bge-large-en-v1.5's onnx/model.onnx) with the model's own tokenizer and
pooling settings, so the vectors match the PyTorch model. optimum, which
sentence-transformers uses for its ONNX backend, does not support
transformers 5, hence this small direct implementation.

`encode()` takes the same arguments the rest of the app passes to
SentenceTransformer.encode, so it is a drop-in replacement.
"""
from __future__ import annotations

import json
import os
from typing import List, Sequence, Union

import numpy as np


class OnnxEmbedder:
    def __init__(self, model_id: str, onnx_file: str = "onnx/model.onnx", threads: int = 0):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer

        self.model_id = model_id
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        pooling = {"pooling_mode_cls_token": True}
        try:
            with open(hf_hub_download(model_id, "1_Pooling/config.json")) as f:
                pooling = json.load(f)
        except Exception:
            pass
        self.pooling = "cls" if pooling.get("pooling_mode_cls_token") else "mean"
        self.max_seq_length = 512
        try:
            with open(hf_hub_download(model_id, "sentence_bert_config.json")) as f:
                self.max_seq_length = int(json.load(f).get("max_seq_length", 512))
        except Exception:
            pass

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads:
            options.intra_op_num_threads = threads
        path = hf_hub_download(model_id, onnx_file)
        # The external-data file (onnx/model.onnx_data) is fetched too when the
        # export keeps its weights separately.
        data_name = os.path.basename(onnx_file) + "_data"
        try:
            hf_hub_download(model_id, os.path.join(os.path.dirname(onnx_file), data_name))
        except Exception:
            pass
        self.session = ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.session.get_inputs()}

    def get_sentence_embedding_dimension(self) -> int:
        return int(self.session.get_outputs()[0].shape[-1])

    def _embed_batch(self, texts: List[str]) -> np.ndarray:
        enc = self.tokenizer(texts, padding=True, truncation=True, max_length=self.max_seq_length, return_tensors="np")
        feed = {k: enc[k].astype(np.int64) for k in ("input_ids", "attention_mask", "token_type_ids")
                if k in self.input_names and k in enc}
        if "token_type_ids" in self.input_names and "token_type_ids" not in feed:
            feed["token_type_ids"] = np.zeros_like(feed["input_ids"])
        hidden = self.session.run(None, feed)[0]
        if self.pooling == "cls":
            return hidden[:, 0]
        mask = enc["attention_mask"][..., None].astype(hidden.dtype)
        return (hidden * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)

    def encode(self, sentences: Union[str, Sequence[str]], batch_size: int = 16, show_progress_bar: bool = False,
               normalize_embeddings: bool = False, convert_to_numpy: bool = True, **_: object) -> np.ndarray:
        single = isinstance(sentences, str)
        texts = [sentences] if single else list(sentences)
        if not texts:
            return np.zeros((0, self.get_sentence_embedding_dimension()), dtype=np.float32)
        # Longest first, like sentence-transformers: batches pad less.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]), reverse=True)
        parts = []
        for b in range(0, len(order), batch_size):
            idx = order[b:b + batch_size]
            parts.append((idx, self._embed_batch([texts[i] for i in idx])))
        out = np.zeros((len(texts), parts[0][1].shape[1]), dtype=np.float32)
        for idx, vecs in parts:
            out[idx] = vecs
        if normalize_embeddings:
            out = out / np.clip(np.linalg.norm(out, axis=1, keepdims=True), 1e-12, None)
        return out[0] if single else out
