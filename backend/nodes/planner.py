import asyncio
import os
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from state import State
from prompts import (
    DOMAIN_PROMPT, 
    ISSUE_CATEGORIES_PROMPT, 
    VALID_TAGS,
    get_intent_prompt
)
from utils import extract_json_safely


from llm import LLMFactory
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
llm = LLMFactory(_CONFIG_PATH).llm


def determine_search_complexity(task: str, issue_categories: list, intent: list) -> bool:
    """
    Determine if the query needs text/semantic search or if structured filters are enough.
    
    Returns True if text search is needed (complex query).
    Returns False if structured filters are sufficient (simple query).
    """
    # Keywords that indicate need for text search (searching within conversations)
    text_search_keywords = [
        "example", "show", "find", "where", "said", "mentioned", 
        "about", "regarding", "complaint", "issue with", "problem with",
        "rude", "angry", "frustrated", "happy", "satisfied", "dissatisfied",
        "specific", "particular", "exactly", "saying", "discussing"
    ]
    
    task_lower = task.lower()
    
    # If we have issue_categories, check if it's a simple count/aggregation
    if issue_categories:
        # Simple count patterns - no text search needed
        simple_patterns = ["count", "how many", "total number", "number of"]
        is_simple_count = any(p in task_lower for p in simple_patterns)
        
        # Check for text search indicators
        needs_text = any(kw in task_lower for kw in text_search_keywords)
        
        # If it's a simple count with issue_categories, don't use text search
        if is_simple_count and not needs_text:
            return False
    
    # If no structured filters, we need text search
    if not issue_categories and not intent:
        return True
    
    # If asking for examples/qualitative data, need text search
    if any(kw in task_lower for kw in text_search_keywords):
        return True
    
    # Default: if we have good structured filters, don't need text search
    return False


async def planner_node(state: State) -> dict:
    """
    Classify tasks by domain, intent, and issue categories.
    Also determines if text/semantic search is needed.
    
    Input: subqueries
    Output: task_dict (mapping of task -> metadata including requires_text_search)
    """
    all_tasks = (
        state["subqueries"].get("Quantitative_Tasks", []) +
        state["subqueries"].get("Qualitative_Tasks", [])
    )
    
    async def process_task(task: str) -> tuple:
        """Process a single task to extract domain, intent, issue_categories."""
        
        # Step 1: Get domain
        domain_prompt = ChatPromptTemplate.from_template(DOMAIN_PROMPT)
        domain_chain = domain_prompt | llm
        domain_response = await domain_chain.ainvoke({"task": task})
        domain_data = extract_json_safely(domain_response.content)
        domain = domain_data.get("domain", ["General"])
        
        # Normalize domain to list
        domain_list = domain if isinstance(domain, list) else [domain]
        domain_list = [d for d in domain_list if d is not None]
        
        # If General, expand to all domains
        if "General" in domain_list:
            domain_list = ['Hotel', 'Flight', 'Retail', 'Banking', 'Telecom', 'Insurance']
        
        # Step 2: Get intent for each valid domain (parallel)
        valid_domains = [d for d in domain_list if d in VALID_TAGS.get("domain", [])]
        
        intent_tasks = []
        for d in valid_domains:
            intent_prompt_template = get_intent_prompt(d)
            intent_prompt = ChatPromptTemplate.from_template(intent_prompt_template)
            intent_chain = intent_prompt | llm
            intent_tasks.append(intent_chain.ainvoke({"task": task}))
        
        # Step 3: Get issue categories
        issue_prompt = ChatPromptTemplate.from_template(ISSUE_CATEGORIES_PROMPT)
        issue_chain = issue_prompt | llm
        issue_task = issue_chain.ainvoke({"domain": ", ".join(domain_list), "task": task})
        
        # Gather all results
        results = await asyncio.gather(*intent_tasks, issue_task, return_exceptions=True)
        
        # Parse intents
        all_intents = []
        for i, r in enumerate(results[:-1]):  # All except last (issue)
            if isinstance(r, Exception):
                continue
            try:
                parsed = extract_json_safely(r.content)
                intents = parsed.get("intent", [])
                if isinstance(intents, str):
                    intents = [intents]
                all_intents.extend([i for i in intents if i != "General"])
            except Exception:
                continue
        
        # Parse issue categories
        issue_categories = []
        issue_result = results[-1]
        if not isinstance(issue_result, Exception):
            try:
                issues = extract_json_safely(issue_result.content).get("issue_categories", [])
                if isinstance(issues, str):
                    issues = [issues]
                if "General" not in issues and issues:
                    issue_categories = list(set(issues))
            except Exception:
                pass
        
        # Determine if text search is needed
        requires_text_search = determine_search_complexity(task, issue_categories, all_intents)
        
        task_data = {"domain": domain_list[0] if len(domain_list) == 1 else domain_list}
        if all_intents:
            task_data["intent"] = list(set(all_intents))
        if issue_categories:
            task_data["issue_categories"] = issue_categories
        
        # Add the complexity flag
        task_data["requires_text_search"] = requires_text_search
        
        logger.info(f"Planner: '{task[:50]}...' → {task_data}")
        return task, task_data
    
    # Process all tasks in parallel
    results = await asyncio.gather(*[process_task(t) for t in all_tasks])
    
    return {"task_dict": dict(results)}

