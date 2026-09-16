# S7 — Failure Classification & Flaky Analysis

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked:** After S6, alongside S8, before H4
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Sections 5 (Reporting Obligations) and 10 (Failure Handling & Retry Logic).

---

## 1. What this skill does

Looks at every failure S6 produced and decides which of four buckets it belongs to — app bug, flaky, environment, or automation error — before it's allowed to count toward any metric. No failure reaches S9's trend data unclassified.

---

## 2. Required inputs

- S6's results and evidence for the run
- Retry history from S6 (which tests failed then passed on retry, and how many attempts)
- Prior flaky classification history for the same tests, if available

---

## 3. Required process

**Step 1 — For every failure, gather the evidence:** what was expected (from the originating S3 test case), what actually happened (from S6's captured evidence), and whether it passed on any retry.

**Step 2 — Apply the classification taxonomy:**
- **App bug** — application behavior contradicts the confirmed requirement the test was built from.
- **Flaky** — only applies if the test failed and then passed within the configured retry window, *and* investigation supports non-determinism (e.g., timing-sensitive, no clear application fault). A pass-on-retry alone is not sufficient — investigate before assigning this label.
- **Environment** — the failure traces to infrastructure, network, or environment conditions unrelated to the application or the test logic itself.
- **Automation error** — the test case or the automation code itself is wrong (e.g., a broken locator, an incorrect assertion left over from a stale requirement).

**Step 3 — If reproduction is inconclusive**, do not force a classification. Use "unclassified/pending triage" and escalate rather than guessing at the most likely bucket.

**Step 4 — Check flaky history.** If a test has now been classified flaky three or more times recently, escalate it regardless of this run's outcome — repeated flakiness usually means a real problem, not noise.

---

## 4. Output format

- `test_case_id`, `run_id`
- `classification` — one of the four categories, or "unclassified/pending triage"
- `evidence_trail` — what was compared to reach this classification
- `confidence` — clear, or noted as inconclusive if reproduction didn't settle it
- `flaky_history_flag` — set if this test has hit the three-strikes threshold

---

## 5. NOT permitted to

- Reclassify a failure as flaky solely because a retry passed, without applying the reproduction criteria in Step 2.
- Delete, suppress, or overwrite the original failure evidence during investigation.
- Force a classification into one of the four buckets when reproduction is genuinely inconclusive — use the pending-triage bucket instead.
- Let an unclassified failure flow into S9's metrics under any label.

---

## 6. Escalation triggers

- Reproduction remains inconclusive after the maximum configured investigation attempts.
- A test has been classified flaky three or more times in recent history.

---

*End of S7 skill.md*
