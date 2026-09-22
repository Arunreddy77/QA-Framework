"""
The Phase 2 graph: S1 -> S2 -> H1 (real pause/resume) -> S3 -> S5 -> S6 -> S7 -> S9.
If a human rejects at H1, the run ends there rather than continuing --
that's the whole point of a gate: nothing downstream should be able
to proceed past an unresolved ambiguity.
"""

import os
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from state import RunState
import knowledge_store
from nodes import (
    s1_normalize,
    s2_ambiguity_detection,
    h1_gate,
    s3_generate_test_cases,
    s5_generate_scripts,
    s6_execute,
    s7_classify_failures,
    s9_report,
)

DATABASE_URL = os.environ["QA_FRAMEWORK_DATABASE_URL"]


def _after_h1(state: RunState) -> str:
    """Routing function: only proceed to S3 if H1 was actually approved."""
    if state.get("status") == "rejected_at_h1":
        return END
    return "s3_generate_test_cases"


def build_graph():
    builder = StateGraph(RunState)

    builder.add_node("s1_normalize", s1_normalize)
    builder.add_node("s2_ambiguity_detection", s2_ambiguity_detection)
    builder.add_node("h1_gate", h1_gate)
    builder.add_node("s3_generate_test_cases", s3_generate_test_cases)
    builder.add_node("s5_generate_scripts", s5_generate_scripts)
    builder.add_node("s6_execute", s6_execute)
    builder.add_node("s7_classify_failures", s7_classify_failures)
    builder.add_node("s9_report", s9_report)

    builder.add_edge(START, "s1_normalize")
    builder.add_edge("s1_normalize", "s2_ambiguity_detection")
    builder.add_edge("s2_ambiguity_detection", "h1_gate")
    builder.add_conditional_edges("h1_gate", _after_h1, ["s3_generate_test_cases", END])
    builder.add_edge("s3_generate_test_cases", "s5_generate_scripts")
    builder.add_edge("s5_generate_scripts", "s6_execute")
    builder.add_edge("s6_execute", "s7_classify_failures")
    builder.add_edge("s7_classify_failures", "s9_report")
    builder.add_edge("s9_report", END)

    # Deliberately not using PostgresSaver as a `with` block -- that
    # would close the connection the moment this function returns.
    # The caller is responsible for closing checkpointer via __exit__
    # when the process shuts down.
    #
    # Note: the context manager itself (`cm`) has to be kept alive and
    # returned -- calling .__enter__() on it without holding a reference
    # to it would let Python garbage-collect it immediately, which closes
    # the connection right away (before it's ever used).
    cm = PostgresSaver.from_conn_string(DATABASE_URL)
    checkpointer = cm.__enter__()
    checkpointer.setup()  # creates checkpoint tables on first run; safe to call every time
    knowledge_store.setup()  # creates the domain_rules table on first run; safe to call every time
    return builder.compile(checkpointer=checkpointer), cm
