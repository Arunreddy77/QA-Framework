"""
Everything app.py needs to drive the existing pipeline (graph.py / nodes.py /
run.py / resume.py) from HTTP requests instead of a terminal. Nothing in
graph.py, nodes.py, llm_gateway.py, or the skill files is touched or
duplicated here -- this only wraps them:

- run.handle_result and evidence_store's path functions are imported and
  reused as-is, so a UI-triggered run writes the exact same H1_review.json /
  H1_decision.json / evidence layout a terminal run does.
- graph.invoke()/Command(resume=...) are the same calls run.py and resume.py
  make -- just started on a background thread so the HTTP request that
  triggers them can return immediately.

The graph + checkpointer are built once at import time and reused for every
run. PostgresSaver takes its own lock around DB access (see its __init__),
so it's designed for exactly this: many threads sharing one checkpointer.
"""

import json
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from langgraph.types import Command

from graph import build_graph
from state import new_run_state, RunState
from llm_gateway import PROVIDER, MODEL
from llm_gateway import SkillEscalation
from evidence_store import EVIDENCE_ROOT, find_run_dir, run_evidence_dir
from run import handle_result
import knowledge_store

# Order matters: it's the order steps actually run in graph.py, and it's
# what lets the status endpoint say "which step is it on" from nothing but
# which output keys are present in the checkpoint.
PIPELINE_STEPS = [
    ("s1_normalize", "S1: Normalize requirement", "s1_output"),
    ("s2_ambiguity_detection", "S2: Ambiguity detection", "s2_output"),
    ("h1_gate", "H1: Human review", "h1_decision"),
    ("s3_generate_test_cases", "S3: Generate test cases", "s3_output"),
    ("s5_generate_scripts", "S5: Generate scripts", "s5_output"),
    ("s6_execute", "S6: Execute tests", "s6_output"),
    ("s7_classify_failures", "S7: Classify failures", "s7_output"),
    ("s9_report", "S9: Report", "s9_output"),
]

_graph, _checkpointer = build_graph()

# run_id -> {"thread": Thread, "phase": "starting"|"running"|"done", "error": str|None}
# This is what tells the status endpoint the run is *actively* working right
# now (as opposed to sitting paused at H1, which the checkpoint alone can't
# tell apart from "server restarted and lost track of it").
_REGISTRY: dict[str, dict] = {}
_REGISTRY_LOCK = threading.Lock()


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _set(run_id: str, **kw) -> None:
    with _REGISTRY_LOCK:
        _REGISTRY.setdefault(run_id, {}).update(kw)


def _get_registry(run_id: str) -> dict:
    with _REGISTRY_LOCK:
        return dict(_REGISTRY.get(run_id, {}))


def _run_in_background(run_id: str, invoke) -> None:
    """Shared by start_run and submit_h1_decision: run `invoke()` (a
    graph.invoke(...) call) on a thread, recording what happened so the
    status endpoint has something to report even for a run the process
    didn't watch the whole time."""
    def target():
        _set(run_id, phase="running", error=None)
        try:
            result = invoke()
            handle_result(result, run_id)  # writes H1_review.json/H1_decision.json, same as run.py/resume.py
            _set(run_id, phase="done")
        except SkillEscalation as e:
            _set(run_id, phase="done", escalation=e.payload)
        except Exception as e:
            _set(run_id, phase="done", error=f"{e}\n{traceback.format_exc()}")

    t = threading.Thread(target=target, daemon=True)
    _set(run_id, thread=t, phase="starting", error=None, escalation=None)
    t.start()


def start_run(raw_requirement: str, headed: Optional[bool] = None, slow_mo_ms: Optional[int] = None) -> str:
    """Starts S1 -> ... -> (H1 pause or further) on a background thread.
    Returns the run_id immediately; the caller polls get_status(run_id).
    headed/slow_mo_ms fall back to the S6_HEADED/S6_SLOW_MO_MS env vars
    when not given (see state.new_run_state) -- passing them here is what
    lets the Submit screen request a visible browser per run."""
    initial_state = new_run_state(raw_requirement, headed=headed, slow_mo_ms=slow_mo_ms)
    run_id = initial_state["run_id"]
    _run_in_background(run_id, lambda: _graph.invoke(initial_state, config=_config(run_id)))
    return run_id


def _dedupe_against_knowledge_store(new_rules: list[str]) -> list[str]:
    """Drops any rule that's already an active (confirmed) row in the
    knowledge store, so approving through the UI can't recreate the
    duplicate rows a repeated H1 approval caused earlier in this project.
    Comparison is exact-text, same as how the duplicates actually happened
    (the same wording submitted twice)."""
    existing = set(knowledge_store.get_confirmed_rules())
    return [r for r in new_rules if r not in existing]


def submit_h1_decision(run_id: str, approved: bool, new_confirmed_rules: list[str], notes: str) -> None:
    """Resumes a run paused at H1, same as resume.py -- on a background
    thread. Filters new_confirmed_rules against the knowledge store first
    (see _dedupe_against_knowledge_store)."""
    decision = {
        "approved": approved,
        "new_confirmed_rules": _dedupe_against_knowledge_store(new_confirmed_rules) if approved else [],
        "notes": notes,
    }
    run_dir = run_evidence_dir(run_id, get_run_slug(run_id))
    (run_dir / "H1_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    _run_in_background(run_id, lambda: _graph.invoke(Command(resume=decision), config=_config(run_id)))


def retry_run(run_id: str) -> None:
    """
    Re-runs a failed/escalated run from its last good checkpoint -- the UI
    equivalent of running `python resume.py <run_id>` again after a
    mid-pipeline crash, which is how every transient failure in this
    project (a free-tier model occasionally returning malformed JSON) has
    actually been recovered from. Reuses the same Command(resume=...) call
    resume.py makes: LangGraph only actually consumes that value if a gate
    is currently interrupted, so re-sending the run's last H1 decision is
    safe whether or not S3/S5/etc is what actually needs retrying.
    """
    status = get_status(run_id)
    # unknown_or_idle included: that's what a run stuck mid-step looks like
    # after a server restart wipes the in-memory registry -- exactly the
    # case retry needs to cover, not just a failure seen live.
    if status["status"] not in ("failed", "escalated", "unknown_or_idle"):
        raise ValueError(f"Run {run_id} is '{status['status']}' -- nothing to retry.")
    values = _graph.get_state(_config(run_id)).values
    decision = values.get("h1_decision") or {"approved": True, "new_confirmed_rules": [], "notes": ""}
    _run_in_background(run_id, lambda: _graph.invoke(Command(resume=decision), config=_config(run_id)))


def get_run_slug(run_id: str) -> Optional[str]:
    values = _graph.get_state(_config(run_id)).values
    return values.get("run_slug")


def _is_paused_at_h1(run_id: str) -> bool:
    snapshot = _graph.get_state(_config(run_id))
    return any(getattr(task, "interrupts", None) for task in snapshot.tasks)


def get_status(run_id: str) -> dict:
    """
    Reconstructed from two sources: the checkpoint (durable -- survives a
    server restart) tells us which steps have finished; the in-memory
    registry (this process only) tells us whether something is actively
    running right now versus just sitting paused. A run started before this
    server process's current lifetime shows up as its last completed step
    with status "unknown_or_idle" instead of "running", since we genuinely
    don't know without the registry.
    """
    snapshot = _graph.get_state(_config(run_id))
    values = snapshot.values
    if not values:
        return {"run_id": run_id, "status": "not_found"}

    reg = _get_registry(run_id)
    completed = [label for _, label, key in PIPELINE_STEPS if values.get(key)]
    run_status = values.get("status")  # "running" | "rejected_at_h1" | "complete" set by nodes.py

    if values.get("s9_output"):
        status = "complete"
    elif run_status == "rejected_at_h1":
        status = "rejected_at_h1"
    elif reg.get("escalation"):
        status = "escalated"
    elif reg.get("error"):
        status = "failed"
    elif _is_paused_at_h1(run_id):
        status = "paused_at_h1"
    elif reg.get("phase") in ("starting", "running"):
        status = "running"
    else:
        status = "unknown_or_idle"  # e.g. server restarted mid-run; not paused, not marked running here

    return {
        "run_id": run_id,
        "status": status,
        "run_slug": values.get("run_slug"),
        "provider": PROVIDER,
        "model": MODEL,
        "steps_completed": completed,
        "current_step": (PIPELINE_STEPS[len(completed)][1] if status == "running" and len(completed) < len(PIPELINE_STEPS) else None),
        "error": reg.get("error"),
        "escalation": reg.get("escalation"),
    }


def get_h1_payload(run_id: str) -> Optional[dict]:
    """The same payload H1_review.json holds -- tagged_statements and
    ambiguity_list -- read straight from the checkpoint so it's available
    the instant the run pauses, no file read required."""
    values = _graph.get_state(_config(run_id)).values
    s2 = values.get("s2_output") or {}
    if not s2 or not _is_paused_at_h1(run_id):
        return None
    return {
        "run_id": run_id,
        "tagged_statements": s2.get("tagged_statements", []),
        "ambiguity_list": s2.get("ambiguity_list", []),
    }


def _evidence_url(path: Optional[str]) -> Optional[str]:
    """Absolute filesystem path under evidence/ -> the /evidence/... URL
    app.py serves it at. Anything outside evidence/ (shouldn't happen, but
    e.g. allure_report_path is None on a generation failure) passes through
    as None instead of a broken link."""
    if not path:
        return None
    try:
        rel = Path(path).relative_to(EVIDENCE_ROOT)
    except ValueError:
        return None
    return f"/evidence/{rel.as_posix()}"


# The 5 valid values in a normalized classification, in the display order the
# Run Report screen's breakdown bar chart uses. Matches S7_CLASSIFICATIONS.
CLASSIFICATION_ORDER = ["app_bug", "flaky", "environment", "automation_error", "unclassified_pending_triage"]


def _classification_breakdown(values: dict) -> dict:
    """Counts per classification, computed straight from S7's own
    normalized output (nodes.s7_classify_failures already coerces every
    label to one of CLASSIFICATION_ORDER -- see its docstring), not from
    S9's free-form aggregate_metrics.by_classification. S9's version is
    restated in whatever key phrasing the model chooses that call ("App
    bug", "Unclassified/pending triage", ...) and isn't guaranteed to even
    agree with S7's own verdict for the same test, since it's a separate
    LLM call summarizing S6+S7's results in prose-adjacent JSON rather
    than just echoing S7's structured labels back."""
    counts = {k: 0 for k in CLASSIFICATION_ORDER}
    for c in (values.get("s7_output") or {}).get("classifications", []):
        label = c.get("classification")
        if label in counts:
            counts[label] += 1
    return counts


def _test_counts(run_dir: Optional[Path]) -> Optional[dict]:
    """Pass/fail/total straight from pytest-json-report's own summary
    block, which pytest writes deterministically -- not from S9's
    aggregate_metrics.by_layer, whose key names have varied between runs
    ("pass"/"fail"/"skip" vs "passed"/"failed"/"skipped"/"total"; see
    _classification_breakdown's docstring for the same class of issue).
    Trust the deterministic file over the model's restatement of it."""
    if not run_dir:
        return None
    import json as _json
    try:
        report = _json.loads((run_dir / "pytest-report.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, _json.JSONDecodeError):
        return None
    summary = report.get("summary", {})
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0) + summary.get("error", 0)
    return {"passed": passed, "failed": failed, "total": summary.get("total", passed + failed)}


def get_results(run_id: str) -> Optional[dict]:
    values = _graph.get_state(_config(run_id)).values
    if not values.get("s9_output"):
        return None

    run_dir = find_run_dir(run_id)
    scripts = sorted(p.name for p in (run_dir / "scripts").glob("*.py")) if run_dir and (run_dir / "scripts").exists() else []
    s9 = values["s9_output"]

    return {
        "run_id": run_id,
        "run_slug": values.get("run_slug"),
        "summary": s9.get("human_readable_summary"),
        "aggregate_metrics": s9.get("aggregate_metrics"),
        "test_counts": _test_counts(run_dir),
        "classification_breakdown": _classification_breakdown(values),
        "unclassified_note": s9.get("unclassified_note"),
        "allure_report_url": _evidence_url(s9.get("allure_report_path")),
        "test_cases_json_url": _evidence_url(str(run_dir / "test_cases.json")) if run_dir and (run_dir / "test_cases.json").exists() else None,
        "test_cases_xlsx_url": _evidence_url(str(run_dir / "test_cases.xlsx")) if run_dir and (run_dir / "test_cases.xlsx").exists() else None,
        "scripts": [{"name": name, "url": _evidence_url(str(run_dir / "scripts" / name))} for name in scripts],
    }


def list_runs() -> list[dict]:
    """Every run this server process has started or resumed, most recent
    first -- for a simple history list on the page. Only knows about runs
    from this process's lifetime (the registry), not ones from a previous
    server run or the terminal."""
    with _REGISTRY_LOCK:
        ids = list(_REGISTRY.keys())
    out = []
    for run_id in ids:
        s = get_status(run_id)
        values = _graph.get_state(_config(run_id)).values
        out.append({**s, "title": (values.get("s1_output") or {}).get("title_summary")})
    return out


def get_activity_log(run_id: str) -> list[dict]:
    """One entry per completed step, oldest first, with a real wall-clock
    timestamp -- for the Pipeline Status screen's activity log. Built from
    LangGraph's own checkpoint history (each checkpoint records when it was
    written), not tracked separately."""
    history = list(_graph.get_state_history(_config(run_id)))
    if not history:
        return []

    step_names = {key: label for _, label, key in PIPELINE_STEPS}
    entries = []
    seen = set()
    for snapshot in reversed(history):  # oldest first
        for key, label in step_names.items():
            if key in snapshot.values and snapshot.values[key] and key not in seen:
                seen.add(key)
                entries.append({"at": snapshot.created_at, "step": label})
    return entries


def _sanitized_id(test_case_id) -> str:
    """The same substitution s6_execute applies to build each script's
    filename (test_TC-API-1 -> test_TC_API_1.py) -- reproduced here so a
    test case can be joined back to its S6 result/S7 classification by the
    same key both were filed under. Without this, a test_case_id with any
    non-alphanumeric character (a hyphen is the common case) never matches
    its own result, and every row silently shows as "not run" even when it
    actually passed."""
    import re as _re
    return _re.sub(r"[^a-zA-Z0-9_]", "_", str(test_case_id))


def _synthesize_actual_result(result: Optional[dict], classification: Optional[dict]) -> str:
    """S3 never produces an 'actual result' -- it runs before anything
    executes. This assembles one from what actually happened: S6's real
    pass/fail outcome, plus S7's classification+reasoning on a failure.
    "Pending" before S6 has run at all, never blank."""
    if result is None:
        return "Pending — not yet executed"
    status = result.get("status")
    duration = result.get("duration_seconds")
    duration_note = f" in {duration:.1f}s" if isinstance(duration, (int, float)) else ""
    if status == "passed":
        return f"Passed{duration_note}"
    if status in ("failed", "error"):
        label = (classification or {}).get("classification")
        label_note = f" [{label}]" if label else ""
        reason = (classification or {}).get("evidence_trail")
        return f"Failed{duration_note}{label_note} — {reason}" if reason else f"Failed{duration_note}{label_note}"
    return f"{status or 'unknown'}{duration_note}"


def _test_case_rows(run_dir: Path, run_id: str) -> list[dict]:
    """One row per S3 test case, joined with its S6 pass/fail result
    (including its screenshot and log, captured on every test now, not
    just failures) and S7 classification+reasoning where they exist --
    what the Run Report screen's table, script viewer, and failure-detail
    panel need. Reads test_cases.json (S3's raw output) and the live
    checkpoint's s6_output/s7_output."""
    import json as _json

    test_cases_path = run_dir / "test_cases.json"
    if not test_cases_path.exists():
        return []
    raw = _json.loads(test_cases_path.read_text(encoding="utf-8"))
    cases = raw.get("test_cases", raw) if isinstance(raw, dict) else list(raw or [])

    values = _graph.get_state(_config(run_id)).values
    results_by_stem = {}
    for r in (values.get("s6_output") or {}).get("results", []):
        stem = _script_stem_safe(r.get("nodeid") or "")
        if stem:
            results_by_stem[stem] = r
    classifications_by_stem = {}
    for c in (values.get("s7_output") or {}).get("classifications", []):
        stem = _script_stem_safe(c.get("nodeid") or "")
        if stem:
            classifications_by_stem[stem] = c

    rows = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        stem = _sanitized_id(case.get("test_case_id", ""))
        result = results_by_stem.get(stem)
        classification = classifications_by_stem.get(stem)
        rows.append({
            "test_case_id": case.get("test_case_id"),
            "title": case.get("title"),
            "pre_requisite": case.get("pre_requisite"),
            "steps": case.get("steps"),
            "obligation": case.get("obligation"),
            "test_type": case.get("test_type"),
            "layer": case.get("layer"),
            "expected_result": case.get("expected_result"),
            "actual_result": _synthesize_actual_result(result, classification),
            "status": (result or {}).get("status", "not_run"),
            "duration_seconds": (result or {}).get("duration_seconds"),
            "classification": (classification or {}).get("classification"),
            "classification_reasoning": (classification or {}).get("evidence_trail"),
            "screenshot_url": _evidence_url(str(run_dir / result["screenshot_path"])) if result and result.get("screenshot_path") else None,
            "log_url": _evidence_url(str(run_dir / result["log_path"])) if result and result.get("log_path") else None,
            "script_url": _evidence_url(str(run_dir / "scripts" / f"test_{stem}.py")),
        })
    return rows


def _script_stem_safe(nodeid: str) -> Optional[str]:
    if not nodeid:
        return None
    stem = Path(nodeid.split("::")[0]).stem
    return stem[len("test_"):] if stem.startswith("test_") else stem


def get_report(run_id: str) -> Optional[dict]:
    """Everything the Run Report screen needs in one call: the results
    summary (see get_results), the per-test-case table joined with S7's
    classification+reasoning, and the pipeline timeline."""
    results = get_results(run_id)
    if results is None:
        return None
    run_dir = find_run_dir(run_id)
    return {
        **results,
        "test_cases": _test_case_rows(run_dir, run_id) if run_dir else [],
        "timeline": get_activity_log(run_id),
    }
