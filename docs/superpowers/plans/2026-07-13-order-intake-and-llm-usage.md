# Order Intake And LLM Usage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect and confirm customer order details before manager handoff, while storing cumulative per-call LLM usage in SQLite.

**Architecture:** Gemini remains responsible for understanding natural language and updates a structured `OrderDraft` through a tool call. The backend persists the draft, validates readiness, protects stock quantities and enforces explicit confirmation before order handoff. A separate `LLMCall` table records usage returned by each provider response.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, SQLite, pytest, Gemini OpenAI-compatible API, Jivo Bot API.

---

### Task 1: Persistent LLM usage

**Files:**
- Modify: `database/models.py`
- Modify: `database/repositories.py`
- Modify: `core/assistant_service.py`
- Modify: `llm/audit_log.py`
- Test: `tests/test_assistant_service.py`
- Test: `tests/test_llm_client.py`
- Test: `tests/test_database_db.py`

- [x] Add failing tests for cumulative SQLite records, token breakdown and current Gemini 3.1 Flash-Lite pricing.
- [x] Run focused tests and confirm the expected failures.
- [x] Add the `LLMCall` model and repository functions.
- [x] Route all three AssistantService LLM call sites through one recording wrapper.
- [x] Run focused tests and confirm they pass.

### Task 2: Structured order draft

**Files:**
- Modify: `database/models.py`
- Modify: `database/repositories.py`
- Modify: `llm/tool_schemas.py`
- Create: `core/order_intake_service.py`
- Test: `tests/test_order_intake_service.py`

- [x] Add failing tests for draft merging, missing-field calculation, product checks and canonical summary generation.
- [x] Run focused tests and confirm the expected failures.
- [x] Add the `OrderDraft` model and repository functions.
- [x] Add the `update_order_draft` tool schema.
- [x] Implement validation, safe product checks and summary generation in `OrderIntakeService`.
- [x] Run focused tests and confirm they pass.

### Task 3: Conversation and handoff integration

**Files:**
- Modify: `core/assistant_service.py`
- Modify: `core/handoff_service.py`
- Modify: `llm/prompts.py`
- Modify: `tests/test_assistant_service.py`
- Modify: `tests/test_dialog_regression.py`

- [x] Add failing conversation tests for initial intake, free-form products, multi-turn collection, confirmation and premature-handoff blocking.
- [x] Run focused tests and confirm the expected failures.
- [x] Stop treating order intent as an immediate backend handoff.
- [x] Execute and persist `update_order_draft` calls, then generate the next customer message from the tool result.
- [x] Include the active order draft in runtime context.
- [x] Allow `order_creation` handoff only after an explicit confirmation of an awaiting-confirmation draft.
- [x] Update the prompt with the intake flow, delivery/payment facts and non-selling tone.
- [x] Run focused tests and confirm they pass.

### Task 4: Documentation, full verification and deployment

**Files:**
- Modify: `PLAN.md`
- Modify: `OPERATIONS.md`
- Modify: `README.md`

- [x] Update operating documentation and the requirement traceability report.
- [x] Run the full pytest suite.
- [x] Run dialog regression evaluation.
- [x] Run an independent agent review against the quoted requirements.
- [x] Fix all critical or important review findings and rerun verification.
- [x] Commit and push the feature branch.
- [x] Deploy to VPS, create the new tables on startup, restart services and verify health.
