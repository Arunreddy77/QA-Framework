# S5 — Test Script Generation

**Skill type:** Stateless — read fresh by the LLM Gateway on every invocation
**Invoked between:** H2 (Test Case Review) and H3 (Script/Code Review)
**Inherits:** All binding sections of AGENT_INSTRUCTIONS.md, especially Section 13.1 (UI Automation Standard) and Section 13.2 (API Automation Standard) — this skill's job is to make those standards actually happen, not just exist in a separate document.

---

## 1. What this skill does

Converts H2-approved test case specifications into executable Playwright automation — UI actions and/or raw HTTP/API requests, per the layer(s) tagged on each test case — using S4's test data. The output is code, but the judgment behind it (what to assert, how to locate things, when to wait) is governed entirely by Section 13, not by whatever seems easiest to write.

---

## 2. Required inputs

- H2-approved test case specifications from S3 (expected results, layer tagging, traceability ID)
- S4's test data, mapped to each test case
- Target environment scope (least-privilege credentials only, per Section 9)

---

## 3. Required process

**Step 0 — Language requirement (read this first): all output MUST be Python.** This is non-negotiable and applies to every script, UI or API:

- Generated scripts MUST be valid Python, not JavaScript/TypeScript.
- Each test function MUST be named with a `test_` prefix (pytest's discovery convention).
- Each test function MUST accept Playwright's `page` fixture as a parameter (from `pytest-playwright`), e.g. `def test_forgot_password_valid_email(page):`.
- Imports MUST use Python syntax (e.g. `import pytest`), never JavaScript/TypeScript import syntax (e.g. never `import { test, expect } from '@playwright/test'`).
- Assertions MUST use Python's `assert` statement or Playwright Python's `expect()` from `playwright.sync_api` — never JavaScript's `expect()` from `@playwright/test`.
- For API-layer test cases, use Python's `requests` library (`import requests`; `requests.post(url, data={...}, timeout=...)`). Do NOT take a parameter named `request` in a test function: in pytest that name is pytest's own built-in fixture (not an HTTP client), and calling `.get()`/`.post()` on it fails. Never use JavaScript's `fetch` or the `request` object from `@playwright/test` either.

Example of a correctly-formatted Python test function (UI layer):

```python
import pytest
from playwright.sync_api import expect

def test_forgot_password_valid_email(page):
    page.goto("https://app.example.com/forgot-password")
    page.get_by_label("Email").fill("registered.user@example.com")
    page.get_by_role("button", name="Send reset link").click()
    expect(page.get_by_text("If an account exists, a reset link has been sent.")).to_be_visible()
```

A script that is valid JavaScript/TypeScript Playwright but not valid Python fails this skill's job entirely, regardless of how correct its locators or assertions are — it cannot run in this project's Python/pytest test suite at all.

**Step 1 — For UI test cases, choose locators in the required order:** role/label/text-based semantic locators first, `data-test-id` attributes next, CSS selectors after that. XPath only as a last resort, and only with a documented reason in the script's metadata. Never locate by dynamically generated IDs or framework-specific class names.

**Step 2 — For UI test cases, use auto-wait by default.** Explicit waits are allowed only for network-idle or a specific, justified application-state condition — document why in the script comment. Hard-coded sleep statements are never acceptable; if a test seems to need one, that's a potential application timing bug to escalate, not a delay to add.

**Step 3 — For API test cases, write the required assertions:** exact status code (not a status-code family), full response schema validation against the confirmed contract, response time against the configured SLA, and any headers the requirement specifies. Isolate token acquisition/refresh logic from test logic so an expired token is never misreported as an application failure.

**Step 4 — Write the assertion to match the expected result exactly as S3 stated it** — not a looser version that's easier to get passing. If the exact assertion can't be written given the current application state, that's a signal to escalate, not to soften.

**Step 5 — Tag the script with full traceability**: which `test_case_id` it implements, which layer(s) it covers, and which Section 13 standard it follows.

---

## 4. Output format

**The response MUST be a single JSON object shaped exactly as `{"scripts": [ ... ]}`.** The `scripts` array holds **exactly one script entry per approved test case from S3** — the same number of entries as S3 approved test cases, each entry's `test_case_id` matching one S3 test case. Never return a bare, unwrapped single-script object (a top-level `script_id`/`script_code` with no `scripts` array), never stop after the first test case, never omit an approved test case, and never add a script for a test case S3 did not approve. A response that breaks this shape stops the run before any test executes.

Shape, shown with two approved test cases:

```json
{"scripts": [
  {"script_id": "SC-001", "test_case_id": "TC-001", "layer": "API", "script_code": "...", "assertions": ["..."]},
  {"script_id": "SC-002", "test_case_id": "TC-002", "layer": "UI", "script_code": "...", "assertions": ["..."]}
]}
```

Each entry in the `scripts` array has these fields:

- `script_id`
- `test_case_id` — the S3 output this script implements
- `layer` — UI, API, or both
- `script_code` — the executable Playwright script, written in **Python** (per Section 3, Step 0) — never JavaScript/TypeScript
- `locator_strategy_notes` — if UI: which strategy was used and why, especially if XPath was needed
- `wait_strategy_notes` — if UI: any explicit waits used and their justification
- `assertions` — restated plainly, so an H3 reviewer can check them against the S3 expected result without reading code

---

## 5. NOT permitted to

- Alter a test's assertions or expected outcomes to make it pass. This is the single rule H3 exists to check — do not make H3's job harder by needing to catch this.
- Hardcode a value that masks a real data-dependency the test is supposed to exercise.
- Use a locator strategy or wait strategy that deviates from Section 13.1 without documenting why and flagging it for H3's attention.
- Weaken an API assertion (e.g., checking "2xx" instead of the exact required status code) to avoid a failure.
- Generate a script for a test case that hasn't passed H2.

---

## 6. Escalation triggers

- A test case specification is technically infeasible to automate as written (e.g., it requires interacting with an element that has no stable locator of any kind).
- Writing the assertion exactly as specified would require weakening it to get the test to pass in the current environment.
- A Section 13 standard genuinely cannot be met given the test case as specified (e.g., no SLA is configured for an endpoint the test needs to check response time against).

---

*End of S5 skill.md*
