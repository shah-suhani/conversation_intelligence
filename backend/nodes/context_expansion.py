"""
Context expansion node: Fetch surrounding chunks for full conversational context.

This is a KEY NEW COMPONENT that fixes the Context Fragmentation problem.
When causes and effects are in different chunks, this ensures the LLM
gets the full picture by fetching surrounding chunks.
"""

import asyncio
from typing import List, Dict, Any
from loguru import logger

from state import State
from utils.db import fetch_chunk_window


async def expand_chunk_context(
    chunk: Dict[str, Any], 
    window_size: int = 2
) -> Dict[str, Any]:
    """
    Expand a single chunk with its surrounding context.
    
    Args:
        chunk: Chunk dictionary with transcript_id and chunk_id
        window_size: Number of chunks before/after to include
    
    Returns:
        Chunk with added 'expanded_context' field
    """
    transcript_id = chunk.get("transcript_id")
    chunk_id = chunk.get("chunk_id")
    
    # If we don't have chunk_id, just return the chunk as-is
    if chunk_id is None or not transcript_id:
        return {**chunk, "expanded_context": chunk.get("chunk_text", "")}
    
    try:
        # Fetch surrounding chunks using chunk_id
        window_chunks = await fetch_chunk_window(
            transcript_id=str(transcript_id),
            chunk_id=int(chunk_id),
            window_size=window_size
        )
        
        if window_chunks:
            # Concatenate all chunk texts in order
            expanded_text = "\n---\n".join([
                c.get("chunk_text", "") for c in window_chunks
            ])
            return {**chunk, "expanded_context": expanded_text}
        else:
            return {**chunk, "expanded_context": chunk.get("chunk_text", "")}
            
    except Exception as e:
        logger.warning(f"Context expansion failed for chunk: {e}")
        return {**chunk, "expanded_context": chunk.get("chunk_text", "")}


async def context_expansion_node(state: State) -> dict:
    """
    Expand context for top reranked chunks by fetching surrounding chunks.
    
    This addresses the "Context Fragmentation" problem where:
    - The "Cause" (Agent was rude at minute 2) and 
    - The "Effect" (Customer asked for refund at minute 10)
    are in different chunks.
    
    By fetching surrounding chunks (window ±2), the LLM gets the full
    conversational flow and can identify causality.
    
    Input: results (reranked chunks)
    Output: results (with expanded_context field added)
    """
    results = state.get("results", {})
    
    if not results:
        logger.warning("Context Expansion: No results to expand")
        return {"results": {}}
    
    expanded_results = {}
    window_size = 2  # Configurable: chunks before/after
    
    for task, rows in results.items():
        if not rows or not isinstance(rows, list):
            expanded_results[task] = rows
            continue
        
        # Skip expansion for aggregate results (no transcript_id/chunk_id)
        first_row = rows[0] if rows else {}
        if 'transcript_id' not in first_row or 'chunk_id' not in first_row:
            logger.info(f"Context Expansion: Skipping aggregate result for '{task[:40]}...'")
            expanded_results[task] = rows
            continue
        
        # Expand context for each chunk in parallel
        expansion_tasks = [
            expand_chunk_context(chunk, window_size) 
            for chunk in rows
        ]
        
        expanded_chunks = await asyncio.gather(*expansion_tasks)
        expanded_results[task] = expanded_chunks
        
        logger.info(f"Context Expansion: '{task[:40]}...' expanded {len(rows)} chunks")
    
    return {"results": expanded_results}

