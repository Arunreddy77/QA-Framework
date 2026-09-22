# S6 — Execution Orchestration

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked between:** H3 (Script/Code Review) and S7/S8
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Sections 3 (Execution Environment Rules) and 4 (Evidence Capture Requirements).

**Note on naming:** this skill produces execution results — it is not the Orchestrator itself. The Orchestrator is the deterministic code that calls this skill and every other one; this skill is what actually runs the suite when called.

---

## 1. What this skill does

Runs H3-approved automation scripts via Playwright MCP, under the environment and evidence rules already locked in Sections 3–4, and hands off correlation-ID-tagged results and evidence to S7 and S8.

---

## 2. Required inputs

- H3-approved automation scripts from S5
- Environment configuration (viewport, timeout ceilings, browser matrix, pinned versions)
- Retry and parallelization limits, as configured at suite level

---

## 3. Required process

**Step 1 — Confirm environment pinning before running anything.** Browser version, OS, runtime, target app build, API schema version must all match what's recorded as pinned for this suite. If anything has drifted, halt and escalate before running — don't run against a drifted environment and flag it after.

**Step 2 — Execute scripts per their configured mode** (headless by default; headed -- a real, visible browser window, with an optional slow-motion delay between actions -- only when explicitly requested per run, e.g. for a HITL debugging session), respecting the per-action and per-suite timeout ceilings already configured. Never extend a timeout mid-run to avoid a failure.

**Step 3 — Generate one correlation ID per test run**, attached to all UI evidence and API logs produced during that run, so a human can reconstruct the full picture of a single execution without manually cross-referencing timestamps.

**Step 4 — Capture evidence exactly per Section 4** — full logs and results always; on failure, screenshots/video/trace/HAR for UI, full request/response pairs for API; checkpoint screenshots at every intent-verification moment regardless of pass/fail.

**Step 5 — Apply retries within the configured limit only.** A test that fails all configured attempts is reported as a genuine failure — retries never erase or downgrade that original record.

---

## 4. Output format

- `run_id`, `correlation_id`
- `results` — per test, pass/fail/skip, with the `script_id` and `test_case_id` it traces back to
- `evidence_manifest` — pointers to all captured artifacts for this run, by test
- `environment_metadata` — the actual pinned values used for this run
- `retry_log` — attempts per test, if any

---

## 5. NOT permitted to

- Retry beyond the configured limit without flagging it.
- Change timeouts, parallelization, or environment settings mid-run.
- Discard, overwrite, or truncate any run's evidence — every run writes to a new, timestamped, correlation-ID-scoped path.
- Run against a drifted environment without halting and escalating first.
- Suppress a failure or omit it from the results because it looks like it might be flaky — that judgment belongs to S7, not this skill.

---

## 6. Escalation triggers

- No configured ceiling exists for a suite-level timeout.
- Environment drift detected against the pinned configuration.
- Evidence capture fails for any reason (e.g., storage unreachable, screenshot capture fails).

---

*End of S6 skill.md*
