# S11 — CI/CD Gate Adapter

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked:** After H5 (Release Sign-Off)
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Section 8 (Human-in-the-Loop Gates, H5).

---

## 1. What this skill does

The last step in the pipeline. Takes the human's H5 sign-off, applies the suite's configured pass/fail threshold, and pushes the resulting status to Jenkins/Git so the CI/CD pipeline can act on it. This skill makes no judgment calls — it applies a pre-configured rule to an already-made human decision.

---

## 2. Required inputs

- The H5 sign-off record from the Orchestrator (confirmation that a human has made the release decision)
- The suite's configured pass/fail threshold
- The target CI/CD endpoint

---

## 3. Required process

**Step 1 — Confirm an H5 sign-off record actually exists** for this run before doing anything else. No sign-off record, no push — this skill does not proceed on an assumption that H5 "probably" happened.

**Step 2 — Apply the configured threshold** to the run's results exactly as configured. Do not adjust it, round it, or apply a different default if the configured value seems off — that's a configuration issue to escalate, not something this skill corrects on its own.

**Step 3 — Push the resulting status** (pass/fail/blocked) to the target Jenkins/Git endpoint, with a link back to S10's release summary so anyone reviewing the CI/CD result can see the full factual picture, not just a status flag.

---

## 4. Output format

- `run_id`
- `threshold_applied`
- `status_pushed` — pass / fail / blocked
- `cicd_endpoint`, `push_timestamp`
- `linked_summary` — pointer to S10's output

---

## 5. NOT permitted to

- Apply any threshold other than the one configured at suite level.
- Push a status before an H5 sign-off record is confirmed to exist.
- Retry a failed push silently without logging that it happened.

---

## 6. Escalation triggers

- No pass/fail threshold is configured for this suite.
- The target CI/CD endpoint is unreachable.

---

*End of S11 skill.md*
