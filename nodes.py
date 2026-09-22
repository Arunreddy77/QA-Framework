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
import sys
from pathlib import Path
from langgraph.types import interrupt
from llm_gateway import call_skill, SkillEscalation
from state import RunState
from evidence_store import scripts_dir, allure_results_dir, allure_report_dir, run_evidence_dir, make_slug
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
        return {"s1_output": output, "run_slug": make_slug(output["title_summary"])}

    output = call_skill(
        "S1_input_normalization.md",
        {"raw_input": raw, "source_type": state.get("source_type", "other")},
    )
    return {"s1_output": output, "run_slug": make_slug(output.get("title_summary", ""))}


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


# Column order/labels for test_cases.xlsx -- (Excel header, S3 output.json key).
# "Tags" is source_tags: the FACT/ASSUMPTION/INFERENCE/DECISION tags S3 carries
# forward from S2 (see skills/S3_test_case_generation.md's Output format).
TEST_CASE_XLSX_COLUMNS = [
    ("Test Case ID", "test_case_id"),
    ("Source Requirement ID", "source_requirement_id"),
    ("Obligation", "obligation"),
    ("Test Type", "test_type"),
    ("Layer", "layer"),
    ("Input Values", "input_values"),
    ("Expected Result", "expected_result"),
    ("Tags", "source_tags"),
]


def _xlsx_cell(value) -> str:
    """Excel cells hold text, not nested Python data -- S3 emits input_values
    and source_tags as a dict/list, so flatten those to compact JSON. Plain
    strings and numbers pass through untouched."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(", ", ": "))
    return "" if value is None else value


def _write_test_cases_export(run_dir: Path, s3_output) -> None:
    """
    Writes test_cases.json (S3's output, verbatim) and test_cases.xlsx (one
    row per test case, per TEST_CASE_XLSX_COLUMNS) into a run's evidence
    folder. Runs for every run, terminal or UI-triggered, since both go
    through this same node. Never raises -- a failed export (e.g. S3
    returned something odd) shouldn't fail the run; it just leaves the
    files missing, and s9_report's evidence links reflect that.
    """
    (run_dir / "test_cases.json").write_text(json.dumps(s3_output, indent=2), encoding="utf-8")

    cases = s3_output.get("test_cases", []) if isinstance(s3_output, dict) else list(s3_output or [])
    if not cases:
        return

    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Test Cases"
    headers = [h for h, _ in TEST_CASE_XLSX_COLUMNS]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for case in cases:
        if not isinstance(case, dict):
            continue
        ws.append([_xlsx_cell(case.get(key)) for _, key in TEST_CASE_XLSX_COLUMNS])

    for i, header in enumerate(headers, start=1):
        col_lengths = [len(header)] + [len(str(row[i - 1].value or "")) for row in ws.iter_rows(min_row=2)]
        width = max(col_lengths)
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 80)

    wb.save(run_dir / "test_cases.xlsx")


def s3_generate_test_cases(state: RunState) -> dict:
    payload = {
        "normalized_requirement": state["s1_output"],
        "tagged_statements": state["s2_output"].get("tagged_statements", []),
        "confirmed_domain_rules": knowledge_store.get_confirmed_rules(),
        "h1_decision": state.get("h1_decision", {}),
    }
    # S3 can emit many test cases in one JSON response -- the default
    # budget (8192) was cutting it off mid-string. 32768 stays safely
    # under every provider's ceiling in use here (Claude Haiku 4.5: 64K,
    # OpenRouter's nemotron-3-ultra: 65536) while giving plenty of room.
    output = call_skill("S3_test_case_generation.md", payload, max_tokens=32768)
    _write_test_cases_export(run_evidence_dir(state["correlation_id"], state.get("run_slug")), output)
    return {"s3_output": output}


def s5_generate_scripts(state: RunState) -> dict:
    payload = {
        "approved_test_cases": state["s3_output"],
        # S4 still not built -- placeholder data only. Real runs need
        # S4 wired in before this output should be trusted.
        "test_data": state.get("s4_output", []),
    }
    # Same truncation problem as S3 (see comment above), and worse here --
    # full script code as JSON strings is more verbose per test case than
    # S3's structured fields. Same safe ceiling applies.
    output = call_skill("S5_test_script_generation.md", payload, max_tokens=32768)
    return {"s5_output": output}


def _scripts_for_run(state: RunState) -> list:
    """
    The S5 scripts s6_execute should run -- but only after checking S5
    actually covered what S3 approved. Raises (so pytest never starts)
    instead of quietly running nothing, or only some of the approved
    tests: a run that "completes" with 0 or a fraction of its tests is
    worse than one that stops and says exactly why.

    s5_output is the full skill response, {"scripts": [...]}, and
    s3_output is {"test_cases": [...]}.
    """
    s5 = state["s5_output"]
    scripts = s5.get("scripts", []) if isinstance(s5, dict) else []
    s3 = state["s3_output"]
    cases = s3.get("test_cases", []) if isinstance(s3, dict) else list(s3 or [])

    if not scripts:
        keys = sorted(s5) if isinstance(s5, dict) else type(s5).__name__
        raise RuntimeError(
            f"S5 produced no scripts (its response had top-level keys {keys}, "
            f'expected {{"scripts": [...]}}) but S3 approved {len(cases)} test case(s) '
            "-- not running pytest."
        )

    if len(scripts) != len(cases):
        case_ids = [c.get("test_case_id") for c in cases if isinstance(c, dict)]
        script_ids = [s.get("test_case_id") for s in scripts if isinstance(s, dict)]
        missing = [i for i in case_ids if i not in script_ids]
        extra = [i for i in script_ids if i not in case_ids]
        detail = ""
        if missing:
            detail += f" No script for: {missing}."
        if extra:
            detail += f" Script(s) for test cases S3 didn't approve: {extra}."
        raise RuntimeError(
            f"S5 produced {len(scripts)} script(s) but S3 approved {len(cases)} test case(s)."
            f"{detail} -- not running pytest."
        )

    return scripts


def s6_execute(state: RunState) -> dict:
    """
    Runs the S5-generated Playwright scripts via pytest + pytest-playwright.
    Depends on S5's output being valid Python with a `test_`-prefixed
    function using the `page` fixture -- see the earlier note that this
    isn't yet enforced in S5's own skill.md, only assumed here.
    """
    correlation_id = state["correlation_id"]
    run_slug = state.get("run_slug")  # None for runs started before slugs existed
    scripts = _scripts_for_run(state)  # raises if S5 didn't cover every S3 test case

    script_dir = scripts_dir(correlation_id, run_slug)
    for script in scripts:
        test_case_id = script.get("test_case_id", "unknown")
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", str(test_case_id))
        script_path = script_dir / f"test_{safe_name}.py"
        script_path.write_text(script["script_code"], encoding="utf-8")

    json_report_path = run_evidence_dir(correlation_id, run_slug) / "pytest-report.json"
    allure_dir = allure_results_dir(correlation_id, run_slug)

    result = subprocess.run(
        [
            # Bare "pytest" resolves via PATH, which can silently pick up
            # an unrelated pytest install (e.g. one at ~/.local/bin) that
            # doesn't have pytest-json-report/allure-pytest installed --
            # sys.executable -m pytest guarantees the one in *this*
            # venv, where those plugins actually live.
            sys.executable,
            "-m",
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
            "nodeid": t.get("nodeid"),
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


# The five values S7's skill may return for `classification` (skills/S7_failure_classification.md).
S7_CLASSIFICATIONS = {"app_bug", "flaky", "environment", "automation_error", "unclassified_pending_triage"}


def _script_stem(nodeid: str) -> str:
    """'.../scripts/test_TC001.py::test_x[chromium]' -> 'TC001': the S5 test_case_id
    as s6_execute sanitised it into the script's file name."""
    stem = Path(nodeid.split("::")[0]).stem
    return stem[len("test_"):] if stem.startswith("test_") else stem


def _s3_cases_by_stem(state: RunState) -> dict:
    """S3's test cases, keyed the same way script files are named, so a
    failing test can be traced back to the test case it implements."""
    s3 = state.get("s3_output")
    cases = s3.get("test_cases", []) if isinstance(s3, dict) else list(s3 or [])
    return {
        re.sub(r"[^a-zA-Z0-9_]", "_", str(c.get("test_case_id"))): c
        for c in cases if isinstance(c, dict)
    }


def _failure_details(test: dict) -> tuple:
    """(error message, traceback tail) from whichever stage of a
    pytest-json-report entry actually failed."""
    for stage in ("setup", "call", "teardown"):
        s = test.get(stage) or {}
        if s.get("outcome") in ("failed", "error"):
            return (s.get("crash") or {}).get("message", ""), (s.get("longrepr") or "")[-2000:]
    return "", ""


def s7_classify_failures(state: RunState) -> dict:
    """
    Classifies every failed test S6 ran as app_bug / flaky / environment /
    automation_error (or unclassified_pending_triage when the evidence
    can't settle it), so S9 never has to report on an unclassified
    failure. Reads the error details from the pytest report S6 wrote,
    since S6's own output only carries status and duration. If nothing
    failed there is nothing to classify and no AI call is made.
    Always writes evidence/<run folder>/S7_classifications.json.
    """
    correlation_id = state["correlation_id"]
    run_slug = state.get("run_slug")
    run_dir = run_evidence_dir(correlation_id, run_slug)

    try:
        pytest_report = json.loads((run_dir / "pytest-report.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pytest_report = {}
    failed = [t for t in pytest_report.get("tests", []) if t.get("outcome") in ("failed", "error")]

    cases_by_stem = _s3_cases_by_stem(state)
    script_dir = scripts_dir(correlation_id, run_slug)
    failures, used_ids = [], set()
    for t in failed:
        nodeid = t.get("nodeid", "")
        stem = _script_stem(nodeid)
        case = cases_by_stem.get(stem)
        test_ref = f"{Path(nodeid.split('::')[0]).name}::{nodeid.split('::', 1)[-1]}"
        case_id = str(case["test_case_id"]) if case else test_ref
        if case_id in used_ids:  # e.g. one script with several parametrised tests
            case_id = test_ref
        used_ids.add(case_id)
        message, tb_tail = _failure_details(t)
        script_file = script_dir / Path(nodeid.split("::")[0]).name
        failures.append({
            "nodeid": nodeid,
            "test_case_id": case_id,
            "test_ref": test_ref,
            "s3_test_case": case,
            "error_message": message,
            "traceback_tail": tb_tail,
            "script_code": script_file.read_text(encoding="utf-8")[:3000] if script_file.exists() else None,
            "attempts": 1,  # S6 doesn't retry, so every test ran exactly once
            "passed_on_retry": False,
        })

    classifications = []
    if failures:
        payload = {
            "run_id": state["run_id"],
            "failed_tests": [{k: v for k, v in f.items() if k != "nodeid"} for f in failures],
            "confirmed_domain_rules": knowledge_store.get_confirmed_rules(),
            "flaky_history": "not available yet",
        }
        output = call_skill("S7_failure_classification.md", payload, max_tokens=16384)

        raw = output.get("classifications") if isinstance(output, dict) else None
        if raw is None and isinstance(output, dict) and "classification" in output:
            raw = [output]  # a bare single classification instead of the wrapper
        returned = {}
        for c in raw or []:
            if isinstance(c, dict) and c.get("test_case_id") is not None:
                returned.setdefault(str(c["test_case_id"]), c)

        # Never drop a failure, and never let a malformed answer stop the run:
        # anything S7 didn't classify cleanly becomes pending triage, visibly.
        for f in failures:
            c = returned.get(f["test_case_id"])
            problem = None
            if c is None:
                c, problem = {}, "S7 returned no classification for this test"
            label = str(c.get("classification", "")).strip().lower().replace("/", "_").replace(" ", "_").replace("-", "_")
            if label not in S7_CLASSIFICATIONS:
                problem = problem or f"S7 returned an unrecognised classification {c.get('classification')!r}"
                label = "unclassified_pending_triage"
            entry = {
                "nodeid": f["nodeid"],
                "test_case_id": f["test_case_id"],
                "classification": label,
                "evidence_trail": c.get("evidence_trail") or problem or "",
                "confidence": c.get("confidence"),
                "flaky_history_flag": bool(c.get("flaky_history_flag", False)),
            }
            if problem:
                entry["coerced_because"] = problem
            classifications.append(entry)

    (run_dir / "S7_classifications.json").write_text(
        json.dumps({
            "run_id": state["run_id"],
            "tests_run": len(pytest_report.get("tests", [])),
            "failed_test_count": len(failures),
            "classifications": classifications,
        }, indent=2),
        encoding="utf-8",
    )
    return {"s7_output": {"classifications": classifications}}


def s9_report(state: RunState) -> dict:
    correlation_id = state["correlation_id"]
    run_slug = state.get("run_slug")

    report_dir = allure_report_dir(correlation_id, run_slug)
    allure_gen = subprocess.run(
        ["allure", "generate", str(allure_results_dir(correlation_id, run_slug)), "-o", str(report_dir), "--clean"],
        capture_output=True,
        text=True,
    )
    allure_report_path = str(report_dir / "index.html") if allure_gen.returncode == 0 else None

    # S6's results, with each failed test's S7 classification attached, and
    # each test's layer (UI/API) taken from the S3 test case it implements.
    cases_by_stem = _s3_cases_by_stem(state)
    classifications = {
        c["nodeid"]: c for c in (state.get("s7_output") or {}).get("classifications", [])
    }
    results = []
    for r in state["s6_output"].get("results", []):
        r = dict(r)
        case = cases_by_stem.get(_script_stem(r.get("nodeid") or ""))
        if case and case.get("layer"):
            r["layer"] = case["layer"]
        c = classifications.get(r.get("nodeid"))
        if c:
            r["classification"] = c["classification"]
            r["classification_evidence"] = c["evidence_trail"]
        results.append(r)

    payload = {
        "classified_results": {**state["s6_output"], "results": results},
        "violations": [],  # no S8 yet
        "baseline": None,
    }
    output = call_skill("S9_reporting_aggregation.md", payload)
    output["allure_report_path"] = allure_report_path
    output["allure_generation_error"] = allure_gen.stderr if allure_gen.returncode != 0 else None

    return {"s9_output": output, "status": "complete"}
