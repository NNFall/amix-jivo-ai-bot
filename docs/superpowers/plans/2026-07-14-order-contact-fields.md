# Confirmed Order Contact Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align order intake with AMIX's confirmed minimum: name and phone for every order, plus INN for bank transfer.

**Architecture:** Keep the existing structured `OrderDraft` and confirmation guard. Narrow readiness validation and model instructions without changing persistence shape, so previously supplied optional company, KPP and email values remain compatible.

**Tech Stack:** Python, SQLAlchemy, pytest, Gemini function calling.

---

### Task 1: Lock the confirmed requirements with tests

**Files:**
- Modify: `tests/test_order_intake_service.py`
- Modify: `tests/test_llm_client.py`

- [x] Add a service test proving bank transfer becomes ready with items, timing, fulfillment, payment method, contact name, contact phone and INN only.
- [x] Add a service test proving phone is required for non-bank-transfer orders even when email exists.
- [x] Add prompt and schema regressions proving the model asks only for the confirmed fields while optional supplied fields remain supported.
- [x] Run the focused tests and verify they fail because the old validator still requires payer type, company name and invoice email.

### Task 2: Narrow validation and generated guidance

**Files:**
- Modify: `core/order_intake_service.py`
- Modify: `core/assistant_service.py`
- Modify: `llm/prompts.py`
- Modify: `llm/tool_schemas.py`

- [x] Require contact name and phone for every order.
- [x] Require only INN in addition when `payment.method` is `bank_transfer`.
- [x] Preserve optional customer type, company/IP name, KPP and email when supplied, and include them in the final summary without asking for them.
- [x] Update prompt and missing-field follow-up wording to match the confirmed minimum.
- [x] Run focused tests and verify they pass.

### Task 3: Documentation, regression and deployment

**Files:**
- Modify: `docs/ORDER_INTAKE_REQUIREMENT_TRACEABILITY.md`
- Modify: `PLAN.md`
- Modify: `OPERATIONS.md`

- [x] Record Artem's confirmed fields and map them to implementation/tests.
- [x] Run `python -m pytest -q` and the dialog regression suite.
- [x] Run compile, diff and secret checks.
- [x] Request an independent review and fix validated findings.
- [x] Commit, push, deploy to VPS and verify services plus public health endpoint.
