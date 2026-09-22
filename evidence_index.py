"""
Read-only aggregation over evidence/ for the Dashboard and Requirements
Library screens. Doesn't call an LLM, doesn't touch graph.py or nodes.py,
and never writes anything -- it only reads what S1/S3/S6/S7/S9 have already
written to disk per run, exactly as scoped.

One deliberate exception: a run's *final* status (did S9 actually produce
a report, or escalate?) has no dedicated file on disk to check -- S9's
output only ever lives in the LangGraph checkpoint, and adding a
results.json for it would mean touching nodes.py, which this task is
explicitly scoped not to do. So status is resolved via
pipeline_runner.get_status(), which itself only reads checkpoint state
(no pipeline invocation, no AI call) -- everything else here (pass/fail
counts, S7 breakdown, requirement title) comes from the evidence/ JSON
files, per the brief.
"""

import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from evidence_store import EVIDENCE_ROOT, make_slug
import pipeline_runner as pr
import knowledge_store

_CACHE_TTL_SECONDS = 3
_cache: dict = {"at": 0.0, "runs": []}

_SLUG_SUFFIX_RE = re.compile(r"^(.*)_([0-9a-f]{8})$")
_BARE_UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _run_id_from_folder(folder: Path) -> Optional[str]:
    """H1_review.json's own run_id field, since virtually every run
    reaches H1 and writes it; falls back to the folder name itself for
    the pre-slug legacy layout, where the folder name *is* the run_id."""
    review = _read_json(folder / "H1_review.json")
    run_id = review.get("run_id") if review else None
    if run_id:
        return run_id
    return folder.name if _BARE_UUID_RE.match(folder.name) else None


def _folder_slug(folder: Path, title: Optional[str]) -> Optional[str]:
    """The slug for grouping/title fallback. Read straight off the folder
    name for the current <slug>_<id8> layout. A folder from before slugs
    existed (a bare run_id) has no slug on disk to read -- derive one
    from its own title (the same make_slug() the pipeline itself uses)
    rather than a shared "legacy" placeholder, so unrelated old runs (a
    password-reset run and a search-API run, say) don't get grouped into
    one Requirements Library card just because both predate slugs."""
    m = _SLUG_SUFFIX_RE.match(folder.name)
    if m:
        return m.group(1)
    if _BARE_UUID_RE.match(folder.name):
        return make_slug(title) if title else None
    return None


def _pytest_counts(folder: Path) -> Optional[dict]:
    report = _read_json(folder / "pytest-report.json")
    if not report:
        return None
    summary = report.get("summary", {})
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0) + summary.get("error", 0)
    total = summary.get("total", passed + failed)
    return {"passed": passed, "failed": failed, "total": total}


def _layer_counts(test_cases: list) -> dict:
    counts = {"API": 0, "UI": 0, "Both": 0}
    for c in test_cases:
        if not isinstance(c, dict):
            continue
        layer = str(c.get("layer", "")).strip().lower()
        if layer == "api":
            counts["API"] += 1
        elif layer == "ui":
            counts["UI"] += 1
        elif layer == "both":
            counts["Both"] += 1
    return counts


def _classification_counts(folder: Path) -> Optional[dict]:
    s7 = _read_json(folder / "S7_classifications.json")
    if s7 is None:
        return None
    counts = {"app_bug": 0, "flaky": 0, "environment": 0, "automation_error": 0, "unclassified_pending_triage": 0}
    for c in s7.get("classifications", []):
        label = c.get("classification")
        if label in counts:
            counts[label] += 1
    return counts


def _requirement_title(folder: Path, run_id: Optional[str], slug: Optional[str]) -> str:
    if run_id:
        try:
            title = (pr._graph.get_state(pr._config(run_id)).values.get("s1_output") or {}).get("title_summary")
            if title:
                return title
        except Exception:
            pass
    if slug:
        return slug.replace("-", " ").title()
    return folder.name


def _one_run(folder: Path) -> Optional[dict]:
    if not folder.is_dir():
        return None
    run_id = _run_id_from_folder(folder)
    title = _requirement_title(folder, run_id, None)
    slug = _folder_slug(folder, title)

    live_status = pr.get_status(run_id) if run_id else {"status": "unknown_or_idle"}
    status = live_status["status"]

    counts = _pytest_counts(folder)
    pass_rate = round(100 * counts["passed"] / counts["total"], 1) if counts and counts["total"] else None
    test_cases = _read_json(folder / "test_cases.json")
    test_cases = test_cases.get("test_cases", test_cases) if isinstance(test_cases, dict) else (test_cases or [])

    return {
        "run_id": run_id,
        "run_ref": run_id[:8] if run_id else folder.name[:8],
        "slug": slug or f"unknown-{folder.name[:8]}",  # last resort: still don't merge unrelated runs
        "folder": folder.name,
        "title": title,
        "status": status,
        "counts": counts,
        "pass_rate": pass_rate,
        "layer_counts": _layer_counts(test_cases),
        "classification_counts": _classification_counts(folder),
        "mtime": folder.stat().st_mtime,
        "has_allure": (folder / "allure-report" / "index.html").exists(),
        "has_test_cases_xlsx": (folder / "test_cases.xlsx").exists(),
    }


def scan_runs(force: bool = False) -> list[dict]:
    """Every run folder under evidence/, newest first. Cached briefly
    (_CACHE_TTL_SECONDS) since a full scan re-reads several small JSON
    files per run -- cheap individually, but Dashboard/Library both call
    this on every request, and a laptop's filesystem doesn't need to be
    re-read every couple hundred milliseconds."""
    now = time.time()
    if not force and now - _cache["at"] < _CACHE_TTL_SECONDS:
        return _cache["runs"]

    runs = []
    if EVIDENCE_ROOT.is_dir():
        for folder in EVIDENCE_ROOT.iterdir():
            run = _one_run(folder)
            if run:
                runs.append(run)
    runs.sort(key=lambda r: r["mtime"], reverse=True)

    _cache["at"] = now
    _cache["runs"] = runs
    return runs


def dashboard_stats() -> dict:
    runs = scan_runs()
    scored = [r for r in runs if r["counts"]]

    total_passed = sum(r["counts"]["passed"] for r in scored)
    total_tests = sum(r["counts"]["total"] for r in scored)
    overall_pass_rate = round(100 * total_passed / total_tests, 1) if total_tests else None

    now = time.time()
    this_month = time.strftime("%Y-%m")
    runs_this_month = sum(1 for r in runs if time.strftime("%Y-%m", time.localtime(r["mtime"])) == this_month)

    layer_totals = {"API": 0, "UI": 0, "Both": 0}
    for r in runs:
        for k, v in r["layer_counts"].items():
            layer_totals[k] += v

    trend = [
        {"run_ref": r["run_ref"], "title": r["title"], "mtime": r["mtime"], "pass_rate": r["pass_rate"]}
        for r in reversed(scored)  # oldest first, for the trend line
    ][-12:]

    return {
        "overall_pass_rate": overall_pass_rate,
        "total_tests": total_tests,
        "runs_this_month": runs_this_month,
        "awaiting_review": sum(1 for r in runs if r["status"] == "paused_at_h1"),
        "confirmed_rules_active": len(knowledge_store.get_confirmed_rules()),
        "layer_totals": layer_totals,
        "trend": trend,
        "recent_runs": runs[:10],
    }


_FAILING_STATUSES = {"escalated", "failed", "rejected_at_h1"}


def _library_bucket(latest: dict) -> str:
    if latest["status"] == "paused_at_h1":
        return "needs_review"
    if latest["status"] in _FAILING_STATUSES:
        return "failing"
    if latest["pass_rate"] is not None:
        return "passing" if latest["pass_rate"] == 100 else "failing"
    return "in_progress"


def requirements_library() -> list[dict]:
    by_slug: dict[str, list[dict]] = defaultdict(list)
    for r in scan_runs():
        by_slug[r["slug"]].append(r)

    cards = []
    for slug, runs in by_slug.items():
        runs.sort(key=lambda r: r["mtime"], reverse=True)
        latest = runs[0]
        live = pr.get_status(latest["run_id"]) if latest["run_id"] else {}
        cards.append({
            "slug": slug,
            "title": latest["title"],
            "run_count": len(runs),
            "latest_run_ref": latest["run_ref"],
            "latest_run_id": latest["run_id"],
            "status": latest["status"],
            "bucket": _library_bucket(latest),
            "pass_rate": latest["pass_rate"],
            "counts": latest["counts"],
            "last_run_mtime": latest["mtime"],
            "escalation_reason": (live.get("escalation") or {}).get("reason"),
        })
    cards.sort(key=lambda c: c["last_run_mtime"], reverse=True)
    return cards


def knowledge_store_rows() -> list[dict]:
    """Every domain_rules row (confirmed and superseded), newest first --
    for the Knowledge Store page. Reads knowledge_store.DATABASE_URL
    directly rather than adding a new function to knowledge_store.py,
    since that module is off-limits for this task."""
    import psycopg
    with psycopg.connect(knowledge_store.DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT id, statement, status, confirmed_by_run_id, created_at "
            "FROM domain_rules ORDER BY id DESC"
        ).fetchall()
    return [
        {"id": r[0], "statement": r[1], "status": r[2], "confirmed_by_run_id": r[3], "created_at": r[4].isoformat()}
        for r in rows
    ]
