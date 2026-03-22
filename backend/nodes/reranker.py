import asyncio
from typing import List, Dict, Any
from loguru import logger

from state import State


_reranker_model = None


def get_reranker():
    global _reranker_model
    if _reranker_model is None:
        try:
            from sentence_transformers import CrossEncoder
            _reranker_model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-12-v2')
            logger.info("Cross-encoder reranker model loaded")
        except ImportError:
            logger.warning("sentence-transformers not installed. Using fallback reranking.")
            _reranker_model = "fallback"
    return _reranker_model


def rerank_chunks(query: str, chunks: List[Dict[str, Any]], top_k: int = 7) -> List[Dict[str, Any]]:
    """
    Rerank chunks using cross-encoder.
    
    Args:
        query: The user query
        chunks: List of chunk dictionaries with 'chunk_text' key
        top_k: Number of top results to return
    
    Returns:
        Reranked list of chunks (top_k highest scoring)
    """
    if not chunks:
        return []
    
    model = get_reranker()
    
    if model == "fallback":
        return chunks[:top_k]
    
    # Create query-document pairs
    pairs = [(query, chunk.get("chunk_text", "")) for chunk in chunks]
    
    # Score all pairs
    scores = model.predict(pairs)
    
    scored_chunks = list(zip(chunks, scores))
    scored_chunks.sort(key=lambda x: x[1], reverse=True)
    
    return [chunk for chunk, score in scored_chunks[:top_k]]


async def rerank_node(state: State) -> dict:
    """
    Rerank retrieved chunks using cross-encoder model.
    
    This node takes raw_results (50 rows per task) and returns
    the top 7 most relevant chunks per task based on how well
    they ANSWER the specific query (not just semantic similarity).
    
    Input: raw_results, standalone_query
    Output: results (reranked, top 7 per task)
    """
    query = state["standalone_query"]
    raw_results = state.get("raw_results", {})
    
    if not raw_results:
        logger.warning("Reranker: No raw results to rerank")
        return {"results": {}}
    
    reranked_results = {}
    
    for task, rows in raw_results.items():
        if not rows or not isinstance(rows, list):
            reranked_results[task] = rows
            continue
        
        # Skip reranking for aggregate results (COUNT, SUM, AVG) - no chunk_text
        first_row = rows[0] if rows else {}
        if 'chunk_text' not in first_row:
            logger.info(f"Reranker: Skipping aggregate result for '{task[:40]}...'")
            reranked_results[task] = rows
            continue
        
        task_query = f"{query} {task}"
        
        reranked = await asyncio.to_thread(rerank_chunks, task_query, rows, top_k=7)
        reranked_results[task] = reranked
        
        logger.info(f"Reranker: '{task[:40]}...' {len(rows)} → {len(reranked)} chunks")
    
    return {"results": reranked_results}
