"""
LLM Usage Metrics Callback Handler

This module provides a LangChain callback handler that automatically tracks:
- Input/output tokens for every LLM call
- Latency for each call
- Number of API calls
- Cost calculation (GPT-4o-mini pricing)

Usage:
    from utils.metrics_callback import MetricsCallbackHandler, get_metrics_handler

    # Get the global handler
    handler = get_metrics_handler()
    
    # Use with LangChain
    llm = ChatOpenAI(callbacks=[handler])
    
    # Or add to existing chain
    chain.invoke(input, config={"callbacks": [handler]})
    
    # Get metrics
    print(handler.get_metrics())
    
    # Reset for new session
    handler.reset()
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from loguru import logger


# Pricing per 1M tokens (GPT-4o-mini)
GPT4O_MINI_INPUT_PRICE = 0.15  # $0.15 per 1M input tokens
GPT4O_MINI_OUTPUT_PRICE = 0.60  # $0.60 per 1M output tokens

# GPT-4o pricing for reference
GPT4O_INPUT_PRICE = 2.50  # $2.50 per 1M input tokens
GPT4O_OUTPUT_PRICE = 10.00  # $10.00 per 1M output tokens


@dataclass
class LLMCallMetrics:
    """Metrics for a single LLM call."""
    node_name: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    timestamp: float
    
    def get_cost(self, model: str = None) -> float:
        """Calculate cost for this call based on model."""
        model = model or self.model
        if "gpt-4o-mini" in model.lower():
            input_price = GPT4O_MINI_INPUT_PRICE
            output_price = GPT4O_MINI_OUTPUT_PRICE
        elif "gpt-4o" in model.lower():
            input_price = GPT4O_INPUT_PRICE
            output_price = GPT4O_OUTPUT_PRICE
        else:
            # Default to gpt-4o-mini pricing
            input_price = GPT4O_MINI_INPUT_PRICE
            output_price = GPT4O_MINI_OUTPUT_PRICE
        
        return (self.input_tokens / 1_000_000) * input_price + \
               (self.output_tokens / 1_000_000) * output_price


@dataclass
class AggregateMetrics:
    """Aggregate metrics across all LLM calls."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_api_calls: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    calls_by_node: Dict[str, int] = field(default_factory=dict)
    tokens_by_node: Dict[str, Dict[str, int]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_api_calls": self.total_api_calls,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "average_latency_ms": round(self.total_latency_ms / max(1, self.total_api_calls), 2),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "avg_cost_per_call_usd": round(self.total_cost_usd / max(1, self.total_api_calls), 6),
            "calls_by_node": dict(self.calls_by_node),
            "tokens_by_node": dict(self.tokens_by_node)
        }


class MetricsCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that tracks LLM usage metrics.
    
    Automatically captures:
    - Token counts (input/output) from LLM responses
    - Latency for each LLM call
    - Cost calculation based on model
    
    Thread-safe for concurrent use.
    """
    
    def __init__(self, name: str = "default"):
        super().__init__()
        self.name = name
        self._lock = threading.Lock()
        self._call_starts: Dict[str, float] = {}  # run_id -> start_time
        self._current_node: str = "unknown"
        self._calls: List[LLMCallMetrics] = []
        self._aggregate = AggregateMetrics()
    
    def set_current_node(self, node_name: str):
        """Set the current node name for attribution."""
        self._current_node = node_name
    
    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Record the start time of an LLM call."""
        with self._lock:
            self._call_starts[str(run_id)] = time.time()
    
    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        """Record metrics when LLM call completes."""
        end_time = time.time()
        run_id_str = str(run_id)
        
        with self._lock:
            start_time = self._call_starts.pop(run_id_str, end_time)
            latency_ms = (end_time - start_time) * 1000
            
            # Extract token usage from response
            input_tokens = 0
            output_tokens = 0
            model = "unknown"
            
            if response.llm_output:
                token_usage = response.llm_output.get("token_usage", {})
                input_tokens = token_usage.get("prompt_tokens", 0)
                output_tokens = token_usage.get("completion_tokens", 0)
                model = response.llm_output.get("model_name", "gpt-4o-mini")
            
            # Create call metrics
            call = LLMCallMetrics(
                node_name=self._current_node,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                timestamp=end_time
            )
            self._calls.append(call)
            
            # Update aggregates
            self._aggregate.total_input_tokens += input_tokens
            self._aggregate.total_output_tokens += output_tokens
            self._aggregate.total_api_calls += 1
            self._aggregate.total_latency_ms += latency_ms
            self._aggregate.total_cost_usd += call.get_cost()
            
            # Track by node
            node = self._current_node
            self._aggregate.calls_by_node[node] = self._aggregate.calls_by_node.get(node, 0) + 1
            
            if node not in self._aggregate.tokens_by_node:
                self._aggregate.tokens_by_node[node] = {"input": 0, "output": 0}
            self._aggregate.tokens_by_node[node]["input"] += input_tokens
            self._aggregate.tokens_by_node[node]["output"] += output_tokens
            
            logger.debug(
                f"[METRICS] {node}: {input_tokens} in, {output_tokens} out, "
                f"{latency_ms:.0f}ms, ${call.get_cost():.6f}"
            )
    
    def on_llm_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        """Clean up on error."""
        run_id_str = str(run_id)
        with self._lock:
            self._call_starts.pop(run_id_str, None)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current aggregate metrics."""
        with self._lock:
            return self._aggregate.to_dict()
    
    def get_calls(self) -> List[Dict[str, Any]]:
        """Get all individual call metrics."""
        with self._lock:
            return [
                {
                    "node_name": c.node_name,
                    "model": c.model,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "latency_ms": round(c.latency_ms, 2),
                    "cost_usd": round(c.get_cost(), 6),
                    "timestamp": c.timestamp
                }
                for c in self._calls
            ]
    
    def get_summary(self) -> str:
        """Get a formatted summary string."""
        m = self.get_metrics()
        lines = [
            "=" * 50,
            "LLM USAGE METRICS SUMMARY",
            "=" * 50,
            f"Total API Calls:        {m['total_api_calls']}",
            f"Total Input Tokens:     {m['total_input_tokens']:,}",
            f"Total Output Tokens:    {m['total_output_tokens']:,}",
            f"Average Latency:        {m['average_latency_ms']:.0f} ms",
            f"Total Cost:             ${m['total_cost_usd']:.4f}",
            f"Avg Cost/Call:          ${m['avg_cost_per_call_usd']:.6f}",
            "-" * 50,
            "Calls by Node:",
        ]
        for node, count in m.get("calls_by_node", {}).items():
            tokens = m.get("tokens_by_node", {}).get(node, {})
            lines.append(f"  {node}: {count} calls ({tokens.get('input', 0)} in, {tokens.get('output', 0)} out)")
        lines.append("=" * 50)
        return "\n".join(lines)
    
    def reset(self):
        """Reset all metrics."""
        with self._lock:
            self._calls = []
            self._aggregate = AggregateMetrics()
            self._call_starts = {}
            logger.info("[METRICS] Metrics reset")
    
    def log_summary(self):
        """Log the current summary."""
        logger.info(f"\n{self.get_summary()}")


# Global singleton handler
_global_handler: Optional[MetricsCallbackHandler] = None
_handler_lock = threading.Lock()


def get_metrics_handler(name: str = "global") -> MetricsCallbackHandler:
    """Get the global metrics handler singleton."""
    global _global_handler
    with _handler_lock:
        if _global_handler is None:
            _global_handler = MetricsCallbackHandler(name=name)
        return _global_handler


def reset_global_metrics():
    """Reset the global metrics handler."""
    handler = get_metrics_handler()
    handler.reset()


def get_global_metrics() -> Dict[str, Any]:
    """Get metrics from the global handler."""
    handler = get_metrics_handler()
    return handler.get_metrics()
