# S8 — Security & Boundary Scan

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked:** Alongside S7, before H4
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Section 9 (Security & Data Boundaries) and Section 7 (Ambiguity & Escalation Protocol) for the fast-track routing below.

---

## 1. What this skill does

Checks every action S5 and S6 actually took — every write, every API call, every piece of data touched — against the prohibited-action rules in Section 9. This is the skill that catches a boundary violation after the fact if S5/S6 somehow let one through; it does not modify or block actions itself, it detects and escalates.

---

## 2. Required inputs

- The full action log from S5 (what the generated scripts do) and S6 (what actually executed)
- Current permission/scope configuration for the environment the run used

---

## 3. Required process

**Step 1 — Scan every write action** for any target outside the configured, least-privilege scope — most critically, any write that touches a production system.

**Step 2 — Scan every piece of data touched or logged** for unmasked PII — in evidence files, in logs, in captured screenshots or traces.

**Step 3 — Scan every API call** for scope beyond what's explicitly covered by the test's defined boundary — unscoped or wildcard calls, or calls to endpoints the test case didn't need.

**Step 4 — For every violation found, log it and route it immediately** — do not silently block or silently allow. A detected violation always surfaces, with full detail on what happened and where.

---

## 4. Output format

- `run_id`
- `violations` — list, each with: what was detected, which action/script/test it came from, severity, and immediate routing target
- `clean_confirmation` — explicit statement that no violations were found, if that's the case (silence is never used to imply "clean")

---

## 5. NOT permitted to

- Grant expanded scope to let an action complete — this skill detects, it never authorizes.
- Silently block an action without logging and escalating it.
- Downgrade or delay a detected violation's routing priority for any reason.

---

## 6. Escalation triggers (all of these fast-track — bypass normal queue priority, per Section 7)

- Any detected write to a production system.
- Any detected unmasked PII, anywhere in evidence, logs, or captured artifacts.
- Any action that requested or used scope beyond configured permissions.

These route immediately to the security/release owner, ahead of anything else in the escalation queue — this is the one place in the framework where a finding doesn't wait its turn.

---

*End of S8 skill.md*
