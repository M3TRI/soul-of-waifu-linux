"""Embeddings (e5-small-en-ru) and emotion detection (go-emotions), both small enough for CPU."""
import asyncio

import numpy as np

from .models import manager

E5_DIR = "/opt/sow/e5-small-en-ru"
EMOTIONS_DIR = "/opt/sow/emotions"
EMBEDDING_MODEL = "e5-small-en-ru"
# Label order of the detector's classifier head, as in interface_signals.detect_emotion.
EMOTIONS = [
    "admiration", "amusement", "anger", "annoyance", "approval", "caring", "confusion", "curiosity",
    "desire", "disappointment", "disapproval", "disgust", "embarrassment", "excitement", "fear",
    "gratitude", "grief", "love", "nervousness", "neutral", "optimism", "pride", "realization",
    "relief", "remorse", "surprise", "joy", "sadness",
]


async def embed(texts: list[str]) -> list[list[float]]:
    def load():
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(E5_DIR, device="cpu")

    slot = await manager.get("embeddings", load, pinned=True)
    async with slot.lock:
        vecs = await asyncio.to_thread(slot.obj.encode, texts, convert_to_numpy=True)
    return np.asarray(vecs, dtype=np.float32).tolist()


async def emotions(texts: list[str]) -> list[dict]:
    def load():
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        return (AutoTokenizer.from_pretrained(EMOTIONS_DIR),
                AutoModelForSequenceClassification.from_pretrained(EMOTIONS_DIR).eval())

    slot = await manager.get("emotions", load, pinned=True)

    def run():
        import torch
        tokenizer, model = slot.obj
        inputs = tokenizer(texts, return_tensors="pt", truncation=True, padding=True)
        with torch.no_grad():
            probs = torch.softmax(model(**inputs).logits, dim=1)
        out = []
        for row in probs:
            idx = int(torch.argmax(row))
            out.append({"label": EMOTIONS[idx], "id": idx, "score": round(float(row[idx]), 4)})
        return out

    async with slot.lock:
        return await asyncio.to_thread(run)
