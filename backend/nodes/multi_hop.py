import re
import json
from typing import Any
from loguru import logger
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from state import State
from prompts.preprocessing import BREAKDOWN_PROMPT
from utils.helpers import extract_json_safely


llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

MAX_HOPS = 3
MAX_HOP_RETRIES = 2  # Retry failed hops


async def hop_detector_node(state: State) -> dict:
    """
    Analyze breakdown output and set multi-hop execution flags.
    
    This node runs after breakdown_node and prepares state for
    either parallel or sequential hop execution.
    
    Input: subqueries (from breakdown_node with new format)
    Output: is_multi_hop, current_hop, all_hops, pending_hops, hop_results
    """
    subqueries = state.get("subqueries", {})
    
    is_multi_hop = subqueries.get("is_multi_hop", False)
    hops = subqueries.get("hops", [])
    
    if not hops:
        logger.info("Hop Detector: Legacy format detected, treating as single hop")
        legacy_hop = {
            "hop_id": 1,
            "tasks": {
                "Quantitative_Tasks": subqueries.get("Quantitative_Tasks", []),
                "Qualitative_Tasks": subqueries.get("Qualitative_Tasks", [])
            },
            "output_var": "hop_1_result"
        }
        hops = [legacy_hop]
        is_multi_hop = False
    
    # Sort hops by hop_id
    hops = sorted(hops, key=lambda h: h.get("hop_id", 1))
    
    # Initialize hop tracking
    current_hop = 1
    pending_hops = hops[1:] if len(hops) > 1 else []
    
    first_hop = hops[0] if hops else {}
    first_hop_tasks = first_hop.get("tasks", {})
    
    logger.info(f"Hop Detector: is_multi_hop={is_multi_hop}, total_hops={len(hops)}")
    
    return {
        "is_multi_hop": is_multi_hop,
        "current_hop": current_hop,
        "all_hops": hops,
        "pending_hops": pending_hops,
        "hop_results": {},
        "hop_retry_count": 0,  # Track retries per hop
        "subqueries": {
            "Quantitative_Tasks": first_hop_tasks.get("Quantitative_Tasks", []),
            "Qualitative_Tasks": first_hop_tasks.get("Qualitative_Tasks", [])
        }
    }


def _substitute_hop_variables(text: str, hop_results: dict) -> str:
    """
    Replace {{variable_name}} placeholders with actual hop results.
    
    Args:
        text: String containing {{var}} placeholders
        hop_results: Dict mapping hop_id -> {result, output_var}
    
    Returns:
        String with placeholders replaced by actual values
    """
    var_map = {}
    for hop_id, data in hop_results.items():
        output_var = data.get("output_var", f"hop_{hop_id}_result")
        result = data.get("result", "")
        
        if isinstance(result, list):
            if len(result) == 1:
                result_str = str(result[0])
            else:
                result_str = ", ".join(str(r) for r in result[:5])
        elif isinstance(result, dict):
            if len(result) == 1:
                result_str = str(list(result.values())[0])
            else:
                result_str = str(result)
        else:
            result_str = str(result)
        
        var_map[output_var] = result_str
    
    # Replace all {{var}} patterns
    def replace_var(match):
        var_name = match.group(1)
        return var_map.get(var_name, f"{{{{UNRESOLVED:{var_name}}}}}")
    
    # Match both {{var}} and {{{{var}}}} patterns (escaped in prompts)
    result = re.sub(r'\{\{(\w+)\}\}', replace_var, text)
    result = re.sub(r'\{\{\{\{(\w+)\}\}\}\}', replace_var, result)
    
    return result


def _validate_hop_result(results: dict) -> tuple[bool, Any]:
    """
    Validate if hop returned meaningful results.
    
    Returns:
        (is_valid, extracted_value)
    """
    if not results:
        return False, None
    
    first_key = list(results.keys())[0]
    result_data = results[first_key]
    
    # Check for empty results
    if result_data is None:
        return False, None
    
    if isinstance(result_data, list):
        if len(result_data) == 0:
            return False, None
        
        first_row = result_data[0]
        if isinstance(first_row, dict):
            # Check if count is 0
            for count_key in ["count", "total", "sum"]:
                if count_key in first_row and first_row[count_key] == 0:
                    return False, None
            
            # Extract meaningful value
            for key in ["airline", "brand", "domain", "name", "count", "total", "intent"]:
                if key in first_row and first_row[key]:
                    return True, first_row[key]
            
            # Fallback to first value
            if first_row:
                return True, list(first_row.values())[0]
        else:
            return True, first_row
    
    elif isinstance(result_data, dict):
        if not result_data:
            return False, None
        return True, result_data
    
    elif isinstance(result_data, str):
        if result_data.strip() == "" or result_data == "None":
            return False, None
        return True, result_data
    
    return True, result_data


async def hop_router_node(state: State) -> dict:
    """
    After hop execution, decide: continue to next hop OR proceed to answer.
    Includes retry logic for failed quantitative hops.
    
    This node runs after sql_executor (and rerank/context_expansion) to:
    1. Validate current hop's results
    2. Retry if quantitative result is empty/invalid (up to MAX_HOP_RETRIES)
    3. Store current hop's results
    4. Prepare next hop's tasks with variable substitution
    5. Signal whether to loop back or proceed to answer
    
    Input: results (from current hop), current_hop, pending_hops, hop_results
    Output: Updated hop tracking, subqueries for next hop (if any)
    """
    current_hop = state.get("current_hop", 1)
    pending_hops = state.get("pending_hops", [])
    hop_results = state.get("hop_results", {})
    all_hops = state.get("all_hops", [])
    results = state.get("results", {})
    hop_retry_count = state.get("hop_retry_count", 0)
    
    # Get current hop config
    current_hop_config = next(
        (h for h in all_hops if h.get("hop_id") == current_hop), 
        {}
    )
    output_var = current_hop_config.get("output_var", f"hop_{current_hop}_result")
    current_tasks = current_hop_config.get("tasks", {})
    
    # Validate hop results
    is_valid, primary_result = _validate_hop_result(results)
    
    # Check if this is a quantitative hop that needs retry
    quant_tasks = current_tasks.get("Quantitative_Tasks", [])
    is_quant_hop = len(quant_tasks) > 0
    
    if not is_valid and is_quant_hop and hop_retry_count < MAX_HOP_RETRIES:
        # Retry the hop with relaxed query
        logger.warning(f"Hop Router: Hop {current_hop} returned empty/invalid results, retrying ({hop_retry_count + 1}/{MAX_HOP_RETRIES})")
        
        # Modify quant tasks to be more relaxed
        relaxed_quant = []
        for task in quant_tasks:
            # Add hint to relax filters
            relaxed_task = f"{task} (RELAX FILTERS - previous attempt returned 0 results)"
            relaxed_quant.append(relaxed_task)
        
        return {
            "hop_retry_count": hop_retry_count + 1,
            "subqueries": {
                "Quantitative_Tasks": relaxed_quant,
                "Qualitative_Tasks": current_tasks.get("Qualitative_Tasks", [])
            },
            # Clear SQL artifacts to force regeneration
            "sql_plan": {},
            "raw_results": {},
            "results": {},
            "task_dict": {}
        }
    
    # Store hop result (even if empty after retries)
    hop_results[current_hop] = {
        "result": primary_result,
        "output_var": output_var,
        "full_results": results,
        "retries": hop_retry_count
    }
    
    if not is_valid:
        logger.warning(f"Hop Router: Hop {current_hop} failed after {hop_retry_count} retries, using fallback")
        # Set a fallback result for dependent hops
        hop_results[current_hop]["result"] = "UNKNOWN"
        primary_result = "UNKNOWN"
    
    logger.info(f"Hop Router: Completed hop {current_hop}, result={primary_result}, pending={len(pending_hops)}")
    
    # Check for more hops
    if not pending_hops or current_hop >= MAX_HOPS:
        # No more hops - signal to proceed to answer
        logger.info("Hop Router: All hops complete, proceeding to answer generation")
        
        # Merge all hop results for answer node
        merged_results = {}
        for hop_id, hop_data in hop_results.items():
            full_results = hop_data.get("full_results", {})
            for task, data in full_results.items():
                merged_results[f"[Hop {hop_id}] {task}"] = data
        
        return {
            "hop_results": hop_results,
            "pending_hops": [],
            "results": merged_results,
            "current_hop": current_hop,
            "hop_retry_count": 0  # Reset for next query
        }
    
    # Prepare next hop
    next_hop = pending_hops[0]
    next_hop_id = next_hop.get("hop_id", current_hop + 1)
    next_tasks = next_hop.get("tasks", {})
    
    # Substitute variables in next hop's tasks
    substituted_quant = []
    for task in next_tasks.get("Quantitative_Tasks", []):
        substituted_quant.append(_substitute_hop_variables(task, hop_results))
    
    substituted_qual = []
    for task in next_tasks.get("Qualitative_Tasks", []):
        substituted_qual.append(_substitute_hop_variables(task, hop_results))
    
    logger.info(f"Hop Router: Preparing hop {next_hop_id} with substituted tasks")
    logger.debug(f"  Quant: {substituted_quant}")
    logger.debug(f"  Qual: {substituted_qual}")
    
    return {
        "hop_results": hop_results,
        "current_hop": next_hop_id,
        "pending_hops": pending_hops[1:],
        "hop_retry_count": 0,  # Reset retry count for new hop
        "subqueries": {
            "Quantitative_Tasks": substituted_quant,
            "Qualitative_Tasks": substituted_qual
        },
        # Clear previous hop's SQL artifacts to force regeneration
        "sql_plan": {},
        "raw_results": {},
        "results": {},
        "task_dict": {}
    }


def check_hop_completion(state: State) -> str:
    """
    Conditional edge function: decide whether to continue hopping, retry, or proceed to answer.
    
    Returns:
        "NEXT_HOP" if more hops pending OR current hop needs retry
        "DONE" if all hops complete
    """
    pending_hops = state.get("pending_hops", [])
    current_hop = state.get("current_hop", 1)
    is_multi_hop = state.get("is_multi_hop", False)
    hop_retry_count = state.get("hop_retry_count", 0)
    results = state.get("results", {})
    
    # Check if current hop is being retried
    if hop_retry_count > 0:
        logger.info(f"Hop Check: Retrying current hop (attempt {hop_retry_count + 1})")
        return "NEXT_HOP"
    
    if not is_multi_hop:
        return "DONE"
    
    if pending_hops and current_hop < MAX_HOPS:
        logger.info(f"Hop Check: More hops pending ({len(pending_hops)}), continuing")
        return "NEXT_HOP"
    
    logger.info("Hop Check: All hops complete")
    return "DONE"

