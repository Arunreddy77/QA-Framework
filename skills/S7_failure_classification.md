# S7 — Failure Classification & Flaky Analysis

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked:** After S6, alongside S8, before H4 (in this pipeline: after S6, before S9)
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Sections 5 (Reporting Obligations) and 10 (Failure Handling & Retry Logic).

---

## 1. What this skill does

Looks at every failure S6 produced and decides which of four buckets it belongs to — app bug, flaky, environment, or automation error — before it's allowed to count toward any metric. No failure reaches S9's trend data unclassified.

---

## 2. Required inputs

For each failed test, this pipeline supplies:

- `test_case_id` and `test_ref` — which test failed (`test_ref` is the script file and test function)
- `s3_test_case` — the originating S3 test case (obligation, expected result, layer), when it could be matched. May be `null`.
- `error_message` and `traceback_tail` — what actually happened
- `script_code` — the test's code (possibly truncated)
- `attempts` and `passed_on_retry` — retry history. **This pipeline's S6 does not retry: every test runs exactly once, so `attempts` is always 1 and `passed_on_retry` is always false.**
- `confirmed_domain_rules` — the confirmed rules for the requirement (may include rules for unrelated features; ignore those)
- `flaky_history` — prior flaky classifications for the same test. **Not available yet**; it will say so.

---

## 3. Required process

**Step 1 — For every failure, gather the evidence:** what was expected (from `s3_test_case` and the confirmed rules), what actually happened (`error_message`, `traceback_tail`), and whether it passed on any retry.

**Step 2 — Ask these two questions, in order:**

1. *Did the test reach the application and get an answer?* If it never got one — a timeout, connection error, DNS failure, TLS failure, the test target unreachable — the failure is **environment**, unless the test's own code crashed before it ever made the request or UI action, in which case it's an **automation error**.
2. *The application answered. Does the answer match the confirmed requirement?* If the application's behavior contradicts the confirmed requirement, it's an **app bug**. If the application behaved as the confirmed requirement says and the test expected something else, it's an **automation error**.

**Step 3 — The four categories, with examples:**

- **`app_bug`** — application behavior contradicts the confirmed requirement the test was built from.
  - *Example:* the confirmed rule says a valid search for "top" returns `responseCode` 200 with a non-empty `products` array; the API returned `responseCode` 200 with `"products": []`. The assertion caught a real defect.
  - *Example:* the requirement says a valid request returns HTTP 200; the API answered HTTP 500 with an error body on a well-formed request.
- **`flaky`** — only applies if the test failed and then passed within the retry window, *and* investigation supports non-determinism (timing-sensitive, no clear application fault). A pass-on-retry alone is not sufficient. **Because this pipeline never retries, `flaky` cannot be assigned from a single run — do not use it here.** (Reference only, for when retry data exists:)
  - *Example:* a response-time check failed at 5.3 s on attempt 1 and passed at 0.6 s on attempt 2 with no change to the code or environment, and the endpoint's other checks are stable.
  - *Example:* a UI assertion fired before an animation finished on attempt 1 and passed on attempt 2, with the element present and correct both times.
- **`environment`** — the failure traces to infrastructure, network, or environment conditions unrelated to the application's logic or the test's logic.
  - *Example:* `requests.exceptions.ReadTimeout: ... Read timed out. (read timeout=10)` — the request got no answer at all, so nothing can be said about the application's behavior.
  - *Example:* `ConnectionError` / `getaddrinfo failed` / `NameResolutionError` for the host, or a `502`/`503` returned by a gateway in front of the application.
- **`automation_error`** — the test case or the automation code itself is wrong.
  - *Example:* `AttributeError: 'TopRequest' object has no attribute 'post'` — the script called a method on the wrong object; the test never exercised the application.
  - *Example:* the test asserts that an empty search returns `responseCode` 400, but the confirmed rule says an empty string returns 200 with all products and the API did exactly that — the assertion is stale, and the application is correct. (Also: `NameError`, `ImportError`, `SyntaxError`, or a locator that matches nothing because the selector is wrong.)

**Step 4 — If the evidence is inconclusive**, do not force a classification and do not guess the most likely bucket. Use `unclassified_pending_triage` for that test and say in `evidence_trail` exactly what is missing. **In this pipeline, do not return the escalation object for an inconclusive test** — an escalation response stops the whole run; a pending-triage entry inside `classifications` does not.

**Step 5 — Check flaky history.** If `flaky_history` shows a test classified flaky three or more times recently, set `flaky_history_flag` to true. Currently no history is supplied, so this will be false.

---

## 4. Output format

**The response MUST be a single JSON object shaped exactly as `{"classifications": [ ... ]}`, with exactly one entry per failed test in the input** — the same number of entries as `failed_tests`, each echoing that test's `test_case_id`. Never return a bare, unwrapped single classification, and never leave a failed test out.

```json
{"classifications": [
  {"test_case_id": "TC001", "test_ref": "test_TC001.py::test_search_product_valid_term[chromium]",
   "classification": "environment",
   "evidence_trail": "The request raised ReadTimeout after 10 s with no response, so the application's behavior was never observed. ...",
   "confidence": "clear", "flaky_history_flag": false}
]}
```

Each entry has:

- `test_case_id` and `test_ref` — copied exactly from the input
- `classification` — exactly one of these five strings: `app_bug`, `flaky`, `environment`, `automation_error`, `unclassified_pending_triage`
- `evidence_trail` — what was compared to reach this classification: the expected behavior, what happened, and why that points to this bucket
- `confidence` — `clear`, or `inconclusive` if the evidence didn't settle it
- `flaky_history_flag` — true only if this test has hit the three-strikes threshold

---

## 5. NOT permitted to

- Reclassify a failure as flaky solely because a retry passed, without applying the reproduction criteria in Step 3 — and never assign flaky when there is no retry evidence.
- Delete, suppress, or overwrite the original failure evidence during investigation.
- Force a classification into one of the four buckets when the evidence is genuinely inconclusive — use `unclassified_pending_triage` instead.
- Let an unclassified failure flow into S9's metrics under any label.

---

## 6. Escalation triggers

- A test has been classified flaky three or more times in recent history (only possible once flaky history is supplied).
- Do **not** escalate for a single inconclusive failure — see Step 4.

---

*End of S7 skill.md*
