"""
Local web UI for the QA framework -- wraps graph.py/nodes.py via
pipeline_runner.py, doesn't modify them. Single laptop, single user, no
login: binds to 127.0.0.1 only.

Run: ./.venv/bin/python app.py
Open: http://127.0.0.1:8000
"""

import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()  # must run before importing pipeline_runner -> graph.py, which reads env vars at import time

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import pipeline_runner as pr
import evidence_index as ei
from evidence_store import EVIDENCE_ROOT

app = FastAPI(title="QA Framework")


class NewRun(BaseModel):
    requirement: str
    headed: Optional[bool] = None  # None -> falls back to the S6_HEADED env var
    slow_mo_ms: Optional[int] = None  # None -> falls back to S6_SLOW_MO_MS


class H1Decision(BaseModel):
    approved: bool
    new_confirmed_rules: list[str] = []
    notes: str = ""


@app.post("/runs")
def create_run(body: NewRun):
    if not body.requirement.strip():
        raise HTTPException(400, "Requirement text is empty.")
    return {"run_id": pr.start_run(body.requirement, headed=body.headed, slow_mo_ms=body.slow_mo_ms)}


@app.get("/runs")
def runs():
    return pr.list_runs()


@app.get("/runs/{run_id}/status")
def run_status(run_id: str):
    status = pr.get_status(run_id)
    if status["status"] == "not_found":
        raise HTTPException(404, f"No run found with id {run_id}.")
    return status


@app.get("/runs/{run_id}/h1")
def run_h1(run_id: str):
    payload = pr.get_h1_payload(run_id)
    if payload is None:
        raise HTTPException(404, "This run isn't paused at H1 (either it hasn't reached H1 yet, or it's past it).")
    return payload


@app.post("/runs/{run_id}/h1/decision")
def run_h1_decision(run_id: str, decision: H1Decision):
    if pr.get_h1_payload(run_id) is None:
        raise HTTPException(409, "This run isn't paused at H1 right now.")
    pr.submit_h1_decision(run_id, decision.approved, decision.new_confirmed_rules, decision.notes)
    return {"ok": True}


@app.post("/runs/{run_id}/retry")
def run_retry(run_id: str):
    try:
        pr.retry_run(run_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.get("/runs/{run_id}/results")
def run_results(run_id: str):
    results = pr.get_results(run_id)
    if results is None:
        raise HTTPException(404, "This run hasn't completed yet.")
    return results


@app.get("/runs/{run_id}/activity")
def run_activity(run_id: str):
    if pr.get_status(run_id)["status"] == "not_found":
        raise HTTPException(404, f"No run found with id {run_id}.")
    return pr.get_activity_log(run_id)


@app.get("/runs/{run_id}/report")
def run_report(run_id: str):
    report = pr.get_report(run_id)
    if report is None:
        raise HTTPException(404, "This run hasn't completed yet.")
    return report


@app.get("/runs/{run_id}/scripts")
def run_scripts(run_id: str):
    results = pr.get_results(run_id)
    if results is None:
        raise HTTPException(404, "This run hasn't completed yet.")
    return results["scripts"]


@app.get("/dashboard")
def dashboard():
    return ei.dashboard_stats()


@app.get("/requirements")
def requirements():
    return ei.requirements_library()


@app.get("/knowledge-store")
def knowledge_store_route():
    return ei.knowledge_store_rows()


# The evidence folder itself -- scripts, the Allure report, test_cases.xlsx/.json --
# served as plain static files so the page can link straight to them.
EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=str(EVIDENCE_ROOT)), name="evidence")

# The page files themselves (style.css, lib.js, dashboard.html, etc.) -- kept at
# /static/... so they don't collide with the JSON data routes above (GET /dashboard
# is the aggregate-stats API; the Dashboard *page* is /static/dashboard.html).
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
