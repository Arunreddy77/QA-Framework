"""
Shared state that flows through every node in the graph.
LangGraph passes this dict between nodes; each node reads what it
needs and returns only the keys it's updating -- LangGraph merges
the rest automatically.
"""

from typing import TypedDict, Optional, Any
import os
import uuid


class RunState(TypedDict, total=False):
    run_id: str
    correlation_id: str
    run_slug: str  # readable evidence-folder prefix, made from the requirement's Title by S1 (see evidence_store.make_slug)

    # Input
    raw_input: str
    source_type: str  # "brd" | "jira_ticket" | "user_story" | "acceptance_criteria" | "other"

    # S6 execution mode -- per-run, so a headed run can be requested from the
    # UI without a server restart. Falls back to the S6_HEADED / S6_SLOW_MO_MS
    # env vars (see new_run_state) when not given explicitly.
    headed: bool
    slow_mo_ms: int

    # Per-skill outputs -- each is the parsed JSON the skill returned
    s1_output: dict
    s2_output: dict  # NEW in Phase 2: tagged statements + ambiguity list from S2
    h1_decision: dict  # NEW in Phase 2: the human's actual decision at the H1 gate
    s3_output: list
    s4_output: list  # not built yet -- see nodes.py note on the remaining gap
    s5_output: list
    s6_output: dict
    s7_output: dict  # failure classifications from S7: {"classifications": [...]}
    s9_output: dict

    # Bookkeeping
    status: str  # "running" | "escalated" | "rejected_at_h1" | "complete" | "failed"
    escalation: Optional[dict]
    error: Optional[str]


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def new_run_state(
    raw_input: str,
    source_type: str = "other",
    headed: Optional[bool] = None,
    slow_mo_ms: Optional[int] = None,
) -> RunState:
    run_id = str(uuid.uuid4())
    return RunState(
        run_id=run_id,
        correlation_id=run_id,  # one correlation ID per run, per Section 4 of AGENT_INSTRUCTIONS.md
        raw_input=raw_input,
        source_type=source_type,
        headed=_env_bool("S6_HEADED") if headed is None else headed,
        slow_mo_ms=int(os.environ.get("S6_SLOW_MO_MS", "0")) if slow_mo_ms is None else slow_mo_ms,
        status="running",
        escalation=None,
        error=None,
    )
