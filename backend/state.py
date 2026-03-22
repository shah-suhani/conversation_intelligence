from typing import TypedDict, List, Optional, Any


class State(TypedDict, total=False):
    """Main state object passed through the LangGraph workflow."""
    
    user_query: str
    thread_id: str                  # Thread identifier for memory lookup
    chat_history: List[dict]
    
    # Short-term memory (session)
    conversation_summary: str       # Rolling summary of conversation
    last_entities: dict             # Currently tracked entities
    recent_context: str             # Compressed last 3 exchanges
    active_entities: dict           # Entities relevant to current query
    session_topics: List[str]       # Topics discussed this session
    
    # Long-term memory (persistent)
    long_term_memory: dict          # Loaded from file at session start
    
    paraphrased_query: str
    standalone_query: str
    
    # Task breakdown (legacy format support)
    subqueries: dict 
    task_dict: dict  
    
    # Multi-hop execution
    is_multi_hop: bool              # True if query requires sequential hops
    current_hop: int                # Current hop being executed (1-indexed)
    all_hops: List[dict]            # All hops from breakdown [{hop_id, tasks, output_var, depends_on?}]
    pending_hops: List[dict]        # Remaining hops to execute
    hop_results: dict               # {hop_id: {"result": ..., "output_var": ...}}
    hop_retry_count: int            # Retry count for current hop
    
    schema_context: dict  # Task -> {relevant_tags, sample_data, cardinality, ...}
    
    sql_plan: dict      
    raw_results: dict    
    results: dict        
    fallback_tasks: List[str]
    
    final_answer: str
    
    retry_count: int
    grader_feedback: str
    is_answer_valid: bool

