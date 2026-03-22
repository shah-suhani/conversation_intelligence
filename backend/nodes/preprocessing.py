import json
import os
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from state import State
from prompts import PARAPHRASE_PROMPT, HISTORY_PROMPT, BREAKDOWN_PROMPT, ENTITY_EXTRACTION_PROMPT
from utils import extract_json_safely
from llm import LLMFactory

# Use absolute path to config.yaml relative to this file's location
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
llm = LLMFactory(_CONFIG_PATH).llm


async def paraphrase_node(state: State) -> dict:
    """
    Paraphrase the user query for clarity.
    
    Input: user_query
    Output: paraphrased_query, standalone_query
    """
    query = state["user_query"]
    
    prompt = ChatPromptTemplate.from_template(PARAPHRASE_PROMPT)
    chain = prompt | llm
    
    response = await chain.ainvoke({"query": query})
    paraphrased = response.content.strip()
    
    logger.info(f"Paraphrase: '{query}' → '{paraphrased}'")
    
    return {
        "paraphrased_query": paraphrased,
        "standalone_query": paraphrased
    }


async def extract_entities(query: str, previous_entities: dict) -> dict:
    """Extract key entities from the query for context memory."""
    prompt = ChatPromptTemplate.from_template(ENTITY_EXTRACTION_PROMPT)
    chain = prompt | llm
    
    try:
        response = await chain.ainvoke({
            "query": query,
            "previous_entities": json.dumps(previous_entities) if previous_entities else "{}"
        })
        entities = extract_json_safely(response.content.strip(), {})
        
        # Merge with previous entities (new values override)
        merged = {**previous_entities} if previous_entities else {}
        for key, value in entities.items():
            if value and value != "null":
                merged[key] = value
        
        return merged
    except Exception as e:
        logger.warning(f"Entity extraction failed: {e}")
        return previous_entities or {}


async def context_resolution_node(state: State) -> dict:
    """
    Resolve context from chat history to make query standalone.
    Uses conversation summary and entity tracking for better multi-turn context.
    
    Input: paraphrased_query, chat_history, conversation_summary, last_entities
    Output: standalone_query, last_entities (updated)
    """
    user_query = state["paraphrased_query"]
    chat_history = state.get("chat_history", [])
    conversation_summary = state.get("conversation_summary", "No previous context.")
    last_entities = state.get("last_entities", {})
    
    # Extract entities from current query (updates memory)
    updated_entities = await extract_entities(user_query, last_entities)
    
    # If no history, query is already standalone
    if not chat_history:
        return {
            "standalone_query": user_query,
            "last_entities": updated_entities
        }
    
    # Format recent history (last 6 messages)
    history_text = "\n".join([
        f"{msg['role'].upper()}: {msg['content'][:500]}..." 
        if len(msg.get('content', '')) > 500 
        else f"{msg['role'].upper()}: {msg['content']}" 
        for msg in chat_history[-6:]
    ])
    
    prompt = ChatPromptTemplate.from_template(HISTORY_PROMPT)
    chain = prompt | llm
    
    response = await chain.ainvoke({
        "conversation_summary": conversation_summary,
        "last_entities": json.dumps(last_entities) if last_entities else "None",
        "history_text": history_text,
        "user_query": user_query
    })
    
    resolved_query = response.content.strip().strip('"').strip("'")
    logger.info(f"Context Resolution: '{user_query}' → '{resolved_query}'")
    logger.debug(f"Entities tracked: {updated_entities}")
    
    return {
        "standalone_query": resolved_query,
        "last_entities": updated_entities
    }


async def breakdown_node(state: State) -> dict:
    """
    Break down complex query into atomic subqueries with multi-hop detection.
    
    Input: standalone_query
    Output: subqueries (dict with is_multi_hop, hops structure)
    """
    query = state["standalone_query"]
    
    prompt = ChatPromptTemplate.from_template(BREAKDOWN_PROMPT)
    chain = prompt | llm
    
    response = await chain.ainvoke({"query": query})
    
    # New format: {is_multi_hop, hops: [{hop_id, tasks: {Quant, Qual}, output_var}]}
    default_structure = {
        "is_multi_hop": False,
        "hops": [{
            "hop_id": 1,
            "tasks": {"Quantitative_Tasks": [], "Qualitative_Tasks": []},
            "output_var": "hop_1_result"
        }]
    }
    
    data = extract_json_safely(response.content.strip(), default_structure)
    
    # Count total tasks across all hops
    total_quant = 0
    total_qual = 0
    for hop in data.get("hops", []):
        tasks = hop.get("tasks", {})
        total_quant += len(tasks.get("Quantitative_Tasks", []))
        total_qual += len(tasks.get("Qualitative_Tasks", []))
    
    hop_count = len(data.get("hops", []))
    is_multi = data.get("is_multi_hop", False)
    
    logger.info(f"Breakdown: {hop_count} hop(s), {total_quant} quant, {total_qual} qual tasks, multi_hop={is_multi}")
    
    return {"subqueries": data}

