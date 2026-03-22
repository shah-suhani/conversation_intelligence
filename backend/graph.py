"""
LangGraph workflow assembly.

This is the main graph that orchestrates all nodes in the pipeline:
paraphrase → context_resolution → breakdown → hop_detector → planner → 
sql_generator → sql_executor → rerank → context_expansion → hop_router
    ↓ (if more hops)     ↓ (if done)
  [loop to planner]    answer → grader
"""

from langgraph.graph import StateGraph, END
from loguru import logger

from state import State
from nodes import (
    paraphrase_node,
    context_resolution_node,
    breakdown_node,
    planner_node,
    schema_context_node,
    sql_generator_node,
    sql_executor_node,
    rerank_node,
    context_expansion_node,
    answer_node,
    grader_node,
    # Multi-hop nodes
    hop_detector_node,
    hop_router_node,
    check_hop_completion
)


def check_answer_quality(state: State) -> str:
    """
    Conditional edge: decide whether to retry or end.
    
    Returns:
        "END" if answer is valid or max retries reached
        "RETRY" if answer needs improvement and retries available
    """
    is_valid = state.get("is_answer_valid", True)
    retry_count = state.get("retry_count", 0)
    MAX_RETRIES = 2
    
    if is_valid:
        logger.info("Grader approved answer")
        return "END"
    
    if retry_count < MAX_RETRIES:
        logger.warning(f"Grader rejected, retrying ({retry_count}/{MAX_RETRIES})")
        return "RETRY"
    
    logger.error("Max retries reached, returning best effort")
    return "END"


def build_graph() -> StateGraph:
    """
    Build the complete LangGraph workflow with multi-hop support.
    
    Graph structure:
    ┌──────────────┐
    │  paraphrase  │
    └──────┬───────┘
           │
    ┌──────▼───────┐
    │context_resolv│
    └──────┬───────┘
           │
    ┌──────▼───────┐
    │  breakdown   │
    └──────┬───────┘
           │
    ┌──────▼───────┐
    │ hop_detector │  ← NEW: Detect multi-hop queries
    └──────┬───────┘
           │
    ┌──────▼───────┐◄─────────────────┐
    │   planner    │                  │
    └──────┬───────┘                  │
           │                          │
    ┌──────▼───────┐                  │
    │schema_context│                  │
    └──────┬───────┘                  │
           │                          │
    ┌──────▼───────┐                  │
    │sql_generator │                  │
    └──────┬───────┘                  │ NEXT_HOP
           │                          │ (loop back)
    ┌──────▼───────┐                  │
    │ sql_executor │                  │
    └──────┬───────┘                  │
           │                          │
    ┌──────▼───────┐                  │
    │   rerank     │                  │
    └──────┬───────┘                  │
           │                          │
    ┌──────▼───────┐                  │
    │context_expand│                  │
    └──────┬───────┘                  │
           │                          │
    ┌──────▼───────┐                  │
    │  hop_router  │──────────────────┘
    └──────┬───────┘
           │ DONE
    ┌──────▼───────┐
    │    answer    │◄─────┐
    └──────┬───────┘      │
           │              │
    ┌──────▼───────┐      │
    │    grader    │──────┤ (RETRY if invalid)
    └──────┬───────┘      │
           │              │
           ▼              │
          END ◄───────────┘
    """
    graph = StateGraph(State)
    
    # Add all nodes
    graph.add_node("paraphrase", paraphrase_node)
    graph.add_node("context_resolution", context_resolution_node)
    graph.add_node("breakdown", breakdown_node)
    graph.add_node("hop_detector", hop_detector_node)  # NEW
    graph.add_node("planner", planner_node)
    graph.add_node("schema_context", schema_context_node)
    graph.add_node("sql_generator", sql_generator_node)
    graph.add_node("sql_executor", sql_executor_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("context_expansion", context_expansion_node)
    graph.add_node("hop_router", hop_router_node)  # NEW
    graph.add_node("answer", answer_node)
    graph.add_node("grader", grader_node)
    
    # Set entry point
    graph.set_entry_point("paraphrase")
    
    # Linear edges through preprocessing
    graph.add_edge("paraphrase", "context_resolution")
    graph.add_edge("context_resolution", "breakdown")
    graph.add_edge("breakdown", "hop_detector")  # NEW: detect multi-hop
    
    # Hop execution loop
    graph.add_edge("hop_detector", "planner")
    graph.add_edge("planner", "schema_context")
    graph.add_edge("schema_context", "sql_generator")
    graph.add_edge("sql_generator", "sql_executor")
    graph.add_edge("sql_executor", "rerank")
    graph.add_edge("rerank", "context_expansion")
    graph.add_edge("context_expansion", "hop_router")  # NEW: route after hop
    
    # Conditional edge from hop_router
    graph.add_conditional_edges(
        "hop_router",
        check_hop_completion,
        {
            "DONE": "answer",        # All hops complete, proceed to answer
            "NEXT_HOP": "planner"    # More hops, loop back to planner
        }
    )
    
    # Answer and grader
    graph.add_edge("answer", "grader")
    
    # Conditional edge from grader
    graph.add_conditional_edges(
        "grader",
        check_answer_quality,
        {
            "END": END,
            "RETRY": "answer"  # Retry goes back to answer node
        }
    )
    
    return graph


def compile_graph(checkpointer=None):
    """
    Args:
        checkpointer: LangGraph checkpoint
    Returns:
        Compiled LangGraph application
    """
    graph = build_graph()
    
    if checkpointer:
        return graph.compile(checkpointer=checkpointer)
    
    return graph.compile()

default_graph = build_graph()

