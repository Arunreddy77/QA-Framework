"""
The Phase 1 graph: S1 -> S3 -> S5 -> S6 -> S9, linear, no gates.
This is the actual "Orchestrator" -- deterministic code, not an LLM --
that AGENT_INSTRUCTIONS.md Section 1 refers to. It sequences skills
and owns run state; it never generates content itself.
"""

import os
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from state import RunState
from nodes import s1_normalize, s3_generate_test_cases, s5_generate_scripts, s6_execute, s9_report

DATABASE_URL = os.environ["QA_FRAMEWORK_DATABASE_URL"]


def build_graph():
    builder = StateGraph(RunState)

    builder.add_node("s1_normalize", s1_normalize)
    builder.add_node("s3_generate_test_cases", s3_generate_test_cases)
    builder.add_node("s5_generate_scripts", s5_generate_scripts)
    builder.add_node("s6_execute", s6_execute)
    builder.add_node("s9_report", s9_report)

    builder.add_edge(START, "s1_normalize")
    builder.add_edge("s1_normalize", "s3_generate_test_cases")
    builder.add_edge("s3_generate_test_cases", "s5_generate_scripts")
    builder.add_edge("s5_generate_scripts", "s6_execute")
    builder.add_edge("s6_execute", "s9_report")
    builder.add_edge("s9_report", END)

    # PostgresSaver gives durable, resumable execution -- if the
    # process dies mid-run, re-invoking with the same thread_id
    # picks up from the last completed node instead of restarting.
    #
    # Deliberately NOT using PostgresSaver as a `with` block here --
    # that would close the connection the moment this function
    # returns, breaking every subsequent .invoke() call. The caller
    # (run.py) is responsible for closing checkpointer.conn when the
    # process shuts down.
    checkpointer = PostgresSaver.from_conn_string(DATABASE_URL).__enter__()
    checkpointer.setup()  # creates the checkpoint tables on first run; safe to call every time
    return builder.compile(checkpointer=checkpointer), checkpointer
