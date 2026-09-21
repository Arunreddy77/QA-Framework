"""
Resumes a run that's paused at a human gate (see run.py). Reads the
decision file the paused run left for you, applies it, and continues
the pipeline from exactly where it stopped -- nothing upstream re-runs.

Usage:
    python resume.py <run_id>

The run_id is the long ID run.py printed when it paused. Just its first
8 characters (the part after the underscore in the evidence folder's
name) works too.
"""

import sys
import json
import uuid
from dotenv import load_dotenv

load_dotenv()

from langgraph.types import Command
from graph import build_graph
from llm_gateway import SkillEscalation
from evidence_store import find_run_dir
from run import handle_result


def _full_run_id(run_ref: str, run_dir) -> str | None:
    """LangGraph needs the full run_id as its thread_id. If we were given
    only the 8-character prefix, read the full one back out of the
    review file the paused run wrote into its folder."""
    try:
        uuid.UUID(run_ref)
        return run_ref
    except ValueError:
        pass
    for review_file in sorted(run_dir.glob("*_review.json")):
        return json.loads(review_file.read_text(encoding="utf-8"))["run_id"]
    return None


def main():
    if len(sys.argv) != 2:
        print("Usage: python resume.py <run_id>")
        sys.exit(1)

    run_ref = sys.argv[1]
    try:
        run_dir = find_run_dir(run_ref)
    except RuntimeError as e:
        print(e)
        sys.exit(1)
    if run_dir is None:
        print(f"No evidence folder found for run {run_ref}.")
        print("Either that run doesn't exist, or run.py hasn't been run for it yet.")
        sys.exit(1)

    run_id = _full_run_id(run_ref, run_dir)
    if run_id is None:
        print(f"Found {run_dir.name}, but it has no review file to read the full run ID from.")
        print("Pass the full run_id instead of just the first 8 characters.")
        sys.exit(1)
    config = {"configurable": {"thread_id": run_id}}

    decision_files = sorted(run_dir.glob("*_decision.json"))
    if not decision_files:
        print(f"No pending decision file found for run {run_id}.")
        print("Either this run isn't paused, or run.py hasn't been run for it yet.")
        sys.exit(1)

    decision_file = decision_files[-1]  # most recently created pending gate
    decision = json.loads(decision_file.read_text(encoding="utf-8"))
    print(f"Resuming run {run_id} ({run_dir.name}) with decision from {decision_file.name}:")
    print(json.dumps(decision, indent=2))

    graph, checkpointer = build_graph()
    try:
        result = graph.invoke(Command(resume=decision), config=config)
        handle_result(result, run_id)
    except SkillEscalation as e:
        print(f"Run {run_id} escalated: {e.payload}")
    finally:
        checkpointer.__exit__(None, None, None)


if __name__ == "__main__":
    main()
