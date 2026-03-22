import json
import os
from datetime import datetime
from typing import Any, Optional
from loguru import logger


MEMORY_DIR = "./memory"


class MemoryManager:
    """Manages short-term and long-term memory for conversations."""
    
    def __init__(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)

    
    def compress_short_term(
        self,
        conversation_summary: str,
        last_entities: dict,
        recent_messages: list,
        max_messages: int = 3
    ) -> dict:
        """
        Compress recent context into short-term memory.
        
        Returns dict with:
        - recent_context: Compressed last N exchanges
        - active_entities: Currently relevant entities
        - session_topics: Topics from this session
        """
        recent = recent_messages[-max_messages * 2:] if recent_messages else []
        recent_context = ""
        
        for msg in recent:
            role = msg.get("role", "").upper()
            content = msg.get("content", "")[:200]
            recent_context += f"{role}: {content}\n"
        
        session_topics = []
        if last_entities:
            if "domain" in last_entities:
                session_topics.append(last_entities["domain"])
            if "brands" in last_entities:
                session_topics.extend(last_entities["brands"][:3])
            if "issue_type" in last_entities:
                session_topics.append(last_entities["issue_type"])
        
        return {
            "recent_context": recent_context.strip(),
            "active_entities": last_entities or {},
            "session_topics": list(set(session_topics))[:5]
        }
    
    
    def _get_memory_path(self, thread_id: str) -> str:
        """Get file path for thread's long-term memory."""
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in thread_id)
        return os.path.join(MEMORY_DIR, f"{safe_id}.json")
    
    def load_long_term(self, thread_id: str) -> dict:
        """Load long-term memory for a thread."""
        path = self._get_memory_path(thread_id)
        
        if not os.path.exists(path):
            return self._create_empty_memory(thread_id)
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                memory = json.load(f)
            logger.debug(f"Loaded long-term memory for thread: {thread_id}")
            return memory
        except Exception as e:
            logger.warning(f"Failed to load memory for {thread_id}: {e}")
            return self._create_empty_memory(thread_id)
    
    def _create_empty_memory(self, thread_id: str) -> dict:
        """Create empty long-term memory structure."""
        return {
            "thread_id": thread_id,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "topic_frequency": {},
            "preferred_entities": {
                "airlines": [],
                "hotels": [],
                "brands": [],
                "domains": []
            },
            "common_patterns": [],
            "session_count": 0
        }
    
    def save_long_term(self, thread_id: str, memory: dict) -> None:
        """Save long-term memory for a thread."""
        path = self._get_memory_path(thread_id)
        memory["updated_at"] = datetime.utcnow().isoformat()
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(memory, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved long-term memory for thread: {thread_id}")
        except Exception as e:
            logger.warning(f"Failed to save memory for {thread_id}: {e}")
    
    def update_patterns(
        self,
        thread_id: str,
        query: str,
        entities: dict,
        domain: Optional[str] = None
    ) -> dict:
        """
        Update long-term memory patterns based on current interaction.
        
        Returns updated memory.
        """
        memory = self.load_long_term(thread_id)
        
        # Update topic frequency
        topic_freq = memory.get("topic_frequency", {})
        
        if domain:
            topic_freq[domain] = topic_freq.get(domain, 0) + 1
        
        # Track entity mentions
        if entities:
            for key, value in entities.items():
                if value and key not in ["sentiment", "resolution"]:
                    if isinstance(value, list):
                        for v in value[:3]:
                            topic_freq[str(v)] = topic_freq.get(str(v), 0) + 1
                    elif isinstance(value, str) and len(value) < 50:
                        topic_freq[value] = topic_freq.get(value, 0) + 1
        
        # Limit topic frequency to top 50
        sorted_topics = sorted(topic_freq.items(), key=lambda x: x[1], reverse=True)[:50]
        memory["topic_frequency"] = dict(sorted_topics)
        
        # Update preferred entities
        preferred = memory.get("preferred_entities", {})
        
        if entities:
            if "airline" in entities or "airlines" in entities:
                airlines = entities.get("airline") or entities.get("airlines", [])
                if isinstance(airlines, str):
                    airlines = [airlines]
                for a in airlines[:2]:
                    if a and a not in preferred.get("airlines", []):
                        preferred.setdefault("airlines", []).append(a)
                preferred["airlines"] = preferred.get("airlines", [])[:5]
            
            if "hotel" in entities or "hotels" in entities:
                hotels = entities.get("hotel") or entities.get("hotels", [])
                if isinstance(hotels, str):
                    hotels = [hotels]
                for h in hotels[:2]:
                    if h and h not in preferred.get("hotels", []):
                        preferred.setdefault("hotels", []).append(h)
                preferred["hotels"] = preferred.get("hotels", [])[:5]
            
            if "brand" in entities or "brands" in entities:
                brands = entities.get("brand") or entities.get("brands", [])
                if isinstance(brands, str):
                    brands = [brands]
                for b in brands[:2]:
                    if b and b not in preferred.get("brands", []):
                        preferred.setdefault("brands", []).append(b)
                preferred["brands"] = preferred.get("brands", [])[:5]
        
        if domain and domain not in preferred.get("domains", []):
            preferred.setdefault("domains", []).append(domain)
            preferred["domains"] = preferred.get("domains", [])[:5]
        
        memory["preferred_entities"] = preferred
        
        patterns = memory.get("common_patterns", [])
        query_lower = query.lower()
        
        if "compare" in query_lower or "vs" in query_lower:
            if "comparison" not in patterns:
                patterns.append("comparison")
        if "count" in query_lower or "how many" in query_lower:
            if "quantitative" not in patterns:
                patterns.append("quantitative")
        if "complain" in query_lower or "issue" in query_lower:
            if "complaint_analysis" not in patterns:
                patterns.append("complaint_analysis")
        if "trend" in query_lower or "over time" in query_lower:
            if "trend_analysis" not in patterns:
                patterns.append("trend_analysis")
        
        memory["common_patterns"] = patterns[:10]
        
        # Save updated memory
        self.save_long_term(thread_id, memory)
        
        return memory
    
    def get_context_hints(self, thread_id: str) -> dict:
        """
        Get hints from long-term memory for context resolution.
        
        Returns dict with preferred domains, entities, and patterns.
        """
        memory = self.load_long_term(thread_id)
        
        # Get top domains by frequency
        topic_freq = memory.get("topic_frequency", {})
        domain_counts = {
            k: v for k, v in topic_freq.items() 
            if k in ["Flight", "Hotel", "Retail", "Banking", "Telecom", "Insurance"]
        }
        top_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        
        return {
            "preferred_domains": [d[0] for d in top_domains],
            "preferred_entities": memory.get("preferred_entities", {}),
            "common_patterns": memory.get("common_patterns", []),
            "session_count": memory.get("session_count", 0)
        }
    
    def increment_session(self, thread_id: str) -> None:
        """Increment session count for a thread."""
        memory = self.load_long_term(thread_id)
        memory["session_count"] = memory.get("session_count", 0) + 1
        self.save_long_term(thread_id, memory)


# Singleton instance
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Get singleton MemoryManager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
