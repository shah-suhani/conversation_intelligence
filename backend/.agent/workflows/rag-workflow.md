# RAG Agent Complete Workflow

## Overview

This document describes the complete workflow of the RAG (Retrieval-Augmented Generation) agent, from receiving a user query to generating a final answer with citations.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER REQUEST                                    │
│                         POST /chat {query, thread_id}                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           1. MEMORY LOADING                                  │
│                                                                              │
│  • Load long-term memory from ./memory/{thread_id}.json                     │
│  • Get context hints (preferred domains, entities, patterns)                │
│  • Initialize input_state with query + thread_id + memory                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         2. PREPROCESSING PHASE                               │
│                                                                              │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐          │
│  │  Paraphrase  │ -> │ Context Resolution│ -> │    Breakdown     │          │
│  │    Node      │    │      Node         │    │      Node        │          │
│  └──────────────┘    └──────────────────┘    └──────────────────┘          │
│                                                                              │
│  • Paraphrase: Clean and clarify the query                                  │
│  • Context Resolution: Resolve pronouns using chat history + entities       │
│  • Breakdown: Decompose into Quantitative/Qualitative tasks with hops       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         3. HOP DETECTION                                     │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────┐           │
│  │                    hop_detector_node                          │           │
│  │  • Parse breakdown output for multi-hop structure            │           │
│  │  • Set is_multi_hop flag                                      │           │
│  │  • Initialize current_hop=1, pending_hops, hop_results       │           │
│  │  • Extract first hop's tasks for execution                    │           │
│  └──────────────────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         4. HOP EXECUTION LOOP                                │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         For each hop:                                   │ │
│  │                                                                          │ │
│  │  ┌─────────┐   ┌──────────────┐   ┌───────────────┐   ┌────────────┐  │ │
│  │  │ Planner │ → │Schema Context│ → │ SQL Generator │ → │SQL Executor│  │ │
│  │  └─────────┘   └──────────────┘   └───────────────┘   └────────────┘  │ │
│  │       │                                                      │          │ │
│  │       ▼                                                      ▼          │ │
│  │  Classify domain,                                   Execute SQL,       │ │
│  │  intent, issue_categories                          get raw results     │ │
│  │                                                                          │ │
│  │  ┌─────────┐   ┌──────────────────┐   ┌──────────────┐                 │ │
│  │  │Reranker │ → │Context Expansion │ → │  Hop Router  │                 │ │
│  │  └─────────┘   └──────────────────┘   └──────────────┘                 │ │
│  │       │                                       │                          │ │
│  │       ▼                                       ▼                          │ │
│  │  Re-rank chunks                     • Store hop result                  │ │
│  │  by relevance                       • Check for pending hops            │ │
│  │                                     • Substitute variables in next hop  │ │
│  │                                     • Retry if quant result empty       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                          ┌───────────┴───────────┐                          │
│                          │  check_hop_completion │                          │
│                          └───────────┬───────────┘                          │
│                                      │                                       │
│                    ┌─────────────────┴─────────────────┐                    │
│                    │                                   │                     │
│              [NEXT_HOP]                            [DONE]                   │
│            Loop back to                        Proceed to                   │
│              Planner                             Answer                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         5. ANSWER GENERATION                                 │
│                                                                              │
│  ┌──────────────┐                     ┌──────────────┐                      │
│  │ Answer Node  │ ─────────────────→  │ Grader Node  │                      │
│  └──────────────┘                     └──────────────┘                      │
│         │                                    │                               │
│         ▼                                    ▼                               │
│  • Format context data                • Validate citations                  │
│  • Generate structured answer         • Check answer quality                │
│  • Include citations [1], [2]         • Approve or request retry            │
│  • Update memory (short + long term)                                        │
│                                                                              │
│                    ┌───────────────────────────┐                            │
│                    │ check_answer_quality      │                            │
│                    └───────────────────────────┘                            │
│                                 │                                            │
│                   ┌─────────────┴─────────────┐                             │
│                   │                           │                              │
│               [RETRY]                     [APPROVED]                        │
│         (max 2 retries)                  Return answer                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         6. MEMORY UPDATE                                     │
│                                                                              │
│  Short-Term Memory (in state):                                              │
│  • conversation_summary: Rolling LLM-generated summary                      │
│  • recent_context: Compressed last 3 exchanges                              │
│  • active_entities: Currently relevant entities                             │
│  • session_topics: Topics discussed this session                            │
│                                                                              │
│  Long-Term Memory (./memory/{thread_id}.json):                              │
│  • topic_frequency: Count of domains/entities mentioned                     │
│  • preferred_entities: Airlines, hotels, brands user asks about             │
│  • common_patterns: Query types (comparison, quantitative, etc.)            │
│  • session_count: Number of sessions                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RESPONSE                                           │
│                      {response: final_answer}                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Node Details

### 1. Paraphrase Node (`preprocessing.py`)
- **Input**: `user_query`
- **Output**: `paraphrased_query`, `standalone_query`
- **Purpose**: Clean and clarify the raw user query

### 2. Context Resolution Node (`preprocessing.py`)
- **Input**: `paraphrased_query`, `chat_history`, `conversation_summary`, `last_entities`
- **Output**: `standalone_query`, `last_entities`
- **Purpose**: Resolve pronouns and references using conversation context

### 3. Breakdown Node (`preprocessing.py`)
- **Input**: `standalone_query`
- **Output**: `subqueries` with `is_multi_hop`, `hops[]`
- **Purpose**: Decompose complex queries into atomic tasks with dependencies

### 4. Hop Detector Node (`multi_hop.py`)
- **Input**: `subqueries`
- **Output**: `is_multi_hop`, `current_hop`, `all_hops`, `pending_hops`, `hop_results`
- **Purpose**: Initialize multi-hop execution state

### 5. Planner Node (`planner.py`)
- **Input**: `subqueries`, `standalone_query`
- **Output**: `task_dict` with domain, intent, issue_categories per task
- **Purpose**: Classify each task for SQL generation

### 6. Schema Context Node (`schema_context.py`)
- **Input**: `task_dict`
- **Output**: `schema_context` with relevant_tags, sample_data
- **Purpose**: Provide database context for accurate SQL

### 7. SQL Generator Node (`sql_generator.py`)
- **Input**: `subqueries`, `task_dict`, `schema_context`
- **Output**: `sql_plan` with SQL query per task
- **Purpose**: Generate and validate SQL with retry logic

### 8. SQL Executor Node (`sql_executor.py`)
- **Input**: `sql_plan`
- **Output**: `raw_results`, `results`, `fallback_tasks`
- **Purpose**: Execute SQL and handle failures with fallback

### 9. Reranker Node (`reranker.py`)
- **Input**: `results`, `standalone_query`
- **Output**: Re-ranked `results`
- **Purpose**: Re-rank chunks by relevance using cross-encoder

### 10. Context Expansion Node (`context_expansion.py`)
- **Input**: `results`
- **Output**: `results` with `expanded_context`
- **Purpose**: Expand chunk context with surrounding lines

### 11. Hop Router Node (`multi_hop.py`)
- **Input**: `results`, `current_hop`, `pending_hops`, `hop_results`
- **Output**: Updated hop state, next hop's `subqueries`
- **Purpose**: Orchestrate multi-hop execution with retries

### 12. Answer Node (`answer.py`)
- **Input**: `user_query`, `results`, `chat_history`
- **Output**: `final_answer`, `chat_history`, `conversation_summary`
- **Purpose**: Generate structured answer with citations

### 13. Grader Node (`grader.py`)
- **Input**: `final_answer`, `results`
- **Output**: `is_answer_valid`, `grader_feedback`
- **Purpose**: Validate citations and answer quality

---

## SQL Filtering Hierarchy

```
1. domain           → HARD (always AND)
2. issue_categories → PRIMARY (AND)
3. intent + tags    → SOFT (OR)
4. BM25 text search → SOFT (OR)
```

---

## Memory Flow

```
Request Start                    Request End
     │                                │
     ▼                                ▼
┌────────────┐                  ┌────────────┐
│Load Memory │                  │Save Memory │
│from JSON   │                  │to JSON     │
└────────────┘                  └────────────┘
     │                                │
     ▼                                ▼
long_term_memory ────────────→ update_patterns()
     │                                │
     ▼                                ▼
context_hints ─────────────→ compress_short_term()
```

---

## State Fields

| Field | Type | Purpose |
|-------|------|---------|
| `user_query` | str | Original user input |
| `thread_id` | str | Session identifier |
| `chat_history` | List[dict] | All messages in session |
| `conversation_summary` | str | Rolling LLM summary |
| `last_entities` | dict | Tracked entities |
| `subqueries` | dict | Breakdown output |
| `is_multi_hop` | bool | Multi-hop query flag |
| `current_hop` | int | Current hop (1-indexed) |
| `pending_hops` | List[dict] | Remaining hops |
| `hop_results` | dict | Results per hop |
| `sql_plan` | dict | SQL per task |
| `results` | dict | Executed results |
| `final_answer` | str | Generated answer |
| `long_term_memory` | dict | Loaded from file |
