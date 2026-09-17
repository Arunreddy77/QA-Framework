"""
Resumes a run that's paused at a human gate (see run.py). Reads the
decision file the paused run left for you, applies it, and continues
the pipeline from exactly where it stopped -- nothing upstream re-runs.

Usage:
    python resume.py <run_id>

The run_id is the long ID run.py printed when it paused.
"""

import sys
import json
from dotenv import load_dotenv

load_dotenv()

from langgraph.types import Command
from graph import build_graph
from llm_gateway import SkillEscalation
from evidence_store import run_evidence_dir
from run import handle_result


def main():
    if len(sys.argv) != 2:
        print("Usage: python resume.py <run_id>")
        sys.exit(1)

    run_id = sys.argv[1]
    config = {"configurable": {"thread_id": run_id}}

    decision_files = sorted(run_evidence_dir(run_id).glob("*_decision.json"))
    if not decision_files:
        print(f"No pending decision file found for run {run_id}.")
        print("Either this run isn't paused, or run.py hasn't been run for it yet.")
        sys.exit(1)

    decision_file = decision_files[-1]  # most recently created pending gate
    decision = json.loads(decision_file.read_text(encoding="utf-8"))
    print(f"Resuming run {run_id} with decision from {decision_file.name}:")
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
