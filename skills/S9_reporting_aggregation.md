# S9 — Reporting & Aggregation

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked:** After S7/S8, before H4
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Section 5 (Reporting Obligations).

---

## 1. What this skill does

Takes S7's classified results and S8's violation log and turns them into trend data, stability metrics, and the human-readable report presented at H4. This skill reports facts — it does not draw conclusions about what should happen next.

---

## 2. Required inputs

- S7's classified results (only classified results — see Section 5 below)
- S8's violation log
- Historical baseline data for this suite, for trend comparison

---

## 3. Required process

**Step 1 — Aggregate by layer and by classification.** Pass/fail counts, broken down by UI vs. API, and by the four S7 categories plus anything still pending triage.

**Step 2 — Compare against baseline.** Identify which failures are new versus previously known, and flag any regression — a test that was passing in the last confirmed baseline and now fails — as its own distinct category, not folded into ordinary new-failure counts.

**Step 3 — Compute stability metrics** (e.g., flaky rate, pass-rate trend over recent runs) using only classified results. If a metric can't be computed because too many results are still unclassified, say so explicitly rather than computing it on partial data silently.

**Step 4 — Produce the human-readable summary**: pass/fail counts, classification breakdown, new-vs-known and regression callouts, S8 violation summary, links to evidence. This is what a human reads at H4 — it should be scannable without needing the raw logs.

---

## 4. Output format

- `run_id`
- `aggregate_metrics` — pass/fail/skip counts by layer and classification
- `trend_data` — comparison against baseline, stability metrics
- `new_vs_known_failures`, `regressions` — explicitly separated
- `human_readable_summary` — the report surfaced at H4
- `unclassified_note` — explicit statement of what couldn't be computed and why, if applicable

---

## 5. NOT permitted to

- Include an unclassified failure in any pass-rate, stability, or trend metric.
- Smooth over, omit, or downplay a newly introduced failure to make a trend look more favorable.
- Silently compute a metric on incomplete data without disclosing that it's incomplete.
- Phrase the summary in a way that implies a release recommendation — that's S10's boundary to respect, and this skill shouldn't drift toward it either.

---

## 6. Escalation triggers

- A required metric cannot be computed because the underlying results are unclassified.
- A statistically meaningful regression against baseline is detected.

---

*End of S9 skill.md*
