import os
from typing import Optional
from psycopg_pool import AsyncConnectionPool
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

_db_pool: Optional[AsyncConnectionPool] = None


async def get_db_pool() -> AsyncConnectionPool:
    global _db_pool
    if _db_pool is None:
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise ValueError("DATABASE_URL environment variable not set")
        _db_pool = AsyncConnectionPool(conninfo=dsn, min_size=1, max_size=10)
        await _db_pool.open()
        logger.info("Database connection pool initialized")
    return _db_pool


async def close_db_pool():
    global _db_pool
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None
        logger.info("Database connection pool closed")


async def execute_query(query: str, params: tuple = None) -> list:
    from psycopg.rows import dict_row
    pool = await get_db_pool()
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if params:
                await cur.execute(query, params)
            else:
                await cur.execute(query)
            return await cur.fetchall()


async def fetch_chunk_window(
    transcript_id: str, 
    chunk_id: int, 
    window_size: int = 2
) -> list:
    """
    Fetch a window of chunks around the given chunk.
    Uses chunk_id for ordering (integer, much simpler).
    
    Args:
        transcript_id: The transcript ID
        chunk_id: The center chunk's ID
        window_size: Number of chunks before and after to fetch
        
    Returns:
        List of chunk rows in order by chunk_id
    """
    query = """
    SELECT 
        chunk_id,
        chunk_text,
        chunk_tags
    FROM transcript_chunks
    WHERE transcript_id = %s
      AND chunk_id BETWEEN %s AND %s
    ORDER BY chunk_id
    """
    
    try:
        min_id = max(0, chunk_id - window_size)
        max_id = chunk_id + window_size
        return await execute_query(query, (transcript_id, min_id, max_id))
    except Exception as e:
        logger.warning(f"Window fetch failed: {e}")
        return []
