"""
Shared state that flows through every node in the graph.
LangGraph passes this dict between nodes; each node reads what it
needs and returns only the keys it's updating -- LangGraph merges
the rest automatically.
"""

from typing import TypedDict, Optional, Any
import uuid


class RunState(TypedDict, total=False):
    run_id: str
    correlation_id: str

    # Input
    raw_input: str
    source_type: str  # "brd" | "jira_ticket" | "user_story" | "acceptance_criteria" | "other"

    # Per-skill outputs -- each is the parsed JSON the skill returned
    s1_output: dict
    s3_output: list
    s4_output: list  # not built yet -- see run.py note on the Phase 1 gap
    s5_output: list
    s6_output: dict
    s9_output: dict

    # Bookkeeping
    status: str  # "running" | "escalated" | "complete" | "failed"
    escalation: Optional[dict]
    error: Optional[str]


def new_run_state(raw_input: str, source_type: str = "other") -> RunState:
    run_id = str(uuid.uuid4())
    return RunState(
        run_id=run_id,
        correlation_id=run_id,  # one correlation ID per run, per Section 4 of AGENT_INSTRUCTIONS.md
        raw_input=raw_input,
        source_type=source_type,
        status="running",
        escalation=None,
        error=None,
    )
