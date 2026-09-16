# S3 — Test Case Generation

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation, no memory of prior calls
**Invoked between:** H1 (Requirement Sign-Off) and H2 (Test Case Review)
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Section 2 (Core Operating Principles) and Section 11 (Domain Knowledge Injection Protocol). This file adds only what is specific to test case generation — it does not restate rules that already apply to every skill.

---

## 1. What this skill does

Given a requirement that has already passed H1 sign-off, this skill produces test case specifications — not automation code, not executable scripts. It decides *what* needs to be proven and *what result would prove it*. S5 turns the output of this skill into actual Playwright scripts later.

Every test case this skill produces must answer, on its own, four questions a human reviewer at H2 will ask: Why does this test exist? Which confirmed requirement or rule does it come from? Is the expected result something we know, or something inferred? Could this same test already exist under different wording?

---

## 2. Required inputs (provided by the Orchestrator every call)

- The H1-confirmed requirement, with its FACT/DECISION-tagged breakdown from S2
- Confirmed Domain Knowledge Store entries relevant to this requirement
- Layer tagging from S2 (UI, API, or both)
- Any existing test cases already generated for this requirement or a related one (for duplicate-checking, Section 5 below)

If any of these is missing — most commonly, a requirement arriving without an H1 confirmation record — this skill does not proceed. It escalates per Section 6.

---

## 3. Required process

Work through these steps in order. Do not skip to generating test values before step 1 is done.

**Step 1 — State the obligation.** Before generating anything, write one sentence stating what this requirement obligates the system to do or prevent. Example: *"The system must reject any discount code greater than 50%."* If you cannot state this in one sentence from the confirmed requirement alone, the requirement is not specific enough to generate a test case from — escalate instead of guessing.

**Step 2 — Apply boundary value analysis (BVA) and equivalence partitioning (EP).** Identify the valid range, the boundary values, and the partitions implied by the obligation. For the discount example: 50% is the boundary; 49% and below is one equivalence partition (accept); 51% and above is another (reject); 50% itself needs its own explicit test since boundaries are where off-by-one errors live.

**Step 3 — Derive the expected result strictly from the confirmed requirement or domain rule — never from the application.** This is the single most important rule in this file: an expected result is only valid if it can be traced to the confirmed requirement text, a confirmed Domain Knowledge Store entry, or an explicit human DECISION. It is never valid to determine an expected result by predicting or assuming what the current application build does. If the confirmed requirement doesn't specify what should happen for a given input, that is a gap — escalate it, don't fill it in by guessing at current behavior.

**Step 4 — Check for duplicates before finalizing.** Compare the test case you're about to produce, by its underlying logic — the obligation, the input partition, and the expected result — against the existing test cases passed in as input. If a test covering the same logical condition already exists, do not create a new one with different wording just because the requirement was phrased differently this time. Reference the existing test case instead. Two test cases that check the same boundary with the same expected result are the same test, regardless of how each was worded.

**Step 5 — Assign traceability.** Every test case must carry a reference back to the exact requirement (or requirement fragment) and Domain Knowledge Store entry it came from. A test case with no traceable source does not get generated.

---

## 4. Output format

For every test case produced, output:

- `test_case_id` — unique within this run
- `source_requirement_id` — traces back to the H1-confirmed requirement
- `obligation` — the one-sentence statement from Step 1
- `test_type` — BVA or EP, and which partition/boundary it covers
- `layer` — UI, API, or both (inherited from S2's tagging)
- `input_values` — the specific input(s) this test case exercises
- `expected_result` — the outcome, stated precisely enough for S5 to write an assertion from it
- `expected_result_basis` — which requirement line, Domain Knowledge Store entry, or DECISION record the expected result was derived from (never "observed application behavior")
- `source_tags` — the FACT/ASSUMPTION/INFERENCE/DECISION tags inherited from S2 for the underlying requirement; only requirements tagged FACT or DECISION may reach this skill in the first place, so this is a record, not a new judgment call
- `duplicate_check` — either "new" or a reference to the existing test case ID it matches

---

## 5. NOT permitted to

- Generate a test case against a requirement that has not passed H1.
- Derive an expected result by predicting, assuming, or characterizing what the current application build does. If the only way to state an expected result is to imagine running the app and seeing what happens, that is not a valid expected result under this skill — it's a gap requiring human decision.
- Fabricate an expected value that cannot be traced to Step 5's source.
- Generate two test cases for the same logical condition because they arrived from differently worded parts of the requirement.
- Approve, finalize, or mark its own output as correct, complete, or release-ready. That judgment belongs to the human at H2.
- Silently drop a requirement it can't generate a test case for. Every requirement that reaches this skill either produces a test case or produces an escalation — never neither.

---

## 6. Escalation triggers

Return an escalation instead of a test case when:

- The requirement reaching this skill has no H1 confirmation record attached.
- The obligation (Step 1) cannot be stated in one sentence from confirmed material alone.
- The expected result for a boundary or partition cannot be derived without inference — i.e., the requirement is silent on what should happen for a specific case.
- Two confirmed requirements or Domain Knowledge Store entries would produce different expected results for what looks like the same scenario.
- The only way to determine an expected result would be to run the current build and use its behavior as the answer.

Every escalation follows the format defined in AGENT_INSTRUCTIONS.md Section 7 — what's blocked, why, what's already known, what's needed to unblock it.

---

## 7. Worked example

**Confirmed requirement (FACT-tagged, H1-passed):** "The system must reject a discount code greater than 50%."

**Step 1 — Obligation:** The system must reject any discount code input over 50% and accept any input of 50% or below.

**Step 2 — BVA/EP:** Boundary at 50%. Partitions: ≤50% (accept), >50% (reject).

**Step 3 — Expected results, from the requirement text directly:**
- 49% → accepted (within stated valid range)
- 50% → accepted (boundary explicitly included by "greater than 50%")
- 51% → rejected (explicitly stated)

**Output — three test cases**, each with its own `test_case_id`, all sharing `source_requirement_id` and `obligation`, each with `expected_result_basis` pointing at the same requirement sentence, none requiring inference because the requirement was explicit at every boundary.

If the requirement had instead said "the system must reject excessive discount codes" with no number given, Step 1 would fail — "excessive" isn't stated — and this skill would escalate for a human to confirm the actual threshold, rather than guessing 50% because that's a common value.

---

*End of S3 skill.md*
