"""Grader node: validates answer quality, citations, and grounding."""

import os
import re
import json
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from state import State
from prompts import GRADER_PROMPT
from utils import extract_json_safely
from llm import LLMFactory

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
llm = LLMFactory(_CONFIG_PATH).llm
CITATION_PATTERN = re.compile(r'\[\d+\]')
SOURCES_TAG_PATTERN = re.compile(r'<sources>.*?</sources>', re.DOTALL)
UUID_PATTERN = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', re.IGNORECASE)


def extract_ids_from_answer(answer: str) -> set:
    """Extract all UUIDs mentioned in the answer."""
    return set(UUID_PATTERN.findall(answer.lower()))


def extract_ids_from_results(results: dict) -> set:
    """Extract all valid transcript IDs from the retrieved results."""
    valid_ids = set()
    for task, rows in results.items():
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    t_id = row.get("transcript_id")
                    if t_id:
                        # Handle "id:chunk:lines" format
                        if ":" in str(t_id):
                            t_id = str(t_id).split(":")[0]
                        valid_ids.add(str(t_id).lower())
    return valid_ids


async def grader_node(state: State) -> dict:
    """
    Grade the generated answer for quality.
    
    Checks:
    1. Inline citations presence [1], [2], etc. (skip for pure quantitative)
    2. Sources block presence <sources>...</sources> (skip for pure quantitative)
    3. ID validation (deterministic - no LLM errors!)
    4. Hallucination + Completeness (LLM check with simplified context)
    
    Input: final_answer, results, standalone_query, subqueries
    Output: is_answer_valid, grader_feedback
    """
    answer = state["final_answer"]
    results = state.get("results", {})
    user_query = state["standalone_query"]
    subqueries = state.get("subqueries", {})
    
    # Check if this is a pure quantitative query (no qualitative tasks)
    qual_tasks = subqueries.get("Qualitative_Tasks", [])
    quant_tasks = subqueries.get("Quantitative_Tasks", [])
    is_pure_quantitative = len(qual_tasks) == 0 and len(quant_tasks) > 0
    
    # Fast-fail checks (skip for pure quantitative queries)
    if not is_pure_quantitative:
        has_citations = bool(CITATION_PATTERN.search(answer))
        has_sources_block = bool(SOURCES_TAG_PATTERN.search(answer))
        
        if not has_citations:
            logger.warning("Grader: No inline citations found")
            return {
                "is_answer_valid": False,
                "grader_feedback": "You failed to include inline citations (e.g., [1], [2]). Add citations to support your statements."
            }
        
        if not has_sources_block:
            logger.warning("Grader: No <sources> block found")
            return {
                "is_answer_valid": False,
                "grader_feedback": "You failed to append the <sources> block at the end. Add a <sources> section listing the cited sources."
            }
    else:
        logger.info("Grader: Skipping citation check for pure quantitative query")
    
    # =========================================================================
    # DETERMINISTIC ID VALIDATION (No LLM errors!)
    # =========================================================================
    answer_ids = extract_ids_from_answer(answer)
    valid_ids = extract_ids_from_results(results)
    
    if answer_ids:
        hallucinated_ids = answer_ids - valid_ids
        if hallucinated_ids:
            logger.warning(f"Grader: Found {len(hallucinated_ids)} hallucinated IDs: {hallucinated_ids}")
            return {
                "is_answer_valid": False,
                "grader_feedback": f"You cited transcript IDs that are NOT in the retrieved data: {list(hallucinated_ids)[:3]}. Only use IDs from the provided context."
            }
        else:
            logger.info(f"Grader: All {len(answer_ids)} cited IDs are valid")
    
    # For pure quantitative queries, skip LLM grading (no citations expected)
    if is_pure_quantitative:
        logger.info("Grader: Auto-approving pure quantitative answer")
        return {
            "is_answer_valid": True,
            "grader_feedback": ""
        }
    
    # =========================================================================
    # LLM-based grading (simplified - just check completeness, not ID validation)
    # =========================================================================
    
    # Create a simplified context with just the valid IDs and a sample
    simplified_context = {
        "valid_transcript_ids": list(valid_ids)[:20],
        "total_results": sum(len(v) if isinstance(v, list) else 1 for v in results.values()),
        "tasks": list(results.keys())
    }
    
    simplified_prompt = f"""
You are a Quality Assurance Auditor for a RAG system.

User Query: {user_query}

Retrieved Data Summary:
- Valid Transcript IDs: {simplified_context['valid_transcript_ids']}
- Total Results: {simplified_context['total_results']}
- Tasks: {simplified_context['tasks']}

Generated Answer:
{answer}

TASK:
Check the Generated Answer for:
1. **Completeness**: Does it answer the core question?
2. **Clarity**: Is the answer clear and well-structured?
3. **Format**: Are citations properly formatted as [1], [2] etc.?

NOTE: ID validation has already been done. Focus on answer quality, not ID checking.

OUTPUT:
Return valid JSON:
{{"is_valid": boolean, "feedback": "explanation if invalid, empty if valid"}}

No comments. No markdown. Valid JSON only.
"""
    
    try:
        prompt = ChatPromptTemplate.from_template("{input}")
        chain = prompt | llm
        
        response = await chain.ainvoke({"input": simplified_prompt})
        parsed = extract_json_safely(response.content, {"is_valid": True, "feedback": ""})
        
        is_valid = parsed.get("is_valid", True)
        feedback = parsed.get("feedback", "")
        
        if not is_valid:
            logger.warning(f"Grader: Answer rejected - {feedback}")
        else:
            logger.info("Grader: Answer approved")
        
        return {
            "is_answer_valid": is_valid,
            "grader_feedback": feedback
        }
    
    except Exception as e:
        logger.error(f"Grader error: {e}")
        # Default to valid on error
        return {
            "is_answer_valid": True,
            "grader_feedback": ""
        }

