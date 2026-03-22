import asyncio
import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from psycopg.rows import dict_row
from loguru import logger

from state import State
from prompts.sql import build_sql_prompt
from utils import extract_json_safely, get_db_pool, get_embedding_async
from llm import LLMFactory

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
llm = LLMFactory(_CONFIG_PATH).llm

async def probe_sql(cursor, sql_query: str, vector_str: str = None) -> dict:
    """
    Execute SQL and return status dict.
    
    Returns: {'success': bool, 'rows': int, 'error': str, 'type': str}
    """
    try:
        if "%s" in sql_query:
            await cursor.execute(sql_query, (vector_str,))
        else:
            await cursor.execute(sql_query)
        
        rows = await cursor.fetchall()
        row_count = len(rows)
        
        if row_count == 0:
            return {'success': False, 'error': 'Query returned 0 rows', 'type': 'EMPTY_RESULT'}
        
        return {'success': True, 'rows': row_count, 'error': None, 'type': 'SUCCESS'}
        
    except Exception as e:
        error_msg = str(e)
        if "allowed as placeholders" in error_msg or "format parameters" in error_msg:
            return {
                'success': False, 
                'error': "PYTHON FORMATTING ERROR: Replace `ILIKE '%term%'` with BM25 syntax.", 
                'type': 'SYNTAX_ERROR'
            }
        error_clean = error_msg.split('\n')[0]
        return {'success': False, 'error': error_clean, 'type': 'SYNTAX_ERROR'}


async def sql_generator_node(state: State) -> dict:
    """
    Generate SQL queries for all tasks with retry logic.
    
    Input: subqueries, task_dict, schema_context
    Output: sql_plan (dict of task -> {sql, rationale})
    """
    # Extract tasks from hops structure (new format from breakdown_node)
    subqueries = state["subqueries"]
    quantitative_tasks = []
    qualitative_tasks = []
    
    # Handle both old flat format and new hops format
    if "hops" in subqueries:
        for hop in subqueries.get("hops", []):
            tasks = hop.get("tasks", {})
            quantitative_tasks.extend(tasks.get("Quantitative_Tasks", []))
            qualitative_tasks.extend(tasks.get("Qualitative_Tasks", []))
    else:
        # Fallback to old flat format
        quantitative_tasks = subqueries.get("Quantitative_Tasks", [])
        qualitative_tasks = subqueries.get("Qualitative_Tasks", [])
    schema_context = state.get("schema_context", {})
    
    sql_plan = {}
    
    async def process_task(task: str, task_type: str) -> tuple:
        """Generate and validate SQL for a single task."""
        max_retries = 2
        feedback_ctx = None
        
        # Get embedding for qualitative tasks
        vector_str = None
        if task_type == "QUAL":
            query_vector = await get_embedding_async(task)
            vector_str = str(query_vector)
        
        current_sql = ""
        current_rationale = ""
        
        pool = await get_db_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                
                for attempt in range(max_retries + 1):
                    task_metadata = state["task_dict"].get(task, {})
                    task_schema_ctx = schema_context.get(task, {})
                    prompt_text = build_sql_prompt(
                        task, 
                        task_metadata, 
                        task_type=task_type, 
                        feedback_context=feedback_ctx,
                        schema_context=task_schema_ctx
                    )
                    
                    try:
                        prompt = ChatPromptTemplate.from_template("{input}")
                        chain = prompt | llm
                        response = await chain.ainvoke({"input": prompt_text})
                        
                        parsed = extract_json_safely(response.content, {})
                        current_sql = parsed.get("sql_query", "")
                        current_rationale = parsed.get("rationale", "No rationale provided")
                        
                        logger.debug(f"[{task_type}] Task: {task[:50]}...")
                        logger.info(f"[{task_type}] Generated SQL:\n{current_sql}")
                        
                        if not current_sql:
                            raise ValueError("LLM returned empty SQL")
                    
                    except Exception as llm_e:
                        logger.error(f"LLM Generation failed: {llm_e}")
                        return task, {"sql": "", "rationale": "LLM Generation Error"}
                    
                    # Probe the SQL
                    probe = await probe_sql(cur, current_sql, vector_str)
                    
                    if probe['success']:
                        logger.info(f"SQL validated ({probe['rows']} rows) on attempt {attempt+1}")
                        return task, {"sql": current_sql, "rationale": current_rationale}
                    
                    logger.warning(f"Attempt {attempt+1} Failed: {probe['error']}")
                    
                    feedback_ctx = {
                        'error': probe['error'],
                        'sql': current_sql,
                        'type': probe['type']
                    }
                    
                    if attempt == max_retries:
                        logger.error(f"Max retries reached for: {task[:50]}...")
        
        return task, {"sql": current_sql, "rationale": current_rationale}
    
    # Process all tasks
    tasks_to_process = []
    for t in quantitative_tasks:
        tasks_to_process.append(process_task(t, "QUANT"))
    for t in qualitative_tasks:
        tasks_to_process.append(process_task(t, "QUAL"))
    
    results = await asyncio.gather(*tasks_to_process)
    
    for task, data in results:
        sql_plan[task] = data
    
    return {"sql_plan": sql_plan}
