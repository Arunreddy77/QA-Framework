# S1 — Input Normalization

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked:** First stage of every run, before S2
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md.

---

## 1. What this skill does

Takes whatever a requirement arrives as — a BRD, a Jira ticket export, a user story, raw acceptance criteria, a test scenario document, a pasted paragraph — and converts it into one standard internal structure that every downstream skill can rely on, regardless of what project or format it came from. This skill does not judge, interpret, or improve the content. It reshapes it.

---

## 2. Required inputs

- The raw input, in whatever format it arrived (structured document, ticket JSON/API payload, plain text)
- The source type, if known (BRD, Jira ticket, user story, acceptance criteria, other)

---

## 3. Required process

**Step 1 — Identify structure.** Find the natural sections in the input: title/summary, description, acceptance criteria, business rules, out-of-scope notes, attachments referenced. Not every input has all of these — that's expected, not an error.

**Step 2 — Map to the standard internal representation** without changing wording, meaning, or emphasis. This is a structural transform, not a summary. If the source says three things, the output says the same three things, just organized.

**Step 3 — Flag anything that doesn't fit.** If part of the input can't be mapped to any known section (e.g., an embedded image with no caption, a table with unclear column meaning), carry it forward as an "unstructured fragment" rather than dropping it or guessing at its meaning.

---

## 4. Output format

- `source_type` — BRD / Jira ticket / user story / acceptance criteria / other
- `title_summary`
- `description` — verbatim, restructured only
- `acceptance_criteria` — list, verbatim
- `business_rules_referenced` — anything the source alludes to but doesn't define (feeds S2's ambiguity detection directly)
- `unstructured_fragments` — anything that couldn't be mapped, carried forward rather than dropped
- `original_source_reference` — pointer back to the raw input, for traceability

---

## 5. NOT permitted to

- Paraphrase, summarize, or reword content during normalization. Structure only — meaning must stay identical.
- Add content not present in the source (e.g., inferring a missing acceptance criterion because it seems obvious).
- Drop content that doesn't fit cleanly into the standard structure. Everything gets carried forward, even the parts that don't fit.
- Resolve any ambiguity itself. That's S2's job — this skill's output should preserve ambiguity for S2 to find, not quietly clean it up.

---

## 6. Escalation triggers

- The input is unparseable (corrupted, empty, or in a format with no recognizable structure at all).
- The input is missing a section every downstream skill needs to function — most critically, no discernible description or acceptance criteria of any kind.

---

*End of S1 skill.md*
