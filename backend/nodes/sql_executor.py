"""SQL executor node: executes SQL queries with fallback to vector search."""

import asyncio
from psycopg.rows import dict_row
from loguru import logger

from state import State
from utils import get_db_pool, get_embedding_async


# Fallback SQL for pure vector search (retrieves 50 for reranking)
FALLBACK_SQL = """
SELECT 
    t.transcript_id, 
    tc.chunk_id,
    tc.start_end_lines, 
    tc.chunk_text, 
    tc.chunk_tags, 
    t.domain, 
    t.intent, 
    t.issue_categories, 
    t.timestamp 
FROM transcript_chunks tc 
JOIN transcripts t ON tc.transcript_id = t.transcript_id 
ORDER BY tc.embedding <=> %s 
LIMIT 50;
"""


async def sql_executor_node(state: State) -> dict:
    """
    Execute SQL queries for all tasks with fallback.
    
    Input: sql_plan, subqueries
    Output: raw_results (before reranking), fallback_tasks
    """
    sql_plans = state["sql_plan"]
    
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
    
    results = {}
    fallback_tasks_triggered = []
    
    async def execute_task(task: str, task_type: str) -> tuple:
        """Execute SQL for a single task with fallback."""
        if task not in sql_plans or 'sql' not in sql_plans[task]:
            return task, [], False
        
        try:
            pool = await get_db_pool()
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    sql_query = sql_plans[task]['sql']
                    logger.info(f"[EXECUTOR] Executing {task_type} SQL:\n{sql_query}")
                    
                    used_fallback = False
                    query_vector = None
                    rows = []
                    
                    try:
                        if "%s" in sql_query:
                            query_vector = await get_embedding_async(task)
                            await cur.execute(sql_query, (str(query_vector),))
                        else:
                            await cur.execute(sql_query)
                        
                        rows = await cur.fetchall()
                    except Exception as sql_err:
                        logger.warning(f"SQL execution failed for '{task[:50]}...': {sql_err}")
                        # Rollback the transaction to clear the aborted state
                        await conn.rollback()
                        rows = []
                    
                    # Fallback to pure vector search if no results
                    if not rows:
                        logger.warning(f"SQL returned 0 rows for '{task[:50]}...'. Using fallback...")
                        
                        if query_vector is None:
                            query_vector = await get_embedding_async(task)
                        
                        try:
                            await cur.execute(FALLBACK_SQL, (str(query_vector),))
                            rows = await cur.fetchall()
                            
                            if rows:
                                logger.info(f"Fallback successful: {len(rows)} rows retrieved.")
                                used_fallback = True
                            else:
                                logger.error("Fallback also returned 0 rows.")
                        except Exception as fallback_err:
                            logger.error(f"Fallback failed: {fallback_err}")
                            await conn.rollback()
                            rows = []
                    
                    return task, rows, used_fallback
        
        except Exception as e:
            logger.error(f"Error executing task '{task[:50]}...': {e}")
            return task, [], False  # Return empty list, not error string
    
    # Execute all tasks
    execution_tasks = []
    for task in quantitative_tasks:
        execution_tasks.append(execute_task(task, "QUANT"))
    for task in qualitative_tasks:
        execution_tasks.append(execute_task(task, "QUAL"))
    
    exec_results = await asyncio.gather(*execution_tasks, return_exceptions=True)
    
    for result in exec_results:
        if isinstance(result, Exception):
            logger.error(f"Task execution failed: {result}")
            continue
        
        task, rows, used_fallback = result
        
        if rows is not None:
            results[task] = rows
        
        if used_fallback:
            fallback_tasks_triggered.append(task)
    
    logger.info(f"SQL Executor: {len(results)} tasks completed, {len(fallback_tasks_triggered)} used fallback")
    
    return {
        "raw_results": results,
        "fallback_tasks": fallback_tasks_triggered
    }
