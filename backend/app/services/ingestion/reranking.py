"""Integrity-pinned CPU cross encoder. No runtime downloads or remote inference."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from functools import lru_cache
from pathlib import Path

MANIFEST_SHA256 = "c4aa06cd6796025da53c16ae437049965eea2c3d1172ece0ad951a0b61ebf773"
MODEL_REVISION = "a09144355adeed5f58c8ed011d209bf8ee5a1fec"
MODEL_ROOT = Path("/opt/wbs-models/ms-marco-MiniLM-L-6-v2")


class OnnxReranker:
    """Bounded pair scoring; raw relevance logits are not answer confidence."""

    def __init__(self, root: Path = MODEL_ROOT):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        manifest = (root / "model-manifest.json").read_bytes()
        if hashlib.sha256(manifest).hexdigest() != MANIFEST_SHA256:
            raise ValueError("Reranker manifest integrity check failed")
        for entry in json.loads(manifest)["files"]:
            name = entry["path"]
            if Path(name).name != name:
                raise ValueError("Invalid reranker artifact name")
            target = root / name
            if target.is_symlink() or target.stat().st_size != entry["size"]:
                raise ValueError("Reranker artifact integrity check failed")
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                while data := stream.read(1024 * 1024):
                    digest.update(data)
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError("Reranker artifact integrity check failed")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(
            str(root / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512, strategy="only_second")
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._lock = threading.Lock()

    def score(self, query: str, texts: list[str]) -> tuple[float, ...]:
        import numpy as np

        if not query.strip() or len(query) > 2000 or len(texts) > 60:
            raise ValueError("Reranking input exceeds its bound")
        if any(not text.strip() or len(text) > 100_000 for text in texts):
            raise ValueError("Reranking passage exceeds its bound")
        with self._lock:
            self.tokenizer.no_truncation()
            if len(self.tokenizer.encode(query).ids) > 128:
                raise ValueError("Reranking query exceeds 128 tokens")
            windows = []
            owners = []
            for index, value in enumerate(texts):
                encoded = self.tokenizer.encode(value, add_special_tokens=False)
                if len(encoded.ids) <= 380:
                    pieces = [value]
                else:
                    # Score evidence throughout a long chunk, rather than just
                    # its opening sentence. At most three bounded source windows.
                    count = len(encoded.ids)
                    starts = sorted({0, max(0, (count - 256) // 2), count - 256})
                    pieces = [
                        value[
                            encoded.offsets[start][0] : encoded.offsets[
                                min(start + 256, count) - 1
                            ][1]
                        ]
                        for start in starts
                    ]
                windows.extend(pieces)
                owners.extend([index] * len(pieces))
            self.tokenizer.enable_truncation(max_length=512, strategy="only_second")
            scores = []
            inputs = {item.name for item in self.session.get_inputs()}
            for start in range(0, len(windows), 4):
                encoded = self.tokenizer.encode_batch(
                    [(query, value) for value in windows[start : start + 4]]
                )
                features = {
                    "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                    "attention_mask": np.asarray(
                        [item.attention_mask for item in encoded], dtype=np.int64
                    ),
                    "token_type_ids": np.asarray(
                        [item.type_ids for item in encoded], dtype=np.int64
                    ),
                }
                output = self.session.run(
                    None, {key: value for key, value in features.items() if key in inputs}
                )[0]
                scores.extend(float(value) for value in output.reshape(-1))
        if len(scores) != len(windows) or not all(math.isfinite(value) for value in scores):
            raise ValueError("Reranker produced invalid scores")
        combined = [float("-inf")] * len(texts)
        for owner, score in zip(owners, scores, strict=True):
            combined[owner] = max(combined[owner], score)
        return tuple(combined)


@lru_cache(maxsize=1)
def get_reranker() -> OnnxReranker:
    return OnnxReranker()
