"""
One function per skill, wired as LangGraph nodes. Each function's job
is narrow: read what it needs from RunState, call the skill (or run
deterministic logic), return only the keys it's updating.

Phase 1 scope note: this slice runs S1 -> S3 -> S5 -> S6 -> S9 with
NO gates and NO S2/S4/S7/S8/S10/S11. That means: S3 receives the raw
normalized input with no FACT/ASSUMPTION/INFERENCE/DECISION tagging
from S2, and S5 has no real test data from S4. This is fine for
proving the pipeline runs end to end -- it is NOT a governed run and
its output should not be treated as reviewed or trustworthy the way
a full-pipeline run would be.
"""

import json
import re
import subprocess
from pathlib import Path
from llm_gateway import call_skill, SkillEscalation
from state import RunState
from evidence_store import scripts_dir, allure_results_dir, allure_report_dir, run_evidence_dir


def s1_normalize(state: RunState) -> dict:
    """
    S1 is deterministic code for structured input, per the earlier
    decision to not spend an LLM call on pure reshaping. Falls back
    to the S1 skill (an LLM call) only when the input has no
    recognizable structure -- e.g. a pasted paragraph with no
    headings or clear sections.
    """
    raw = state["raw_input"]

    # Cheap structure check: does the input already have clear
    # section markers (headings, "Acceptance Criteria:", etc.)?
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
            "business_rules_referenced": [],  # left for S2 to identify
            "unstructured_fragments": sections.get("unstructured_fragments", []),
            "original_source_reference": state["run_id"],
        }
        return {"s1_output": output}

    # No structure detected -- fall back to the actual S1 skill.
    output = call_skill(
        "S1_input_normalization.md",
        {"raw_input": raw, "source_type": state.get("source_type", "other")},
    )
    return {"s1_output": output}


def s3_generate_test_cases(state: RunState) -> dict:
    payload = {
        "normalized_requirement": state["s1_output"],
        # No S2 in this slice -- see module docstring.
        "confirmed_domain_rules": [],
    }
    output = call_skill("S3_test_case_generation.md", payload)
    return {"s3_output": output}


def s5_generate_scripts(state: RunState) -> dict:
    payload = {
        "approved_test_cases": state["s3_output"],
        # No S4 in this slice -- placeholder data only. Real runs
        # need S4 built before this output should be trusted.
        "test_data": state.get("s4_output", []),
    }
    output = call_skill("S5_test_script_generation.md", payload)
    return {"s5_output": output}


def s6_execute(state: RunState) -> dict:
    """
    Actually runs the S5-generated Playwright scripts, for real, using
    pytest + pytest-playwright. Each script is written to its own file,
    then pytest runs the whole batch and produces two things: a JSON
    report (for this skill's own pass/fail bookkeeping) and raw Allure
    results (for S9 to turn into a human-readable report later).

    Important assumption this depends on: each S5-generated script_code
    must be valid Python containing a function starting with `test_`
    that uses the `page` fixture pytest-playwright provides. If S5's
    output doesn't follow that shape, pytest will fail to collect it --
    that will show up as a collection error in the results below, which
    is itself useful signal that S5's skill.md needs tightening.
    """
    correlation_id = state["correlation_id"]
    scripts = state["s5_output"]

    script_dir = scripts_dir(correlation_id)
    for script in scripts:
        test_case_id = script.get("test_case_id", "unknown")
        # pytest requires filenames to start with test_ to auto-discover them
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", str(test_case_id))
        script_path = script_dir / f"test_{safe_name}.py"
        script_path.write_text(script["script_code"], encoding="utf-8")

    json_report_path = run_evidence_dir(correlation_id) / "pytest-report.json"
    allure_dir = allure_results_dir(correlation_id)

    result = subprocess.run(
        [
            "pytest",
            str(script_dir),
            "--screenshot=only-on-failure",  # pytest-playwright: capture evidence per Section 4
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
        # pytest itself failed to run (e.g. every script had a syntax
        # error) -- surface this plainly rather than pretending we have results
        tests = []

    results = [
        {
            "test_case_id": t.get("nodeid", "").split("::")[-1].replace("test_", "", 1),
            "status": t.get("outcome", "unknown"),  # "passed" | "failed" | "error"
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

    # Turn the raw Allure results into an actual HTML report you can open.
    report_dir = allure_report_dir(correlation_id)
    allure_gen = subprocess.run(
        ["allure", "generate", str(allure_results_dir(correlation_id)), "-o", str(report_dir), "--clean"],
        capture_output=True,
        text=True,
    )
    allure_report_path = str(report_dir / "index.html") if allure_gen.returncode == 0 else None

    payload = {
        "classified_results": state["s6_output"],  # no S7 in this slice -- unclassified
        "violations": [],  # no S8 in this slice
        "baseline": None,
    }
    output = call_skill("S9_reporting_aggregation.md", payload)
    output["allure_report_path"] = allure_report_path
    output["allure_generation_error"] = allure_gen.stderr if allure_gen.returncode != 0 else None

    return {"s9_output": output, "status": "complete"}
