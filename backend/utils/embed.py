import os
import asyncio
import threading
from typing import List

from dotenv import load_dotenv

load_dotenv()

_embedder = None
_embed_lock = threading.Lock()

def get_embeddings_model():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        model_name = "intfloat/e5-base-v2"
        _embedder = SentenceTransformer(model_name, device='cpu')
    return _embedder


def _encode_with_lock(texts: List[str], normalize: bool = True) -> list:
    """Thread-safe encoding using a lock."""
    with _embed_lock:
        model = get_embeddings_model()
        return model.encode(texts, normalize_embeddings=normalize)


def get_embedding(text: str) -> List[float]:
    """Get embedding for a single text."""
    embedding = _encode_with_lock(["query: " + text])[0]
    return embedding.tolist()


async def get_embedding_async(text: str) -> List[float]:
    """Async wrapper for get_embedding."""
    return await asyncio.to_thread(get_embedding, text)


async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Get embeddings for multiple texts."""
    prefixed_texts = ["query: " + text for text in texts]
    embeddings = await asyncio.to_thread(_encode_with_lock, prefixed_texts)
    return [e.tolist() for e in embeddings]
