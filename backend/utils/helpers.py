"""Helper utilities for JSON extraction and text processing."""

import re
import json
from typing import Any, Optional


def extract_json_safely(text: str, default: Optional[Any] = None) -> Any:
    """
    Args:
        text: Text potentially containing JSON
        default: Default value if extraction fails
        
    Returns:
        Parsed JSON or default value
    """
    if default is None:
        default = {}
        
    text = text.strip()
    
    # Handle markdown code blocks
    if text.startswith("```"):
        text = text[text.find('\n')+1:text.rfind('```')].strip()
    
    # Try to find JSON object
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    # Try to find JSON array
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    return default


def format_chat_history(history: list, max_messages: int = 6) -> str:
    """Format chat history for prompts."""
    if not history:
        return ""
    
    formatted = []
    for msg in history[-max_messages:]:
        role = "User" if msg["role"] == "user" else "Assistant"
        content = msg["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        formatted.append(f"{role}: {content}")
    
    return "\n".join(formatted)


def truncate_results(results: dict, max_rows: int = 7, max_chars: int = 40000) -> str:
    """Format and truncate results for the answer prompt."""
    context_data = ""
    
    for task, rows in results.items():
        if len(context_data) > max_chars:
            context_data += "\n[...Context Truncated due to size limit...]"
            break
            
        context_data += f"### Subquery: {task}\n"
        
        if not isinstance(rows, list):
            rows = [rows]
        
        truncated_rows = rows[:max_rows]
        data_str = json.dumps(truncated_rows, default=str)
        context_data += f"Data Retrieved: {data_str}\n\n"
    
    return context_data
