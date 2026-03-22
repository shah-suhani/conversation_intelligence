# Schema Context Node - Detailed Documentation

## Purpose

The Schema Context Node queries the **actual database** before SQL generation to provide the LLM with real-world context about the data. This dramatically improves SQL accuracy by showing:
- What tags actually exist in the database
- How data is formatted
- Row counts for different filters
- Whether mentioned entities exist

---

## Architecture

```
                    ┌───────────────────────────────────────────────────────┐
                    │                  PLANNER OUTPUT                        │
                    │   task_dict: {task → {domain, intent, categories}}    │
                    └───────────────────────────────────────────────────────┘
                                            │
                                            ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                          SCHEMA CONTEXT NODE                                   │
│                                                                                │
│  For each task, gather in parallel:                                           │
│                                                                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐               │
│  │ extract_keywords│  │find_relevant_tags│  │ get_sample_data │               │
│  │ from task text  │  │matching keywords │  │ for format ref  │               │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘               │
│           │                    │                    │                         │
│           ▼                    ▼                    ▼                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐               │
│  │ get_cardinality │  │search_entity_   │  │get_top_tags_for │               │
│  │ (filter counts) │  │values (BM25)    │  │domain (top 10)  │               │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘               │
│           │                    │                    │                         │
│           └────────────────────┼────────────────────┘                         │
│                                ▼                                              │
│                    ┌───────────────────────┐                                  │
│                    │ Combine & Deduplicate │                                  │
│                    └───────────────────────┘                                  │
└───────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
                    ┌───────────────────────────────────────────────────────┐
                    │                  schema_context                        │
                    │   {task → {relevant_tags, sample_data, cardinality}}  │
                    └───────────────────────────────────────────────────────┘
```

---

## Input / Output

| Direction | Field | Type | Description |
|-----------|-------|------|-------------|
| **Input** | `task_dict` | `Dict[str, Dict]` | Task → metadata mapping from Planner |
| **Output** | `schema_context` | `Dict[str, Dict]` | Task → context mapping for SQL Generator |

---

## Context Components

### 1. Keywords Extraction

**Function**: `extract_keywords(task: str) → List[str]`

Extracts meaningful keywords from task description after removing stop words.

```python
# Example
task = "Find complaints about Delta flight delays in November"
keywords = ["complaints", "delta", "flight", "delays", "november"]
```

---

### 2. Relevant Tags

**Function**: `find_relevant_tags(pool, keywords, domain, limit=15) → List[str]`

Finds chunk_tags that match task keywords using ILIKE pattern matching.

```sql
SELECT tag, COUNT(*) as freq
FROM (
    SELECT unnest(tc.chunk_tags) as tag
    FROM transcript_chunks tc
    JOIN transcripts t ON tc.transcript_id = t.transcript_id
    WHERE t.domain = 'Flight'
) subq
WHERE tag ILIKE '%delay%' OR tag ILIKE '%complaint%'
GROUP BY tag
ORDER BY freq DESC
LIMIT 15
```

**Output Example**:
```python
["CUSTOMER_EXPRESSES_FRUSTRATION", "DELAY_MENTIONED", "AGENT_APOLOGIZES"]
```

---

### 3. Sample Data

**Function**: `get_sample_data(pool, domain, intent, keywords, limit=2) → List[Dict]`

Gets random sample rows matching filters to show data format.

**Output Example**:
```python
[
    {
        "chunk_text": "Customer: My flight was delayed for 3 hours...",
        "chunk_tags": ["CUSTOMER_STATES_ISSUE", "DELAY_MENTIONED"],
        "domain": "Flight",
        "intent": "Delay Management",
        "issue_categories": ["SERVICE_COMPLAINT"]
    }
]
```

---

### 4. Cardinality

**Function**: `get_cardinality(pool, domain, intent, tags) → Dict[str, int]`

Gets row counts for different filter combinations.

**Output Example**:
```python
{
    "domain_only": 1500,
    "domain_and_intent": 320,
    "with_tags": 145
}
```

**Purpose**: Helps LLM understand filter effectiveness. If `with_tags` is 0, tags might be too restrictive.

---

### 5. Entity Matches

**Function**: `search_entity_values(pool, keywords, domain) → Dict[str, str]`

Uses BM25 text search to verify if mentioned entities exist in data.

**Output Example**:
```python
{
    "delta": "Found in 234 transcripts",
    "november": "Found in 89 transcripts"
}
```

---

### 6. Top Domain Tags

**Function**: `get_top_tags_for_domain(pool, domain, limit=10) → List[str]`

Gets most frequent chunk_tags for a specific domain.

**Output Example** (for Flight domain):
```python
[
    "AGENT_EXPRESSES_EMPATHY",
    "CUSTOMER_STATES_ISSUE",
    "DELAY_MENTIONED",
    "REFUND_DISCUSSED",
    ...
]
```

---

## Final Context Structure

```python
schema_context = {
    "Find complaints about Delta delays": {
        "keywords_extracted": ["complaints", "delta", "delays"],
        "relevant_tags": [
            "CUSTOMER_EXPRESSES_FRUSTRATION",
            "DELAY_MENTIONED",
            "AGENT_APOLOGIZES",
            ...
        ],
        "sample_data": [
            {
                "chunk_text": "Customer: My flight was delayed...",
                "chunk_tags": [...],
                "domain": "Flight",
                "intent": "Delay Management"
            }
        ],
        "cardinality": {
            "domain_only": 1500,
            "domain_and_intent": 320,
            "with_tags": 145
        },
        "entity_matches": {
            "delta": "Found in 234 transcripts"
        },
        "suggested_filters": [
            "t.domain = 'Flight'",
            "('DELAY_MENTIONED' = ANY(tc.chunk_tags) OR ...)"
        ]
    }
}
```

---

## How SQL Generator Uses This

The `build_sql_prompt()` function injects this context:

```
DATABASE CONTEXT FOR THIS TASK:
- RELEVANT CHUNK_TAGS (use in OR filters): ['CUSTOMER_EXPRESSES_FRUSTRATION', 'DELAY_MENTIONED', ...]
- CARDINALITY: domain_only: 1500 rows, with_tags: 145 rows
- ENTITIES FOUND IN DATA: 'delta' (Found in 234 transcripts)
- SAMPLE DATA FORMAT:
  Tags: ['CUSTOMER_STATES_ISSUE', 'DELAY_MENTIONED']
  Text: "Customer: My flight was delayed..."
- SUGGESTED FILTERS: t.domain = 'Flight'; ('DELAY_MENTIONED' = ANY(tc.chunk_tags) OR ...)

USE THIS CONTEXT: Incorporate the relevant_tags in your WHERE clause using OR logic.
```

---

## Performance

- All 5 context queries run **in parallel** using `asyncio.gather()`
- Typical execution: 50-200ms per task
- Results are cached in `state["schema_context"]` for the request lifecycle

---

## Error Handling

Each function wraps database errors and returns empty defaults:
- `find_relevant_tags` → `[]`
- `get_sample_data` → `[]`
- `get_cardinality` → `{}`
- `search_entity_values` → `{}`

The main `gather_context_for_task` checks for exceptions in parallel results and logs warnings.
