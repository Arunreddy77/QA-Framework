"""
Entry point for a single Phase 1 run. Usage:

    QA_FRAMEWORK_ROOT=/path/to/framework \
    QA_FRAMEWORK_DATABASE_URL=postgresql://user:pass@localhost:5432/qa_framework \
    ANTHROPIC_API_KEY=sk-... \
    python run.py path/to/requirement.txt
"""

import sys
import json
from dotenv import load_dotenv

load_dotenv()

from graph import build_graph
from state import new_run_state
from llm_gateway import SkillEscalation


def main():
    if len(sys.argv) != 2:
        print("Usage: python run.py <path-to-requirement-file>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        raw_input = f.read()

    graph, checkpointer = build_graph()
    initial_state = new_run_state(raw_input)

    try:
        result = graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": initial_state["run_id"]}},
        )
        print(f"Run {initial_state['run_id']} complete.")
        report_path = result.get("s9_output", {}).get("allure_report_path")
        if report_path:
            print(f"\nOpen your report here: {report_path}")
        print(json.dumps(result.get("s9_output", {}), indent=2))

    except SkillEscalation as e:
        print(f"Run {initial_state['run_id']} escalated: {e.payload}")
        # In a real deployment this is where the Orchestrator would
        # surface the escalation to the Human Review surface instead
        # of just printing it -- see AGENT_INSTRUCTIONS.md Section 7.

    finally:
        checkpointer.__exit__(None, None, None)


if __name__ == "__main__":
    main()
