import logging
from typing import Optional

import numpy as np

from app.utils import sow_server

logger = logging.getLogger("EmbeddingProvider")

MODEL_NAME = "e5-small-en-ru"


class RemoteEmbedder:
    """
    Stand-in for SentenceTransformer(e5-small-en-ru): the model runs on the Soul of Waifu
    server (/v1/embeddings). encode() keeps sentence-transformers' shapes: a string gives one
    vector, a list gives one row per item. Callers add the e5 "query: "/"passage: " prefixes.
    """

    def encode(self, sentences, convert_to_numpy: bool = True, **_kwargs) -> np.ndarray:
        single = isinstance(sentences, str)
        texts = [sentences] if single else list(sentences)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vecs = sow_server.embed(texts)
        return vecs[0] if single else vecs


_embedder = RemoteEmbedder()


def get_embedder(device: str = "cpu") -> Optional[RemoteEmbedder]:
    """
    The embedder, or None while the server is unreachable or has no embedding model; callers
    then use their simplified non-semantic fallback, as they did without sentence-transformers.
    """
    caps = sow_server.capabilities()
    if not caps or not caps.get("embeddings", {}).get("available"):
        return None
    return _embedder


def is_loaded() -> bool:
    return get_embedder() is not None


def reset_failure_state() -> None:
    sow_server.reset()


def unload() -> None:
    """Nothing to free here: the model lives on the server."""
