import json
import time
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger
import uvicorn

from graph import compile_graph
from utils.db import get_db_pool, close_db_pool
from agents.schema_agent import get_schema_agent


logger.remove()
logger.add("agent.log", rotation="500 MB", retention="10 days", level="DEBUG")
logger.add(lambda msg: print(msg, end=""), level="INFO")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting RAG Agent server...")
    
    await get_db_pool()
    logger.info("Database connection pool initialized")
    
    try:
        await get_schema_agent()
        logger.info("Schema Understanding Agent initialized")
    except Exception as e:
        logger.warning(f"Schema Agent initialization failed: {e}")
    
    yield
    
    logger.info("Shutting down RAG Agent server...")
    await close_db_pool()
    logger.info("Database connection pool closed")


server = FastAPI(
    title="ObserveAI",
    description="ObserveAI",
    version="1.0.0",
    lifespan=lifespan
)

checkpointer = MemorySaver()
app = compile_graph(checkpointer=checkpointer)


class ChatRequest(BaseModel):
    """Chat request model."""
    query: str
    thread_id: str = "default_user"


class ChatResponse(BaseModel):
    """Chat response model."""
    response: str


class TranscriptRequest(BaseModel):
    """Transcript request model."""
    transcript_id: str


class TranscriptResponse(BaseModel):
    """Transcript response model."""
    transcript: dict


class BatchTranscriptRequest(BaseModel):
    """Batch transcript request model."""
    transcript_ids: list[str]


class BatchTranscriptResponse(BaseModel):
    """Batch transcript response model."""
    transcripts: list[dict]
    found_count: int
    not_found_ids: list[str]


@server.middleware("http")
async def log_requests(request: Request, call_next):
    """Log incoming requests."""
    logger.info(f"Request: {request.method} {request.url}")
    response = await call_next(request)
    return response


@server.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


@server.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    
    try:
        # Load long-term memory for this thread
        from utils.memory import get_memory_manager
        memory_manager = get_memory_manager()
        long_term_memory = memory_manager.load_long_term(request.thread_id)
        context_hints = memory_manager.get_context_hints(request.thread_id)
        
        input_state = {
            "user_query": request.query,
            "thread_id": request.thread_id,
            "long_term_memory": long_term_memory,
            "retry_count": 0,
            "grader_feedback": "",
            "is_answer_valid": False, 
        }
        result = await app.ainvoke(
            input_state, 
            config=config
        )


        logger.info(result["final_answer"])
        logger.info(result["grader_feedback"])
        
        import re
        uuid_pattern = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', re.IGNORECASE)
        
        sources_sent_to_llm = set()
        results = result.get("results", {})
        for task, rows in results.items():
            if isinstance(rows, list):
                for row in rows:
                    t_id = str(row.get("transcript_id", ""))
                    if ":" in t_id:
                        t_id = t_id.split(":")[0]
                    if t_id and t_id != "None" and uuid_pattern.match(t_id):
                        sources_sent_to_llm.add(t_id)

        output_data = {
            "answer": result["final_answer"],
            "sources_sent_to_llm": list(sources_sent_to_llm),
            "sql_results": result.get("results", {})
        }
    
        logs_dir = "logs"
        os.makedirs(logs_dir, exist_ok=True)
        
        filename = f"{logs_dir}/response_{request.thread_id}_{int(time.time())}.json"
        with open(filename, "w") as f:
            json.dump(output_data, f, indent=2, default=str)
        

        return ChatResponse(response=result["final_answer"])
    
    except Exception as e:
        logger.error(f"API Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@server.get("/schema/stats")
async def schema_stats():
    try:
        agent = await get_schema_agent()
        return {
            "domains": agent.get_all_domains(),
            "statistics": agent.statistics,
            "tag_vocabulary_summary": {
                domain: tags[:10] 
                for domain, tags in agent.tag_vocabulary.items()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@server.post("/transcript", response_model=TranscriptResponse)
async def get_transcript(request: TranscriptRequest):
    """
    Retrieve a transcript by its ID from the transcripts data file.
    
    Args:
        request: TranscriptRequest containing the transcript_id
        
    Returns:
        TranscriptResponse with the matching transcript data
        
    Raises:
        HTTPException: 404 if transcript not found, 500 for other errors
    """
    try:
        transcript_file = "./data/transcripts_data.json"
        
        # Load transcripts data
        with open(transcript_file, 'r') as f:
            transcripts = json.load(f)
        
        # Search for the transcript with matching ID
        for transcript in transcripts:
            if transcript.get("transcript_id") == request.transcript_id:
                logger.info(f"Found transcript: {request.transcript_id}")
                return TranscriptResponse(transcript=transcript)
        
        # Transcript not found
        logger.warning(f"Transcript not found: {request.transcript_id}")
        raise HTTPException(
            status_code=404, 
            detail=f"Transcript with ID '{request.transcript_id}' not found"
        )
        
    except FileNotFoundError:
        logger.error(f"Transcripts file not found: {transcript_file}")
        raise HTTPException(
            status_code=500, 
            detail="Transcripts data file not found"
        )
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in transcripts file: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Invalid transcripts data file format"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving transcript: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@server.post("/transcripts/batch", response_model=BatchTranscriptResponse)
async def get_transcripts_batch(request: BatchTranscriptRequest):
    """
    Retrieve multiple transcripts by their IDs from the transcripts data file.
    
    Args:
        request: BatchTranscriptRequest containing a list of transcript_ids
        
    Returns:
        BatchTranscriptResponse with:
        - transcripts: list of found transcript objects
        - found_count: number of transcripts found
        - not_found_ids: list of IDs that were not found
        
    Raises:
        HTTPException: 500 for file or parsing errors
    """
    try:
        transcript_file = "./data/transcripts_data.json"
        
        # Load transcripts data
        with open(transcript_file, 'r') as f:
            all_transcripts = json.load(f)
        
        # Create a lookup dictionary for faster searching
        transcript_lookup = {
            t.get("transcript_id"): t 
            for t in all_transcripts 
            if t.get("transcript_id")
        }
        
        # Find matching transcripts
        found_transcripts = []
        not_found_ids = []
        
        for requested_id in request.transcript_ids:
            if requested_id in transcript_lookup:
                found_transcripts.append(transcript_lookup[requested_id])
                logger.info(f"Found transcript: {requested_id}")
            else:
                not_found_ids.append(requested_id)
                logger.warning(f"Transcript not found: {requested_id}")
        
        logger.info(f"Batch request: {len(request.transcript_ids)} requested, {len(found_transcripts)} found")
        
        return BatchTranscriptResponse(
            transcripts=found_transcripts,
            found_count=len(found_transcripts),
            not_found_ids=not_found_ids
        )
        
    except FileNotFoundError:
        logger.error(f"Transcripts file not found: {transcript_file}")
        raise HTTPException(
            status_code=500, 
            detail="Transcripts data file not found"
        )
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in transcripts file: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Invalid transcripts data file format"
        )
    except Exception as e:
        logger.error(f"Error retrieving transcripts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def main():
    uvicorn.run(
        server,
        host="0.0.0.0",
        port=8010,
        log_level="info"
    )


if __name__ == "__main__":
    main()
