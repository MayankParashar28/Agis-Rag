import numpy as np

from app.services.onnx_embedder import OnnxEmbedder


class FakeTokenizer:
    def __call__(self, texts, **kw):
        n = max(len(t) for t in texts)
        ids = np.array([[len(t)] + [1] * (n - 1) for t in texts], dtype=np.int64)
        mask = np.array([[1] * len(t) + [0] * (n - len(t)) for t in texts], dtype=np.int64)
        return {"input_ids": ids, "attention_mask": mask}


class FakeSession:
    def __init__(self):
        self.batches = []

    def run(self, _, feed):
        self.batches.append(feed["input_ids"].shape[0])
        ids = feed["input_ids"].astype(np.float32)
        # hidden[b, t] = [len(text), 1] at every token -> CLS == mean here except mask
        return [np.stack([np.stack([ids[:, 0], np.ones(len(ids))], axis=1)] * ids.shape[1], axis=1)]


def _embedder(pooling="cls"):
    e = OnnxEmbedder.__new__(OnnxEmbedder)
    e.tokenizer, e.session, e.pooling, e.max_seq_length = FakeTokenizer(), FakeSession(), pooling, 512
    e.input_names = {"input_ids", "attention_mask", "token_type_ids"}
    return e


def test_results_come_back_in_input_order_and_batched():
    e = _embedder()
    texts = ["a", "ccc", "bb", "dddd", "e"]
    out = e.encode(texts, batch_size=2)
    assert out[:, 0].tolist() == [1, 3, 2, 4, 1]        # each vector belongs to its own text
    assert e.session.batches == [2, 2, 1]


def test_normalize_and_single_string():
    e = _embedder("mean")
    v = e.encode("abcd", normalize_embeddings=True)
    assert v.shape == (2,) and abs(float(np.linalg.norm(v)) - 1.0) < 1e-6
