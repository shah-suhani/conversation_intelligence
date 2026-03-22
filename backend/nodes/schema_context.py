
import asyncio
import re
from typing import Dict, List, Any, Optional
from loguru import logger

from state import State
from utils.db import get_db_pool


def extract_keywords(task: str) -> List[str]:
    """
    Extract meaningful keywords from a task description.
    Removes common stop words and returns substantive terms.
    """
    stop_words = {
        'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
        'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
        'from', 'as', 'into', 'through', 'during', 'before', 'after',
        'above', 'below', 'between', 'under', 'again', 'further', 'then',
        'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any',
        'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
        'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very',
        'just', 'and', 'but', 'if', 'or', 'because', 'until', 'while',
        'about', 'against', 'what', 'which', 'who', 'whom', 'this', 'that',
        'these', 'those', 'am', 'it', 'its', 'find', 'show', 'get', 'list',
        'give', 'tell', 'me', 'many', 'much', 'count', 'number', 'total'
    }
    
    # Clean and tokenize, Filter stop words and return unique keywords
    words = re.findall(r'\b[a-zA-Z]{3,}\b', task.lower())
    keywords = [w for w in words if w not in stop_words]
    
    # Deduplicate while preserving order
    seen = set()
    unique_keywords = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique_keywords.append(kw)
    
    return unique_keywords[:10]


# ---------------------------------------------------------------------------
# Context Gathering Functions
# ---------------------------------------------------------------------------

async def find_relevant_tags(
    pool, 
    keywords: List[str], 
    domain: Optional[str] = None,
    limit: int = 15
) -> List[str]:
    """
    Find chunk_tags that match the task keywords.
    Uses text matching on tag names.
    """
    if not keywords:
        return []
    
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Build pattern for matching tags
                patterns = [f"%{kw}%" for kw in keywords]
                
                # Query to find matching tags with frequency
                if domain and domain != "General":
                    query = """
                    SELECT tag, COUNT(*) as freq
                    FROM (
                        SELECT unnest(tc.chunk_tags) as tag
                        FROM transcript_chunks tc
                        JOIN transcripts t ON tc.transcript_id = t.transcript_id
                        WHERE t.domain = %s
                    ) subq
                    WHERE """ + " OR ".join(["tag ILIKE %s" for _ in patterns]) + """
                    GROUP BY tag
                    ORDER BY freq DESC
                    LIMIT %s
                    """
                    params = [domain] + patterns + [limit]
                else:
                    query = """
                    SELECT tag, COUNT(*) as freq
                    FROM (
                        SELECT unnest(chunk_tags) as tag
                        FROM transcript_chunks
                    ) subq
                    WHERE """ + " OR ".join(["tag ILIKE %s" for _ in patterns]) + """
                    GROUP BY tag
                    ORDER BY freq DESC
                    LIMIT %s
                    """
                    params = patterns + [limit]
                
                await cur.execute(query, params)
                rows = await cur.fetchall()
                
                return [row[0] for row in rows]
                
    except Exception as e:
        logger.warning(f"find_relevant_tags error: {e}")
        return []


async def get_sample_data(
    pool,
    domain: Optional[str] = None,
    intent: Optional[str] = None,
    keywords: List[str] = None,
    limit: int = 2
) -> List[Dict[str, Any]]:
    """
    Get sample rows matching the filters to show data format.
    """
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                conditions = []
                params = []
                
                if domain and domain != "General":
                    conditions.append("t.domain = %s")
                    params.append(domain)
                
                if intent:
                    conditions.append("t.intent = %s")
                    params.append(intent)
                
                where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
                
                query = f"""
                SELECT 
                    tc.chunk_text,
                    tc.chunk_tags,
                    t.domain,
                    t.intent,
                    t.issue_categories
                FROM transcript_chunks tc
                JOIN transcripts t ON tc.transcript_id = t.transcript_id
                {where_clause}
                ORDER BY RANDOM()
                LIMIT %s
                """
                params.append(limit)
                
                await cur.execute(query, params)
                rows = await cur.fetchall()
                
                samples = []
                for row in rows:
                    # Truncate chunk_text for context
                    chunk_text = row[0][:500] + "..." if len(row[0]) > 500 else row[0]
                    samples.append({
                        "chunk_text": chunk_text,
                        "chunk_tags": row[1][:5] if row[1] else [],  # First 5 tags
                        "domain": row[2],
                        "intent": row[3],
                        "issue_categories": row[4][:3] if row[4] else []
                    })
                
                return samples
                
    except Exception as e:
        logger.warning(f"get_sample_data error: {e}")
        return []


async def get_cardinality(
    pool,
    domain: Optional[str] = None,
    intent: Optional[str] = None,
    tags: List[str] = None
) -> Dict[str, int]:
    """
    Get row counts for different filter combinations.
    Helps understand filter effectiveness.
    """
    cardinality = {}
    
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Total count for domain
                if domain and domain != "General":
                    await cur.execute(
                        "SELECT COUNT(DISTINCT transcript_id) FROM transcripts WHERE domain = %s",
                        (domain,)
                    )
                    result = await cur.fetchone()
                    cardinality["domain_only"] = result[0] if result else 0
                    
                    # With intent
                    if intent:
                        await cur.execute(
                            "SELECT COUNT(DISTINCT transcript_id) FROM transcripts WHERE domain = %s AND intent = %s",
                            (domain, intent)
                        )
                        result = await cur.fetchone()
                        cardinality["domain_and_intent"] = result[0] if result else 0
                
                # With tags (if provided)
                if tags and len(tags) > 0:
                    tag_condition = " OR ".join(["%s = ANY(tc.chunk_tags)" for _ in tags])
                    query = f"""
                    SELECT COUNT(DISTINCT t.transcript_id)
                    FROM transcript_chunks tc
                    JOIN transcripts t ON tc.transcript_id = t.transcript_id
                    WHERE ({tag_condition})
                    """
                    params = list(tags)
                    
                    if domain and domain != "General":
                        query += " AND t.domain = %s"
                        params.append(domain)
                    
                    await cur.execute(query, params)
                    result = await cur.fetchone()
                    cardinality["with_tags"] = result[0] if result else 0
                
                return cardinality
                
    except Exception as e:
        logger.warning(f"get_cardinality error: {e}")
        return {}


async def search_entity_values(
    pool,
    keywords: List[str],
    domain: Optional[str] = None
) -> Dict[str, str]:
    """
    Check if mentioned entities exist in the data.
    Returns matching values found.
    """
    if not keywords:
        return {}
    
    entity_matches = {}
    
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Check for entity keywords in chunk_text using BM25
                for keyword in keywords[:5]:  # Check top 5 keywords
                    query = """
                    SELECT COUNT(DISTINCT t.transcript_id)
                    FROM transcript_chunks tc
                    JOIN transcripts t ON tc.transcript_id = t.transcript_id
                    WHERE tc.text_search_vector @@ websearch_to_tsquery('english', %s)
                    """
                    params = [keyword]
                    
                    if domain and domain != "General":
                        query += " AND t.domain = %s"
                        params.append(domain)
                    
                    await cur.execute(query, params)
                    result = await cur.fetchone()
                    count = result[0] if result else 0
                    
                    if count > 0:
                        entity_matches[keyword] = f"Found in {count} transcripts"
                
                return entity_matches
                
    except Exception as e:
        logger.warning(f"search_entity_values error: {e}")
        return {}


async def get_top_tags_for_domain(
    pool,
    domain: str,
    limit: int = 10
) -> List[str]:
    """
    Get the most frequent chunk_tags for a specific domain.
    """
    if not domain or domain == "General":
        return []
    
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                query = """
                SELECT unnest(tc.chunk_tags) as tag, COUNT(*) as freq
                FROM transcript_chunks tc
                JOIN transcripts t ON tc.transcript_id = t.transcript_id
                WHERE t.domain = %s
                GROUP BY tag
                ORDER BY freq DESC
                LIMIT %s
                """
                await cur.execute(query, (domain, limit))
                rows = await cur.fetchall()
                
                return [row[0] for row in rows]
                
    except Exception as e:
        logger.warning(f"get_top_tags_for_domain error: {e}")
        return []


# ---------------------------------------------------------------------------
# Main Node Function
# ---------------------------------------------------------------------------

async def gather_context_for_task(
    pool,
    task: str,
    metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Gather all schema context for a single task.
    """
    # Extract domain from metadata
    domain = metadata.get("domain")
    if isinstance(domain, list):
        domain = domain[0] if domain else None
    
    intent = metadata.get("intent")
    if isinstance(intent, list):
        intent = intent[0] if intent else None
    
    # Extract keywords from task
    keywords = extract_keywords(task)
    
    # Gather context in parallel
    relevant_tags, sample_data, cardinality, entity_matches, top_domain_tags = await asyncio.gather(
        find_relevant_tags(pool, keywords, domain),
        get_sample_data(pool, domain, intent, keywords),
        get_cardinality(pool, domain, intent, []),
        search_entity_values(pool, keywords, domain),
        get_top_tags_for_domain(pool, domain),
        return_exceptions=True
    )
    
    # Handle any exceptions
    if isinstance(relevant_tags, Exception):
        logger.warning(f"relevant_tags failed: {relevant_tags}")
        relevant_tags = []
    if isinstance(sample_data, Exception):
        logger.warning(f"sample_data failed: {sample_data}")
        sample_data = []
    if isinstance(cardinality, Exception):
        logger.warning(f"cardinality failed: {cardinality}")
        cardinality = {}
    if isinstance(entity_matches, Exception):
        logger.warning(f"entity_matches failed: {entity_matches}")
        entity_matches = {}
    if isinstance(top_domain_tags, Exception):
        logger.warning(f"top_domain_tags failed: {top_domain_tags}")
        top_domain_tags = []
    
    # Combine relevant_tags with top_domain_tags (deduplicated)
    all_tags = list(dict.fromkeys(relevant_tags + top_domain_tags))
    
    # Get cardinality with the found tags
    if all_tags:
        tag_cardinality = await get_cardinality(pool, domain, intent, all_tags[:5])
        cardinality.update(tag_cardinality)
    
    # Build suggested filters based on what we found
    suggested_filters = []
    if domain and domain != "General":
        suggested_filters.append(f"t.domain = '{domain}'")
    if all_tags:
        tag_filter = " OR ".join([f"'{t}' = ANY(tc.chunk_tags)" for t in all_tags[:3]])
        suggested_filters.append(f"({tag_filter})")
    
    context = {
        "keywords_extracted": keywords,
        "relevant_tags": all_tags[:10],
        "sample_data": sample_data,
        "cardinality": cardinality,
        "entity_matches": entity_matches,
        "suggested_filters": suggested_filters
    }
    
    return context


async def schema_context_node(state: State) -> dict:
    """
    Gather database context for each task to improve SQL generation.
    
    This node queries the actual database to provide:
    - Relevant chunk_tags matching task keywords
    - Sample data rows for format understanding
    - Cardinality counts for filter effectiveness
    - Entity value matching verification
    
    Input: task_dict (from planner)
    Output: schema_context (dict mapping task -> context)
    """
    task_dict = state.get("task_dict", {})
    
    if not task_dict:
        logger.warning("Schema Context: No tasks to process")
        return {"schema_context": {}}
    
    logger.info(f"Schema Context: Processing {len(task_dict)} tasks")
    
    pool = await get_db_pool()
    schema_context = {}
    
    # Process each task
    context_tasks = []
    task_list = list(task_dict.items())
    
    for task, metadata in task_list:
        context_tasks.append(gather_context_for_task(pool, task, metadata))
    
    # Gather all contexts in parallel
    results = await asyncio.gather(*context_tasks, return_exceptions=True)
    
    for i, (task, _) in enumerate(task_list):
        result = results[i]
        if isinstance(result, Exception):
            logger.error(f"Schema Context failed for '{task[:50]}...': {result}")
            schema_context[task] = {}
        else:
            schema_context[task] = result
            logger.info(
                f"Schema Context: '{task[:40]}...' → "
                f"{len(result.get('relevant_tags', []))} tags, "
                f"{len(result.get('sample_data', []))} samples"
            )
    
    return {"schema_context": schema_context}
