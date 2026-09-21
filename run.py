"""
Entry point for a run. Starts the pipeline; if it hits a human gate
(H1, so far -- H2-H5 aren't built yet), it stops there, writes the
gate's details to a file for you to review, and tells you exactly
what to do next. See resume.py for continuing a paused run.

Usage:
    python run.py path/to/requirement.txt
"""

import sys
import json
from dotenv import load_dotenv

load_dotenv()

from graph import build_graph
from state import new_run_state
from llm_gateway import SkillEscalation
from evidence_store import run_evidence_dir


def handle_result(result: dict, run_id: str) -> None:
    """
    Shared by run.py and resume.py: either the run just paused at a
    gate (write it out for a human), or it actually finished (print
    the report path), or -- in principle -- it paused at a second
    gate in a future version with more gates wired in.
    """
    interrupts = result.get("__interrupt__")
    if interrupts:
        gate_payload = interrupts[0].value
        gate_name = gate_payload["gate"]

        run_dir = run_evidence_dir(run_id, result.get("run_slug"))
        gate_file = run_dir / f"{gate_name}_review.json"
        gate_file.write_text(json.dumps(gate_payload, indent=2), encoding="utf-8")

        decision_file = run_dir / f"{gate_name}_decision.json"
        decision_file.write_text(json.dumps({
            "approved": False,
            "new_confirmed_rules": [],
            "notes": "",
        }, indent=2), encoding="utf-8")

        print(f"\nRun {run_id} is PAUSED at gate {gate_name}.")
        print("\nNo AI calls happen and nothing costs money while paused --")
        print("take whatever time you need.")
        print(f"\n1. Open and read:   {gate_file}")
        print(f"2. Edit your decision in: {decision_file}")
        print("   (set \"approved\": true only once every ambiguity is resolved;")
        print("    list anything you've resolved under \"new_confirmed_rules\")")
        print(f"3. Then run:        python resume.py {run_id}")
        return

    print(f"Run {run_id} complete.")
    report_path = result.get("s9_output", {}).get("allure_report_path")
    if report_path:
        print(f"\nOpen your report here: {report_path}")
    print(json.dumps(result.get("s9_output", {}), indent=2))


def main():
    if len(sys.argv) != 2:
        print("Usage: python run.py <path-to-requirement-file>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        raw_input = f.read()

    graph, checkpointer = build_graph()
    initial_state = new_run_state(raw_input)
    config = {"configurable": {"thread_id": initial_state["run_id"]}}

    try:
        result = graph.invoke(initial_state, config=config)
        handle_result(result, initial_state["run_id"])
    except SkillEscalation as e:
        print(f"Run {initial_state['run_id']} escalated: {e.payload}")
        # In a real deployment this is where the Orchestrator would
        # surface the escalation to the Human Review surface instead
        # of just printing it -- see AGENT_INSTRUCTIONS.md Section 7.
    finally:
        checkpointer.__exit__(None, None, None)


if __name__ == "__main__":
    main()
