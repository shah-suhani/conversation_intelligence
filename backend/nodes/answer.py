import json
import os
import time
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from state import State
from prompts import ANSWER_PROMPT, CONVERSATION_SUMMARY_PROMPT
from utils.helpers import format_chat_history
from llm import LLMFactory

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
llm = LLMFactory(_CONFIG_PATH).llm

ANSWER_LOG_DIR = "logs/answers"
os.makedirs(ANSWER_LOG_DIR, exist_ok=True)


def log_answer_details(
    query: str,
    answer: str,
    context_data: str,
    results: dict,
    thread_id: str = "default"
):
    sources = set()
    for task, rows in results.items():
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    t_id = row.get("transcript_id")
                    if t_id and t_id != "None":
                        sources.add(str(t_id))
    
    log_data = {
        "query": query,
        "answer": answer,
        "sources_sent_to_llm": list(sources),
        "context": context_data
    }
    
    timestamp = int(time.time())
    filename = f"{ANSWER_LOG_DIR}/answer_{thread_id}_{timestamp}.json"
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        logger.debug(f"Answer logged to: {filename}")
    except Exception as e:
        logger.warning(f"Failed to log answer: {e}")


def format_context_data(
    results: dict, 
    sql_plans: dict = None,
    fallback_tasks: list = None,
    max_rows: int = 7,
    max_chars: int = 40000
) -> str:
    """
    Format results for the answer prompt.
    
    Uses expanded_context if available, falls back to chunk_text.
    """
    fallback_tasks = fallback_tasks or []
    context_data = ""
    
    if fallback_tasks:
        task_list_str = ", ".join(fallback_tasks)
        context_data += f"""
[SYSTEM NOTE: DATA PRECISION WARNING]
The following tasks used fallback semantic search (results may be less precise):
- {task_list_str}

---
"""
    
    for task, rows in results.items():
        if len(context_data) > max_chars:
            context_data += "\n[...Context Truncated due to size limit...]"
            break
        
        is_fallback = task in fallback_tasks
        method_str = "(Fallback Search)" if is_fallback else "(Targeted Search)"
        
        context_data += f"### Subquery: {task} {method_str}\n"
        
        if not isinstance(rows, list):
            rows = [rows] if rows else []
        
        # Filter out non-dict items (error strings, None, etc.)
        valid_rows = [r for r in rows if isinstance(r, dict)]
        
        if not valid_rows:
            context_data += "No data retrieved for this task.\n\n"
            continue
        
        first_row = valid_rows[0]
        is_aggregate = ('count' in first_row or 'sum' in first_row or 'avg' in first_row) and 'chunk_text' not in first_row
        
        if is_aggregate:
            data_str = json.dumps(valid_rows, default=str, indent=2)
            context_data += f"Result: {data_str}\n\n"
        else:
            truncated_rows = valid_rows[:max_rows]
            formatted_rows = []
            for row in truncated_rows:
                formatted_row = {
                    "transcript_id": row.get("transcript_id"),
                    "chunk_id": row.get("chunk_id"),
                    "start_end_lines": row.get("start_end_lines"),
                    "domain": row.get("domain"),
                    "intent": row.get("intent"),
                    "text": row.get("expanded_context") or row.get("chunk_text", "")
                }
                if formatted_row["text"] and len(formatted_row["text"]) > 2000:
                    formatted_row["text"] = formatted_row["text"][:2000] + "..."
                formatted_rows.append(formatted_row)
            
            data_str = json.dumps(formatted_rows, default=str, indent=2)
            context_data += f"Data:\n{data_str}\n\n"
    
    return context_data


def extract_key_finding(answer: str) -> str:
    """Extract the most important finding from the answer for summarization."""
    if not answer:
        return ""
    
    lines = answer.split('\n')
    for line in lines:
        clean_line = line.strip()
        # Look for bullet points with key info
        if clean_line.startswith('•') or clean_line.startswith('-') or clean_line.startswith('*'):
            finding = clean_line.lstrip('•-* ').strip()
            if len(finding) > 20:  # Ensure it's meaningful
                return finding[:200]
        # Look for first substantive line (not a header)
        elif clean_line and not clean_line.startswith('#') and len(clean_line) > 30:
            return clean_line[:200]
    
    return answer[:150] if answer else ""


async def generate_context_summary(
    current_summary: str,
    new_query: str,
    response_summary: str,
    entities: dict
) -> str:
    """Generate an intelligent rolling summary using LLM."""
    try:
        prompt = ChatPromptTemplate.from_template(CONVERSATION_SUMMARY_PROMPT)
        chain = prompt | llm
        
        response = await chain.ainvoke({
            "current_summary": current_summary or "(No previous context)",
            "new_query": new_query,
            "response_summary": response_summary,
            "entities": json.dumps(entities) if entities else "{}"
        })
        
        summary = response.content.strip()
        
        # Ensure max length
        if len(summary) > 350:
            summary = summary[:347] + "..."
        
        return summary
    except Exception as e:
        logger.warning(f"Summary generation failed: {e}")
        # Fallback to simple concatenation
        if current_summary:
            return f"{current_summary[:150]} → {new_query[:100]}"
        return f"Query: {new_query[:150]}"


async def answer_node(state: State) -> dict:
    """
    Generate final answer based on retrieved and processed data.
    
    Input: user_query, results, chat_history, sql_plan, fallback_tasks
    Output: final_answer, updated chat_history, conversation_summary
    """
    user_query = state["user_query"]
    results = state.get("results", {})
    full_history = state.get("chat_history", [])
    sql_plans = state.get("sql_plan", {})
    fallback_tasks = state.get("fallback_tasks", [])
    
    retry_count = state.get("retry_count", 0)
    feedback = state.get("grader_feedback", "")
    
    history_text = format_chat_history(full_history, max_messages=3)
    
    context_data = format_context_data(
        results, 
        sql_plans, 
        fallback_tasks
    )
    
    # Log context for debugging
    logger.info(f"[ANSWER] Context data preview (first 2000 chars):\n{context_data[:2000]}")
    
    # Build prompt
    prompt_text = ANSWER_PROMPT.format(
        history_text=history_text,
        user_query=user_query,
        context_data=context_data
    )
    
    if feedback:
        prompt_text += f"""

!!! PREVIOUS ATTEMPT REJECTED !!!
FEEDBACK: "{feedback}"
INSTRUCTIONS: Address the feedback. Ensure citations match retrieved data.
"""
    
    prompt = ChatPromptTemplate.from_template("{input}")
    chain = prompt | llm
    
    response = await chain.ainvoke({"input": prompt_text})
    final_answer = response.content.strip()
    
    logger.info(f"Answer generated (attempt {retry_count + 1}): {len(final_answer)} chars")
    
    log_answer_details(
        query=user_query,
        answer=final_answer,
        context_data=context_data,
        results=results
    )
    
    user_msg = {"role": "user", "content": user_query}
    assistant_msg = {"role": "assistant", "content": final_answer}
    
    updated_history = list(full_history)
    if retry_count == 0:
        updated_history.append(user_msg)
        updated_history.append(assistant_msg)
    else:
        if updated_history and updated_history[-1]['role'] == 'assistant':
            updated_history[-1] = assistant_msg
        else:
            updated_history.append(assistant_msg)
    
    # Generate intelligent context summary using LLM
    current_summary = state.get("conversation_summary", "")
    standalone_query = state.get("standalone_query", user_query)
    entities = state.get("last_entities", {})
    thread_id = state.get("thread_id", "default")
    
    # Extract key finding from the answer
    key_finding = extract_key_finding(final_answer)
    
    # Generate rolling summary with LLM
    new_summary = await generate_context_summary(
        current_summary=current_summary,
        new_query=standalone_query,
        response_summary=key_finding,
        entities=entities
    )
    
    logger.debug(f"Context summary updated: {new_summary}")
    
    # Update memory
    from utils.memory import get_memory_manager
    memory_manager = get_memory_manager()
    
    # Compress short-term memory
    short_term = memory_manager.compress_short_term(
        conversation_summary=new_summary,
        last_entities=entities,
        recent_messages=updated_history,
        max_messages=3
    )
    
    # Update long-term memory patterns
    domain = None
    if sql_plans:
        for task, plan in sql_plans.items():
            if isinstance(plan, dict) and "domain" in plan.get("rationale", ""):
                domain = plan.get("domain")
                break
    
    memory_manager.update_patterns(
        thread_id=thread_id,
        query=standalone_query,
        entities=entities,
        domain=domain
    )

    return {
        "final_answer": final_answer,
        "chat_history": updated_history,
        "retry_count": retry_count + 1,
        "conversation_summary": new_summary,
        "recent_context": short_term.get("recent_context", ""),
        "active_entities": short_term.get("active_entities", {}),
        "session_topics": short_term.get("session_topics", [])
    }

