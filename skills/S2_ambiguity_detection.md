# S2 — Domain Context & Ambiguity Detection

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked between:** S1 (Input Normalization) and H1 (Requirement Sign-Off)
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Section 11 (Domain Knowledge Injection Protocol), which defines the tagging taxonomy this skill applies.

---

## 1. What this skill does

Takes S1's structured output and works out what's actually known versus assumed, what's ambiguous, what conflicts, and which layer(s) — UI, API, or both — each requirement touches. This is the skill that decides what a human needs to confirm at H1 before anything gets built against it. Getting this right matters more than any other skill in the pipeline: everything downstream trusts that FACT and DECISION tags mean what they say.

---

## 2. Required inputs

- S1's structured output
- The current confirmed Domain Knowledge Store entries for this project

---

## 3. Required process

**Step 1 — Break the requirement into individual, checkable statements.** "The system must reject discounts over 50% and log the attempt" is two statements, not one — tag each separately.

**Step 2 — Tag every statement:**
- **FACT** — explicitly stated in the source material, or matches a confirmed Domain Knowledge Store entry exactly.
- **ASSUMPTION** — plausible given the context, but not actually stated. Example: the requirement says "reject invalid discount codes" without defining "invalid" — assuming it means "over 50%" because that's a common pattern is an ASSUMPTION, not a FACT.
- **INFERENCE** — derived from a pattern seen elsewhere (another requirement, another project), not stated anywhere in this project's material.
- **DECISION** — a human has already explicitly resolved this exact point, and it's recorded in the Domain Knowledge Store.

**Step 3 — Identify the layer(s).** Tag each statement UI, API, or both, based on where it would actually be validated.

**Step 4 — Surface conflicts.** If two statements — within this requirement, or between this requirement and a confirmed Domain Knowledge Store entry — would produce different outcomes for the same scenario, flag it explicitly. Do not pick a side.

**Step 5 — Compile the escalation list.** Every ASSUMPTION and INFERENCE, and every conflict from Step 4, goes into the list a human resolves at H1. FACT and DECISION items don't need human confirmation — they're already grounded.

---

## 4. Output format

- `tagged_statements` — list of individual statements, each with its tag (FACT/ASSUMPTION/INFERENCE/DECISION) and layer (UI/API/both)
- `ambiguity_list` — every ASSUMPTION, INFERENCE, and conflict, with a plain-language description of what's unclear and why
- `confirmed_carryforward` — which Domain Knowledge Store entries this requirement relied on

---

## 5. NOT permitted to

- Tag something FACT because it seems obviously true. If it isn't stated and isn't already a confirmed DECISION, it is not a FACT, no matter how reasonable it sounds.
- Invent acceptance criteria not present or derivable from source material.
- Assume "standard" or "typical" business behavior for anything undocumented — that's exactly what ASSUMPTION and INFERENCE tags exist to catch, not bypass.
- Resolve a conflict itself. Conflicts are surfaced, never picked between.
- Let anything tagged ASSUMPTION or INFERENCE pass through to S3 without appearing in the escalation list for H1.

---

## 6. Escalation triggers

- Any statement with more than one plausible interpretation with materially different test outcomes.
- Any business rule referenced but not defined anywhere in confirmed material.
- Two confirmed sources (this requirement and the Domain Knowledge Store, or two parts of the same requirement) implying different outcomes for the same scenario.

---

## 7. Worked example

**Input from S1:** "The system must reject excessive discount codes and notify the finance team."

**Tagging:**
- "The system must reject discount codes" → **FACT** (explicitly stated)
- "excessive" defined as a specific threshold → **ASSUMPTION** (no number given anywhere in source)
- "notify the finance team" → **FACT**, but *how* (email? in-app? which address?) → **ASSUMPTION**

**Escalation list for H1:** "What threshold defines 'excessive'? What does 'notify' mean concretely — channel, recipient, timing?"

Nothing here gets guessed. Both go to a human before S3 ever sees this requirement.

---

*End of S2 skill.md*
