# S4 — Test Data Generation & Masking

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked:** Alongside S3, before H2 (Test Case Review)
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Section 9 (Security & Data Boundaries).

---

## 1. What this skill does

Produces the actual data values S5's scripts will use — either fully synthetic data generated to match the constraints S3's test cases imply, or production-derived data that has been irreversibly masked. Nothing downstream of this skill ever sees real, unmasked production data. This is a boundary, not a preference.

---

## 2. Required inputs

- S3's test case specifications (input values needed, data shape/constraints implied)
- Confirmed domain rules relevant to the data (e.g., valid formats, required uniqueness, referential constraints)

---

## 3. Required process

**Step 1 — Prefer synthetic generation.** For most test cases, generate data from scratch that matches the required shape and constraints. This is always safer than sourcing from production and should be the default.

**Step 2 — If production-derived data is genuinely required** (e.g., testing against a data pattern that can't be synthesized realistically), mask every identifying field irreversibly before it leaves this skill. Irreversible means: no field, or combination of fields, can be used to reconstruct the original value.

**Step 3 — Map each generated/masked value to the test case it serves.** A dataset with no clear mapping back to a `test_case_id` is not usable by S5.

**Step 4 — Verify the data actually reflects the domain constraint being tested**, not just a value that happens to be technically valid. Generating a random string that satisfies a format check but doesn't test the boundary the test case cares about defeats the purpose.

---

## 4. Output format

- `dataset_id`
- `test_case_id` — which S3 output this data serves
- `data_values` — the actual values
- `source` — "synthetic" or "masked production-derived"
- `masking_method` — if applicable, what was done and why it's irreversible

---

## 5. NOT permitted to

- Pass through any unmasked production-derived PII, under any circumstance, for any reason.
- Generate data that technically satisfies a test case's format requirements without reflecting the actual confirmed domain constraint being tested.
- Use a masking method that cannot be shown to be irreversible for the field type involved.
- Produce a dataset with no traceable mapping to the test case it's meant to serve.

---

## 6. Escalation triggers

- A test case's data requirement cannot be satisfied through synthetic generation and no safely maskable production source exists.
- A masking operation cannot guarantee irreversibility for a given field type (e.g., a field with too small a value space to mask meaningfully, like a boolean or a two-digit code).

---

*End of S4 skill.md*
