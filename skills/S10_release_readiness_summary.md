# S10 — Release Readiness Summary

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked between:** H4 (Execution & Stability Review) and H5 (Release Sign-Off)
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Section 8 (Human-in-the-Loop Gates, H5).

---

## 1. What this skill does

Produces the single factual document a human uses to make the release decision at H5. This is the most consequential output in the entire pipeline in terms of what it's *not* allowed to do: it presents facts, and only facts. It never tells anyone whether to ship.

---

## 2. Required inputs

- S9's aggregated reports and trend data
- S8's violation log
- The release baseline for comparison

---

## 3. Required process

**Step 1 — Pull together the complete factual picture**: pass/fail counts, every outstanding app-bug classification (not just a count — enough detail that a human can judge severity), every S8 violation, and comparison against the release baseline.

**Step 2 — State facts, not judgments.** Write "12 app-bug classified failures, 3 of which are new since the last baseline" — not "release looks risky" or "recommend holding." The line between the two is easy to blur under pressure to be helpful; hold it anyway.

**Step 3 — Surface anything incomplete.** If required data isn't available yet (e.g., S9 flagged an unclassified-metric gap), state that plainly rather than presenting an artificially complete-looking summary.

**Step 4 — Make evidence one click away**, not buried. Every fact in the summary should link to the evidence that supports it.

---

## 4. Output format

- `run_id`
- `pass_fail_summary` — by layer and classification
- `outstanding_app_bugs` — full list with severity context, not just a count
- `security_violations` — from S8, in full
- `baseline_comparison` — new vs. known vs. regression
- `data_completeness_note` — explicit flag if anything required is missing
- `evidence_links` — for every claim made above

---

## 5. NOT permitted to

- Phrase any part of the output as a go/no-go recommendation, or use language that leans toward one ("looks ready," "should be fine," "risky to proceed"). State the facts; let the human at H5 draw the conclusion.
- Omit or soften an outstanding app-bug or security violation to present a cleaner picture.
- Present a summary as complete when required underlying data is actually missing.

---

## 6. Escalation triggers

- Required data for the summary (from S9 or S8) is missing or incomplete at the point H5 is reached.

---

*End of S10 skill.md*
