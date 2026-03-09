"""Workflow Tracer — captures tool calls, user instructions, corrections, and manual actions as structured traces."""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class TraceEvent:
    type: str  # tool_call, user_instruction, user_correction, user_manual_action, user_decision, question_asked
    # Common
    content: Optional[str] = None
    timestamp: Optional[str] = None
    # tool_call
    tool: Optional[str] = None
    params: Optional[dict] = None
    # user_instruction
    applies_to: Optional[list] = None
    persist: Optional[bool] = None
    # user_correction
    corrects: Optional[str] = None
    new_value: Optional[str] = None
    # user_manual_action
    inferred_step: Optional[str] = None
    action_binding: Optional[str] = None
    auth_note: Optional[str] = None
    # user_decision
    context: Optional[str] = None
    decision: Optional[str] = None
    rationale: Optional[str] = None
    # question_asked
    resolution: Optional[str] = None
    prefill_next_time: Optional[bool] = None
    # inferred
    inferred_intent: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "TraceEvent":
        """Create a TraceEvent from a dictionary, ignoring unknown keys."""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)

    def to_dict(self) -> dict:
        d = {"type": self.type, "timestamp": self.timestamp}
        # Include only non-None fields relevant to this event type
        for k, v in asdict(self).items():
            if v is not None and k != "type" and k != "timestamp":
                d[k] = v
        return d


class WorkflowTracer:
    def __init__(self, traces_dir: str):
        self.traces_dir = Path(traces_dir)
        self.active_dir = self.traces_dir / "active"
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self._traces: dict = {}  # trace_id -> {"events": [], "started_at": str}
        self._active_trace_id: Optional[str] = None

    def start_trace(self, trace_id: str) -> None:
        self._active_trace_id = trace_id
        if trace_id not in self._traces:
            self._traces[trace_id] = {
                "trace_id": trace_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "events": [],
            }

    def add_event(self, event: TraceEvent) -> None:
        trace_id = self._active_trace_id
        if not trace_id or trace_id not in self._traces:
            return
        if not event.timestamp:
            event.timestamp = datetime.now(timezone.utc).isoformat()
        self._traces[trace_id]["events"].append(event.to_dict())

    def get_trace(self, trace_id: str) -> Optional[dict]:
        return self._traces.get(trace_id)

    def flush(self, trace_id: str) -> None:
        trace = self._traces.get(trace_id)
        if not trace:
            return
        path = self.active_dir / f"{trace_id}.json"
        with open(path, "w") as f:
            json.dump(trace, f, indent=2)

    def flush_all(self) -> None:
        for trace_id in list(self._traces):
            self.flush(trace_id)

    def load_trace(self, trace_id: str) -> Optional[dict]:
        path = self.active_dir / f"{trace_id}.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            self._traces[trace_id] = data
            return data
        return None

    def list_traces(self) -> list:
        return [p.stem for p in self.active_dir.glob("*.json")]

    def get_tool_sequence(self, trace_id: str) -> list:
        trace = self._traces.get(trace_id, {})
        return [e.get("tool", "") for e in trace.get("events", []) if e.get("type") == "tool_call" and e.get("tool")]

    def similarity(self, trace_id_a: str, trace_id_b: str) -> float:
        """Compare two traces by their tool call sequences. Returns 0.0-1.0."""
        seq_a = self.get_tool_sequence(trace_id_a)
        seq_b = self.get_tool_sequence(trace_id_b)
        if not seq_a and not seq_b:
            return 1.0
        if not seq_a or not seq_b:
            return 0.0
        # Simple Jaccard + order similarity
        set_a, set_b = set(seq_a), set(seq_b)
        jaccard = len(set_a & set_b) / len(set_a | set_b) if set_a | set_b else 0.0
        # Order: longest common subsequence ratio
        lcs_len = _lcs_length(seq_a, seq_b)
        order_score = (2 * lcs_len) / (len(seq_a) + len(seq_b)) if (seq_a or seq_b) else 0.0
        return 0.5 * jaccard + 0.5 * order_score


def _lcs_length(a: list, b: list) -> int:
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[m][n]
