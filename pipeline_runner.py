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


def start_run(raw_requirement: str) -> str:
    """Starts S1 -> ... -> (H1 pause or further) on a background thread.
    Returns the run_id immediately; the caller polls get_status(run_id)."""
    initial_state = new_run_state(raw_requirement)
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
