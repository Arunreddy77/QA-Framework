"""
One function per skill, wired as LangGraph nodes. Each function's job
is narrow: read what it needs from RunState, call the skill (or run
deterministic logic), return only the keys it's updating.

Phase 2 adds S2 (ambiguity detection) and the real H1 gate -- a genuine
pause-and-wait-for-a-human step, using LangGraph's interrupt(). S4,
S7, S8, S10, S11 and H2-H5 are still not wired in; see the project
overview for what remains.
"""

import json
import re
import subprocess
from pathlib import Path
from langgraph.types import interrupt
from llm_gateway import call_skill, SkillEscalation
from state import RunState
from evidence_store import scripts_dir, allure_results_dir, allure_report_dir, run_evidence_dir
import knowledge_store


def s1_normalize(state: RunState) -> dict:
    """
    S1 is deterministic code for structured input, per the earlier
    decision to not spend an LLM call on pure reshaping. Falls back
    to the S1 skill (an LLM call) only when the input has no
    recognizable structure -- e.g. a pasted paragraph with no
    headings or clear sections.
    """
    raw = state["raw_input"]

    has_structure = bool(re.search(r"(?im)^(description|acceptance criteria|summary|title)\s*:", raw))

    if has_structure:
        sections = {}
        current_key = "unstructured_fragments"
        current_lines = []
        for line in raw.splitlines():
            header_match = re.match(r"(?i)^(description|acceptance criteria|summary|title)\s*:\s*(.*)", line)
            if header_match:
                if current_lines:
                    sections.setdefault(current_key, []).append("\n".join(current_lines).strip())
                current_key = header_match.group(1).lower().replace(" ", "_")
                current_lines = [header_match.group(2)]
            else:
                current_lines.append(line)
        if current_lines:
            sections.setdefault(current_key, []).append("\n".join(current_lines).strip())

        output = {
            "source_type": state.get("source_type", "other"),
            "title_summary": sections.get("title", sections.get("summary", [""]))[0],
            "description": sections.get("description", [""])[0],
            "acceptance_criteria": sections.get("acceptance_criteria", []),
            "business_rules_referenced": [],  # S2 identifies these next
            "unstructured_fragments": sections.get("unstructured_fragments", []),
            "original_source_reference": state["run_id"],
        }
        return {"s1_output": output}

    output = call_skill(
        "S1_input_normalization.md",
        {"raw_input": raw, "source_type": state.get("source_type", "other")},
    )
    return {"s1_output": output}


def s2_ambiguity_detection(state: RunState) -> dict:
    """
    NEW in Phase 2. Tags every statement FACT / ASSUMPTION / INFERENCE /
    DECISION against the currently-confirmed Domain Knowledge Store
    entries (real Postgres rows now, via knowledge_store.py -- not an
    empty list like S3 used in Phase 1).
    """
    payload = {
        "normalized_requirement": state["s1_output"],
        "confirmed_domain_rules": knowledge_store.get_confirmed_rules(),
    }
    output = call_skill("S2_ambiguity_detection.md", payload)
    return {"s2_output": output}


def h1_gate(state: RunState) -> dict:
    """
    NEW in Phase 2. The first REAL human-in-the-loop gate. This node
    calls interrupt() -- LangGraph pauses the graph here, persists its
    state to Postgres via the checkpointer, and .invoke() returns
    control to run.py with the interrupt payload. Nothing continues
    until someone resumes this exact run with a decision (see resume.py).

    Expected shape of the human's decision, once resumed:
        {
            "approved": bool,
            "new_confirmed_rules": [str, ...],   # ASSUMPTION/INFERENCE items
                                                   # the human resolved into facts
            "notes": str                          # optional, for the record
        }
    """
    decision = interrupt({
        "gate": "H1",
        "run_id": state["run_id"],
        "tagged_statements": state["s2_output"].get("tagged_statements", []),
        "ambiguity_list": state["s2_output"].get("ambiguity_list", []),
        "instruction": (
            "Review the ambiguity_list below. For each item, either resolve it "
            "(add the resolved statement to new_confirmed_rules) or leave it "
            "unresolved. Set approved=true only if every blocking ambiguity is "
            "resolved and you're satisfied the requirement is unambiguous "
            "enough to generate test cases from."
        ),
    })

    if decision.get("approved"):
        for rule in decision.get("new_confirmed_rules", []):
            knowledge_store.add_confirmed_rule(rule, state["run_id"])
        return {"status": "running", "h1_decision": decision}

    return {"status": "rejected_at_h1", "h1_decision": decision}


def s3_generate_test_cases(state: RunState) -> dict:
    payload = {
        "normalized_requirement": state["s1_output"],
        "tagged_statements": state["s2_output"].get("tagged_statements", []),
        "confirmed_domain_rules": knowledge_store.get_confirmed_rules(),
        "h1_decision": state.get("h1_decision", {}),
    }
    output = call_skill("S3_test_case_generation.md", payload)
    return {"s3_output": output}


def s5_generate_scripts(state: RunState) -> dict:
    payload = {
        "approved_test_cases": state["s3_output"],
        # S4 still not built -- placeholder data only. Real runs need
        # S4 wired in before this output should be trusted.
        "test_data": state.get("s4_output", []),
    }
    output = call_skill("S5_test_script_generation.md", payload)
    return {"s5_output": output}


def s6_execute(state: RunState) -> dict:
    """
    Runs the S5-generated Playwright scripts via pytest + pytest-playwright.
    Depends on S5's output being valid Python with a `test_`-prefixed
    function using the `page` fixture -- see the earlier note that this
    isn't yet enforced in S5's own skill.md, only assumed here.
    """
    correlation_id = state["correlation_id"]
    scripts = state["s5_output"]

    script_dir = scripts_dir(correlation_id)
    for script in scripts:
        test_case_id = script.get("test_case_id", "unknown")
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", str(test_case_id))
        script_path = script_dir / f"test_{safe_name}.py"
        script_path.write_text(script["script_code"], encoding="utf-8")

    json_report_path = run_evidence_dir(correlation_id) / "pytest-report.json"
    allure_dir = allure_results_dir(correlation_id)

    result = subprocess.run(
        [
            "pytest",
            str(script_dir),
            "--screenshot=only-on-failure",
            "--video=retain-on-failure",
            "--tracing=retain-on-failure",
            f"--json-report-file={json_report_path}",
            "--json-report",
            f"--alluredir={allure_dir}",
            "-v",
        ],
        capture_output=True,
        text=True,
    )

    try:
        pytest_report = json.loads(json_report_path.read_text(encoding="utf-8"))
        tests = pytest_report.get("tests", [])
    except (FileNotFoundError, json.JSONDecodeError):
        tests = []

    results = [
        {
            "test_case_id": t.get("nodeid", "").split("::")[-1].replace("test_", "", 1),
            "status": t.get("outcome", "unknown"),
            "duration_seconds": t.get("duration"),
        }
        for t in tests
    ]

    return {
        "s6_output": {
            "run_id": state["run_id"],
            "correlation_id": correlation_id,
            "results": results,
            "pytest_returncode": result.returncode,
            "pytest_stderr_tail": result.stderr[-2000:] if result.returncode not in (0, 1) else None,
        }
    }


def s9_report(state: RunState) -> dict:
    correlation_id = state["correlation_id"]

    report_dir = allure_report_dir(correlation_id)
    allure_gen = subprocess.run(
        ["allure", "generate", str(allure_results_dir(correlation_id)), "-o", str(report_dir), "--clean"],
        capture_output=True,
        text=True,
    )
    allure_report_path = str(report_dir / "index.html") if allure_gen.returncode == 0 else None

    payload = {
        "classified_results": state["s6_output"],  # no S7 yet -- unclassified
        "violations": [],  # no S8 yet
        "baseline": None,
    }
    output = call_skill("S9_reporting_aggregation.md", payload)
    output["allure_report_path"] = allure_report_path
    output["allure_generation_error"] = allure_gen.stderr if allure_gen.returncode != 0 else None

    return {"s9_output": output, "status": "complete"}
