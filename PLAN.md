# PLAN

## Update 2026-07-17 (Model-Driven Two-Tool Candidate)

- Status: local implementation and deterministic dialog verification pass; independent reviews and isolated live Gemini verification on the VPS are in progress. Production services have not been restarted.
- Runtime boundary: the backend no longer classifies customer language with keyword lists, regex intent rules, prelookup routes or hidden order state. Gemini receives the complete chronological user/assistant/tool history and may call only `search_products` or `handoff_to_manager`.
- Product boundary: backend code only executes the model-supplied search, normalizes catalog identifiers and compares an explicitly supplied per-product quantity with stock.
- Jivo reliability: a client event is finalized only after the background turn is delivered; superseded turns are recorded separately; failed delivery removes the undelivered generated turn and permits a later retry of the same event.
- Local verification: `python -m pytest -q` -> `124 passed`; dialog regression -> `PASS=9 FAIL=0`; fake history-order evaluation with three repetitions -> `27/27` scenarios and `123/123` turns; compile and diff checks passed.
- Evidence: local ignored files `outputs/history-order-fake.json` and `outputs/history-order-fake.md`; tracked concise report `DIALOG_EVALS.md`.
- Remaining gate: resolve independent review findings, run repeated real Gemini scenarios in an isolated VPS copy/database, then deploy and verify Jivo only if every blocking check passes.

## Update 2026-07-16 (Live V6 Hardening In Progress)

- Status: live Gemini v6 failed 6 of 18 scenario runs; production services remain on the previous loaded revision and must not be restarted yet.
- Fixed locally after v6: natural customer-name recognition, preservation of customer-requested quantities, removal of premature "order completed" wording, manager handoff summary sourced from the exact customer-confirmed bot summary, and forced `search_products` retry for new product facts.
- Current hardening scope: manager-request negation, premature handoff claims, correction messages that start with "yes", invoice/payment false positives, broader exact-stock redaction, two-tool enforcement for Kie, Jivo send failures, and stronger chronological-history eval assertions.
- Constraints: exactly two model tools (`search_products`, `handoff_to_manager`); no order-state tool or hidden order aggregate; complete chronological history is the only order memory.
- Verification gate: focused red/green tests, full local suite, repeated fake eval, dialog regression, repeated real Gemini eval on VPS, then independent review of the exact candidate commit.
- Deployment gate: merge/restart only after every blocking live and review finding is closed; preserve production SQLite `-shm` and `-wal` files.

## Update 2026-07-16 (History-Driven Order Flow)

- Status: implementation stabilized locally; server verification, repeated live Gemini evaluation and final review of the exact commit remain before deployment.
- Goal: remove `update_order_draft` and all parallel order memory so Gemini conducts short order conversations from complete chronological history.
- Tool boundary: expose exactly `search_products` and `handoff_to_manager`.
- History: send the whole persisted chat from its first message through chronological assistant/tool events; do not apply the current 20-row limit.
- Prompt: replace draft-specific and narrow instructions with one compact generalized order policy covering collection, corrections, summary, explicit confirmation and handoff.
- Product lookup: represent requested quantity per product and preserve `customer query -> code -> article` identity.
- Backend scope: retain message persistence, rapid-message supersession, Jivo lifecycle/idempotency, product truth, stock privacy, usage accounting and invite-before-promise behavior; do not parse a second order aggregate.
- Legacy data: stop all runtime reads/writes of `OrderDraft`; leave the physical table for one rollback window, then remove it separately.
- Verification: TDD, full deterministic suite, repeated real Gemini multi-turn evaluation on the server, saved JSON/Markdown evidence and independent code/prompt/transcript reviews.
- Specification: `docs/superpowers/specs/2026-07-16-history-driven-order-flow-design.md`.
- Implementation plan: `docs/superpowers/plans/2026-07-16-history-driven-order-flow.md`; execution started through TDD and subagent review checkpoints.
- Local evidence: `python -m pytest -q` -> `224 passed`; dialog regression -> `OK=31 PARTIAL=0 FAIL=0`; fake history-order evaluation with three repetitions -> `27/27` scenario runs and `123/123` turns; exactly two declared tools; compile and diff checks passed.
- Current gate: commit the stable candidate, run the same history-order scenarios repeatedly through the production-configured Gemini provider on the VPS, review every saved transcript and the exact commit independently, then merge, deploy and verify Jivo services.

## Update 2026-07-16 (Independent Audit Of Live Dialog Evaluation)

- Status: completed; previous 6.7/10 score withdrawn, no production behavior changed.
- Trigger: the first order transcript exposed a mismatch between the customer's wording, the bot reply and the persisted order draft that the initial 10/10 score did not penalize.
- Goal: independently re-audit the requirements, simulation methodology, order/tool implementation, prompts and every live transcript before accepting the evaluation results.
- Review structure: multiple read-only subagents with separate scopes, followed by a consolidated local verification against raw JSON and source code.
- No production changes or deployments are allowed during this audit.
- Corrected result: scenario-average 4.0/10 and turn-weighted 4.1/10; MT-01 reduced from 10/10 to 6/10.
- MT-01 root cause: the product turn called only `search_products`, left `order_draft.items` empty, and applied scalar `requested_quantity=2` to codes whose requested quantities were 2 and 3; items were recovered only on the following turn.
- Critical implementation findings: wrong-tool calls bypass the order-tool retry, per-item quantities cannot be represented by the search schema, later tool calls can be discarded, list replacement can lose items, and a failed Jivo invite can still be followed by a handoff promise.
- Methodology finding: the run is valid only as a real-Gemini service-layer smoke; it bypassed the production Jivo webhook/background/debounce/outbound/lifecycle path and had no machine assertions or reproducibility manifest.
- Local audit: `data/logs/live_multiturn_dialogs_2026-07-16-independent-audit.md`; the original report is explicitly marked superseded.
- Next implementation step: a separate TDD iteration for order invariants, per-item checks, tool execution, handoff delivery truthfulness and a versioned service plus Jivo E2E harness.

## Update 2026-07-15 (Live Multi-Turn Dialog Evaluation)

- Status: completed; live behavior reviewed and scored, no production behavior changed.
- Goal: run several long, isolated customer dialogs through the production-configured Gemini provider and real product tools on the VPS.
- Scenarios: coded order, free-form order, protected stock checks, duplicate article refinement, missing-code recovery and technical handoff.
- Isolation: use a temporary SQLite database populated from the current AMIX XML; use demo handoff mode; do not send messages to real Jivo chats or alter production statistics.
- Evidence: save complete chronological dialogs, tool calls, draft/handoff states, latency and token/cost usage to local JSON and Markdown reports.
- Result: 6 scenarios, 37 customer turns, 45 real Gemini calls, 268,972 total tokens, estimated cost RUB 8.03; average response 1.54 s, P95 3.09 s.
- Score: 6.7/10 after independent review. Both order-intake scenarios passed; stock attempt limiting, large duplicate-article refinement and missing-code recovery failed.
- Confirmed defects:
  - quantity-attempt counting is bypassed when later checks are answered from `active_product` without a new `search_products` call;
  - a sentence-ending dot can become part of a numeric product code before the literal code lookup;
  - price refinement cannot select a product omitted from the first 20 matches of a very large duplicate-article result;
  - a quantity reply in a product-check conversation can start order intake before the customer asks to place an order;
  - an immediate handoff after a customer disputes a not-found result prevents a later corrected code from being checked.
- Independent review: totals, costs, latency, transcripts, order states and handoff behavior matched the raw JSON; the reviewer identified the premature missing-code handoff and required the score reduction above.
- Local artifacts: `data/logs/live_multiturn_dialogs_2026-07-15.json` and `data/logs/live_multiturn_dialogs_2026-07-15.md` (ignored by Git because they contain full synthetic transcripts).
- Completion criteria met: all scenarios executed and manually reviewed, artifacts saved locally, invalid encoding run excluded, temporary VPS database and result file removed.

## Update 2026-07-14 (Confirmed Order Contact Fields)

- Status: completed, independently reviewed, verified and deployed to VPS.
- AMIX confirmed that the bot must collect the customer's name and phone, plus INN for payment by bank transfer.
- Customer type, company/IP name, KPP and invoice email are no longer required; values supplied voluntarily remain supported.
- Final summary, explicit customer confirmation and manager handoff behavior remain unchanged.
- Implementation plan: `docs/superpowers/plans/2026-07-14-order-contact-fields.md`.
- Verification target: focused red/green tests, full pytest suite, dialog regression, secret scan and deployment smoke.
- Local verification: `python -m pytest -q` -> `166 passed`; dialog regression -> `OK=31 PARTIAL=0 FAIL=0`; compile and diff checks passed.
- Independent review: no findings; the suggested optional-field coverage was added before the final test run.
- Deployment: server revision `8c5d963`; `166 passed`; both services active; local and public healthchecks passed.
- Isolated live Gemini smoke: two customer turns produced `awaiting_confirmation`, no missing fields, only name/phone plus INN for the invoice flow, and zero handoffs.

## Update 2026-07-13 (Order Intake + Persistent LLM Usage)

- Status: completed, reviewed, verified and deployed to VPS.
- Source requirements fixed in `docs/superpowers/specs/2026-07-13-order-intake-and-llm-usage-design.md`.
- Implementation plan: `docs/superpowers/plans/2026-07-13-order-intake-and-llm-usage.md`.
- Scope:
  - collect order details instead of immediately handing off;
  - support codes/articles and free-form product descriptions;
  - collect delivery, payment and contact details;
  - collect the customer's desired timing without promising delivery dates;
  - collect legal entity/IP details for bank-transfer invoices;
  - show a final summary and require explicit confirmation before order handoff;
  - store every LLM call's tokens, latency and estimated cost cumulatively in SQLite;
  - keep PDF, Excel and image specification parsing out of scope.
- Implemented:
  - `OrderDraft` persistence and `update_order_draft` tool flow;
  - backend confirmation guard for order handoff;
  - safe yes/no quantity checks without exact stock exposure;
  - cumulative `LLMCall` records and admin totals;
  - current Gemini 3.1 Flash-Lite paid pricing;
  - safe not-found wording for XML rows omitted at zero stock.
- Independent review fixes:
  - all model handoff reasons are blocked while an order draft is incomplete or unconfirmed;
  - an order confirmation is valid only immediately after the canonical summary was persisted in chat history;
  - LLM usage is committed before a later outbound Jivo operation can roll it back;
  - bank-transfer intake requires a phone and safely includes any payer details the customer volunteered;
  - order-intake not-found replies use the same guarded wording as normal product search;
  - raw conversation debug logs are disabled by default.
  - stale order turns discard hidden draft/tool/reply state while retaining usage statistics;
  - dissatisfied customers can still reach a manager during an active order;
  - Jivo invitation succeeds before the customer is sent a handoff promise;
  - exact stock is redacted and guarded in order replies, unknown stock remains unknown;
  - items can be stored before quantity is known;
  - rotating provider audit masks contact and invoice identifiers.
- Baseline check before changes: `python -m pytest -q` -> `133 passed`.
- Superseded on 2026-07-14: AMIX confirmed the exact minimum as name, phone and INN for bank transfer.
- Verification: `python -m pytest -q` -> `162 passed`; dialog regression -> `OK=31 PARTIAL=0 FAIL=0`.
- Deployment: server commit `e96b7ef`; `162 passed`; both services active; external health `200`; isolated live Gemini order collection and confirmed-handoff smokes passed.
- Next: observe real Jivo order dialogs and adjust the confirmed minimum only if AMIX managers request it.

## Update 2026-07-02 (Prevent Premature Handoff On Ambiguous Product)

- Status: completed and deployed.
- Goal:
  - Fix the case where the bot asks the customer to clarify a product variant and also triggers manager handoff in the same turn.
  - Keep the chat active after multiple product variants are found until the customer provides product code or price.
- Done:
  - Added a regression test for a CWJ-102 style color question where multiple product variants are found and the model tries to append manager handoff.
  - Added a backend guard: if product clarification is pending, an accidental "Передаю менеджеру" phrase is replaced with the safe code/price clarification fallback instead of creating a real handoff.
  - Updated prompts to explicitly forbid manager handoff on unresolved multiple variants unless the customer asks for a person.
- Checks:
  - `python -m pytest tests/test_assistant_service.py::test_assistant_service_does_not_handoff_when_multiple_variants_need_clarification -q` -> `1 passed`.
  - `python -m pytest tests/test_assistant_service.py -q` -> `65 passed`.
  - `python -m pytest -q` -> `133 passed`.
- VPS:
  - deployed commit `3d167f5`;
  - server `.venv/bin/python -m pytest -q` -> `133 passed`;
  - restarted `amix-api.service` and `amix-telegram-demo.service`;
  - both services are `active/running`;
  - `https://amix.cifresh.ru/health` -> `200 {"status":"ok"}`.

## Update 2026-06-17 (Stock Scraping Protection)

- Status: completed and deployed.
- Goal:
  - Stop exposing exact stock quantities for plain availability/stock requests.
  - Ask the customer for the desired quantity if they ask how many are available without specifying quantity.
  - If desired quantity is specified, answer only whether that quantity is available.
  - Escalate to a manager after repeated quantity checks for the same product code in one chat.
- Plan:
  - Added regression tests for stock request without quantity, enough quantity, insufficient quantity, quantity follow-up, and repeated attempts.
  - Implemented a backend guard in product-result reply flow so the rule does not rely on LLM wording.
  - Updated prompts to align model behavior with the backend guard.
  - Local full test suite passed.
  - Deployed to VPS.
- Checks:
  - `python -m pytest tests/test_assistant_service.py -q` -> `63 passed`.
  - `python -m pytest -q` -> `132 passed`.
- VPS:
  - deployed commit `aeec1c2`;
  - server `.venv/bin/python -m pytest -q` -> `132 passed`;
  - restarted `amix-api.service` and `amix-telegram-demo.service`;
  - both services are `active/running`;
  - `https://amix.cifresh.ru/health` -> `200 {"status":"ok"}`.

## Update 2026-06-15 (amix.cifresh.ru Nginx/SSL)

- Status: completed on VPS.
- Goal:
  - Point `https://amix.cifresh.ru` to the existing AMIX backend on VPS.
  - Keep the FastAPI service behind Nginx and issue a Let's Encrypt certificate.
- Plan:
  - Verified DNS resolves `amix.cifresh.ru` to the VPS.
  - Inspected current VPS services, ports, Nginx config and existing app health endpoint.
  - Added an Nginx server block for `amix.cifresh.ru` proxying to the running AMIX app.
  - Issued/attached Let's Encrypt SSL certificate and enabled HTTPS redirect.
  - Verified external `https://amix.cifresh.ru` health and admin endpoints.
- Risks:
  - Existing Nginx config must not be broken while adding the new host.
  - SSL issuance depends on DNS propagation and port 80 reachability.
- Checks:
  - HTTP `http://amix.cifresh.ru/health` -> `301` to HTTPS.
  - HTTPS `https://amix.cifresh.ru/health` -> `200 {"status":"ok"}`.
  - HTTPS `https://amix.cifresh.ru/admin` -> `303` to `/admin/login`.
  - HTTPS `https://amix.cifresh.ru/admin/login` -> `200` login page.

## Update 2026-05-20 (Google Chronological Tool History)

- Status: completed locally, pending VPS deploy.
- Finding:
  - Google Logs test `AMIX_LOG_SHAPE_TEST_A_TOOL_ROLE_20260520` confirmed that Google OpenAI-compatible endpoint displays chronological `assistant.tool_calls` and `functionResponse` in `contents`.
  - Google Logs test `AMIX_LOG_SHAPE_TEST_B_MIDDLE_SYSTEM_20260520` confirmed that a middle `system` message is moved to `systemInstruction`, not kept chronologically.
  - Direct VPS test `AMIX_LOG_SHAPE_TEST_D_TOOL_HISTORY_NO_TOOLS_20260520` confirmed completed tool history is accepted even when the final request does not pass `tools`.
- Done:
  - Removed Google-specific conversion of tool history to `TOOL_RESULTS_JSON` system messages.
  - Kept system-message merge for Google, because multiple `system` messages still map to one `systemInstruction`.
  - Added regression tests that Google-bound assistant payloads preserve `assistant.tool_calls` and `role=tool`.
- Checks:
  - `python -m pytest -q` -> `112 passed`.
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Next:
  - Deploy to VPS and verify Google Logs on a live/tool smoke turn.

## Update 2026-05-20 (Strict Check/FAQ Answer Guards)

- Status: completed and deployed.
- Done:
  - Treat plain product check requests like `проверьте 14.023пр и xyz-999` as stock/check-only unless the customer explicitly asks for price, weight, mass, comparison, discount or order.
  - Keep full price/weight facts in LLM-visible tool history for later follow-up questions.
  - Guard only the final client-facing reply for check-only requests: if the model leaks price/weight or starts offering manager/order/analogs without request, replace the final text with a stock/not-found fallback.
  - Allow normal short FAQ politeness such as `Будем рады видеть вас`; still guard unsupported facts and AI-bot capability claims.
- Checks:
  - `python -m pytest -q` -> `111 passed`.
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- VPS:
  - deployed commit `c162b45`;
  - server `.venv/bin/python -m pytest -q` -> `111 passed`;
  - `amix-telegram-demo.service` -> `active/running/enabled`;
  - smoke `Проверьте 14.023пр и xyz-999` returned stock/not-found without price/weight or manager offer;
  - the stored tool-result still contains price/weight for later context;
  - smoke address FAQ allowed a short polite ending from the model.
- Next:
  - Explain Google AI Studio log shape and keep observing LLM-first Telegram behavior.

## Update 2026-05-20 (Switchable LLM-First Product Search)

- Status: completed and deployed.
- Done:
  - Added `ASSISTANT_BACKEND_PRELOOKUP_ENABLED`.
  - Default stays `true` so existing production behavior is unchanged unless the flag is explicitly disabled.
  - When disabled, backend no longer performs automatic product prelookup for article, price-refinement, contextual follow-up, order, manager or technical prelookup branches.
  - Product facts are fetched only when the LLM calls `search_products`; backend then executes exactly that tool call and stores `assistant_tool_call` + `tool` history.
  - Hardened LLM-first stock-only flow: final client-facing stock-only replies are replaced with deterministic fallback if the model mentions price or weight.
  - Added a guard that replaces a stock-only LLM reply with deterministic stock fallback if the model still mentions price or weight.
  - Added regression coverage proving an article query goes through LLM tool-call flow when backend prelookup is disabled.
- Checks:
  - `python -m pytest tests\test_assistant_service.py::test_assistant_service_can_disable_backend_prelookup_for_article_query tests\test_assistant_service.py::test_assistant_service_uses_backend_prelookup_for_article_query -q` -> `2 passed`.
  - `python -m pytest -q` -> `108 passed`.
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- VPS:
  - deployed commit `1f70810`;
  - server `.env` set to `ASSISTANT_BACKEND_PRELOOKUP_ENABLED=false`;
  - server `.venv/bin/python -m pytest -q` -> `108 passed`;
  - `amix-telegram-demo.service` -> `active/running/enabled`;
  - smoke confirmed LLM-first flow: `client`, `llm_tool_call`, `tool_result`, `llm_tool_search`; stock-only reply returned only availability.
- Next:
  - Test live Telegram wording with the LLM-first product search mode enabled.

## Update 2026-05-20 (Google System Message Merge)

- Status: completed locally, pending VPS deploy.
- Finding:
  - Google AI Studio logs showed only the last `system` block as `systemInstruction`, usually `TOOL_RESULTS_JSON`.
  - Server audit confirmed the OpenAI-compatible request contained the full first system prompt, but Google native logging and token counts indicated multiple `system` messages were being collapsed incorrectly by the Google bridge.
- Done:
  - Google provider now merges all `system` messages into one first `system` message before the HTTP request.
  - Added a test that verifies `SYSTEM_PROMPT` and `TOOL_RESULTS_JSON` are sent together in one Google system message.
  - Added a general prompt rule: if the latest customer message itself looks like a new article/code/product name, it is more important than old `active_product`.
- Checks:
  - `python -m pytest tests\test_llm_client.py::test_openai_service_uses_google_ai_studio_provider -q` -> `1 passed`.
  - `python -m pytest -q` -> `108 passed`.
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Next:
  - Deploy and verify Google logs show a full merged `systemInstruction`.

## Update 2026-05-19 (LLM-first FAQ and Product Follow-ups)

- Status: completed locally, pending VPS deploy
- Done:
  - Disabled scripted company FAQ replies by default when LLM is enabled.
  - Kept deterministic company FAQ only as offline/fallback behavior via `ASSISTANT_DETERMINISTIC_COMPANY_FAQ_ENABLED`.
  - Added ordering guard for extracted product candidates so multi-product queries preserve the customer's written order.
  - Added context resolver for follow-ups like `а по второму` and `am02 который я написал` using the previous product lookup.
  - Strengthened prompts so product answers keep `результаты_по_запросам` order and company answers use only AMIX reference facts.
  - Added a dedicated LLM rewrite flow for company FAQ answers: backend supplies safe AMIX facts, the model only reformulates them.
  - Added a guard that falls back to safe AMIX facts if the model writes about AI-bot capabilities or unsupported characteristics.
  - Added Google-provider payload adaptation: synthetic tool history is sent as `TOOL_RESULTS_JSON` system context, not as `assistant.tool_calls`.
  - Added regression tests for company FAQ routing and contextual product follow-ups.
- Checks:
  - `python -m pytest -q` -> `95 passed`.
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Next:
  - Commit, push and deploy to VPS.

## Update 2026-05-19 (Google Free-Tier Rate Limit Throttle)

- Status: completed and deployed
- Done:
  - Inspected server LLM audit log: recent entries contained `12` success, `7` HTTP 503, `6` HTTP 429 and `5` old HTTP 400 before the Google tool-history fix.
  - Added Google provider throttling via `GOOGLE_AI_MIN_REQUEST_INTERVAL_SECONDS`; default is `13` seconds for a 5 RPM free-tier project.
  - Added long delay for 429 retries via `GOOGLE_AI_RATE_LIMIT_RETRY_DELAY_SECONDS`; default is `65` seconds, so retries do not burn attempts inside the same minute window.
  - Kept KIE retry behavior unchanged.
  - Added unit tests for provider throttling and long rate-limit retry delay.
- Checks:
  - `python -m pytest tests\test_llm_client.py -q` -> `9 passed`.
  - `python -m pytest tests\test_assistant_service.py -q` -> `46 passed`.
  - `python -m pytest -q` -> `97 passed`.
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- VPS:
  - commit `66f03ca` deployed to `/root/amix`;
  - server `.env` updated with `GOOGLE_AI_MIN_REQUEST_INTERVAL_SECONDS=13` and `GOOGLE_AI_RATE_LIMIT_RETRY_DELAY_SECONDS=65`;
  - server `.venv/bin/python -m pytest -q` -> `97 passed`;
  - `amix-telegram-demo.service` -> `active/running/enabled`.
- Next:
  - Observe live Telegram usage: answers on Free tier may queue behind the 13-second Google throttle, but 429 loops should stop.

## Update 2026-05-19 (Google Model Dialog Comparison)

- Status: completed on VPS.
- Done:
  - Added reusable script `scripts/compare_google_models_dialog.py`.
  - Confirmed available server-side Google model ids through the Gemini API models endpoint:
    `gemini-3-flash-preview`, `gemini-2.5-pro`, `gemini-3.1-flash-lite`.
  - Ran the same 10-turn AMIX dialog on VPS for all three models.
  - Report saved on VPS:
    `/root/amix/data/logs/model_compare_2026-05-19.md`
    and `/root/amix/data/logs/model_compare_2026-05-19.json`.
- Result summary:
  - `gemini-3.1-flash-lite`: fastest and cheapest in this run, 20.0s total, 7,185 tokens, about 0.1343 RUB.
  - `gemini-2.5-pro`: stable but much more expensive, 77.1s total, 12,247 tokens, about 8.1371 RUB.
  - `gemini-3-flash-preview`: slowest in this run due to two HTTP 503 retries, 169.0s total, 7,394 tokens, about 0.8799 RUB.
  - All three models hallucinated technical meaning for `л`/`пр` before saying that technical data is missing; prompt/backend guard should be tightened before relying on technical answers.
- Checks:
  - Local `python -m pytest -q` -> `97 passed`.
  - VPS `python -m pytest -q` -> `97 passed`.
- Next:
  - Add a hard technical-question guard: if structured product data has no technical characteristics, final answer should not let the model infer meanings like left/right.

## Update 2026-05-19 (Gemini 3.1 Pro Append)

- Status: completed on VPS.
- Done:
  - Ran the same 10-turn dialog on `gemini-3.1-pro-preview` before adding the technical guard.
  - Added combined report on VPS:
    `/root/amix/data/logs/model_compare_2026-05-19-combined.md`
    and `/root/amix/data/logs/model_compare_2026-05-19-combined.json`.
- Result:
  - `gemini-3.1-pro-preview`: 272.2s total, 8,040 tokens, about 5.1830 RUB.
  - Last technical turn hit a 180s read timeout and fell back to safe fallback text.
  - Earlier `14.023 без пр` answer still inferred right/left semantics, so Pro did not remove the hallucination risk.
- Next:
  - Keep `gemini-3.1-flash-lite` as the practical default unless a new guarded comparison shows Pro quality is materially better for AMIX.

## Update 2026-05-19 (Switch Default To Gemini 3.1 Flash Lite + Safer Consulting Prompt)

- Status: completed and deployed.
- Done:
  - Changed default direct Google model to `gemini-3.1-flash-lite`.
  - Updated prompt with general consulting rules:
    no pushy sales wording, no order/offering language without explicit purchase intent, no technical recommendations from article/name/common knowledge.
  - Added backend guard for technical handoff answers:
    keep checked article names, but remove model-inferred technical explanations when structured data has no characteristics.
  - Updated README and `.env.example`.
- Checks:
  - `python -m pytest tests\test_assistant_service.py tests\test_dialog_regression.py -q` -> `50 passed`.
  - `python -m pytest -q` -> `98 passed`.
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- VPS:
  - commit `2a31de6` deployed to `/root/amix`;
  - server `.env` set to `GOOGLE_AI_MODEL=gemini-3.1-flash-lite`;
  - server `.venv/bin/python -m pytest -q` -> `98 passed`;
  - `amix-telegram-demo.service` -> `active/running/enabled`.
- Next:
  - Verify live Telegram behavior on the next user test message.

## Update 2026-05-17 (Order Shortage + Pricing Policy)

- Status: completed and deployed
- Done:
  - Added `SHOW_CORPORATE_PRICE` setting and `.env.example` entry.
  - Backend now passes pricing policy, requested quantity, response mode and code-query context into `backend_actions`.
  - Stock shortage now has priority over generic order handoff: if requested quantity is greater than free stock, bot must not say the order can be оформлен.
  - Customer replies now sanitize internal word `выгрузка` into `текущие данные`.
  - Product lookup results now include `display_query`, so similar/not-found replies use the customer's raw query like `14.023`, not normalized `14023`.
  - Fallback responses explicitly mention code lookup: `По коду 1364 нашёл артикул ...`.
  - Product prompt updated with rules for raw/display query, corporate price policy and shortage handoff wording.
  - Live eval scenarios extended from 27 to 31 for shortage order, raw-query display, corporate price and missing price wording.
  - First VPS live run exposed a real-data edge case: `14.023` was incorrectly treated as exact code `14023` because backend searched by normalized candidate.
  - Fixed lookup execution to search by restored customer fragment/display query when available, while preserving normalized value as `raw_backend_query`.
- Checks:
  - Local full pytest -> `53 passed`.
  - Local dialog regression -> `OK=31 PARTIAL=0 FAIL=0`.
  - Local live eval with real LLM was not run because local `.env` has no `KIE_API_KEY`/`OPENAI_API_KEY`.
  - VPS full pytest -> `53 passed`.
  - VPS live eval -> `31` scenarios, `31` without style flags, `0` manual style-review flags.
- Next:
  - For future live checks, append full dated runs to `LIVE_DIALOG_EVALS.md` instead of replacing the file, so external review can compare full model outputs by run.
  - Continue Telegram demo checks with real user messages and keep tuning only on observed failures.

## Update 2026-05-17 (Live Semantic Assertions)

- Status: completed and deployed
- Done:
  - Strengthened `SYSTEM_PROMPT` for FAQ questions: contacts, address, schedule and delivery must answer concrete user intent, not generic greeting.
  - Added product price display fields from backend: `retail_price_display`, `corporate_price_display`.
  - Product prompt now tells the model to use display price fields and not round prices.
  - Sanitizer now fixes glued code wording such as `коду26168`.
  - Live eval now separates `style_flags` from `content_flags`.
  - Added content assertions for contacts, delivery, code spacing, rounded corporate prices, missing-price wording and shortage wording.
- Checks:
  - Local full pytest -> `57 passed`.
  - Local dialog regression -> `OK=31 PARTIAL=0 FAIL=0`.
  - VPS full pytest -> `57 passed`.
  - VPS live eval appended run -> `31` scenarios, `31` without style flags, `31` without content flags.
- Next:
  - Next test expansion should move from single-turn scenarios to multi-turn dialogs with 2-3 user messages and context-dependent answers.

## Update 2026-05-17 (Live LLM Dialog Evaluation)

- Status: completed and deployed
- Done:
  - Added `scripts/run_live_dialog_eval.py` for real configured LLM/KIE dialog checks.
  - Live eval runs through `AssistantService`, real prompts, SQLite product lookup, backend actions and real model responses.
  - Added 22 live scenarios covering company Q&A, exact products, duplicate articles, dirty input, mixed lookup, order, shortage and handoff.
  - Fixed live eval methodology: each scenario now uses a separate chat id to avoid history contamination.
  - Found and fixed alias leakage after exact lookup: when exact matches exist, similar alias results are not sent to the model.
  - Saved final real-model report in `LIVE_DIALOG_EVALS.md`.
- Checks:
  - Local full pytest -> `47 passed`.
  - VPS focused pytest -> `16 passed`.
  - VPS live eval -> `22` scenarios, `22` without style flags, `0` manual style-review flags.
- Current assessment:
  - Real KIE responses are now materially closer to first-line manager wording.
  - Duplicate article flow asks for code/price instead of dumping all rows.
  - Remaining improvement candidates: make handoff answers for technical подбор warmer and tune multi-product answers to avoid overly dense two-line responses.

## Update 2026-05-17 (Live Tone Micro-Tuning)

- Status: completed and deployed
- Done:
  - Added shared `HUMAN_MANAGER_STYLE_RULES` to prompts.
  - Strengthened product-facts prompt with concrete examples for exact product, duplicate article, mixed lookup, technical comparison, подбор and order.
  - Added rule not to greet repeatedly in product replies.
  - Reworked direct complex handoff: подбор now explains which parameters are needed before transferring to a manager.
  - Sanitized model wording so handoff says `подключится к диалогу`, not `свяжется с вами`.
  - Added live scenarios L-023..L-027, including history-based checks.
  - Added support for scenario history in live eval.
  - Added history-aware lookup for follow-up questions like `цена 132` after duplicate article clarification.
- Checks:
  - Local full pytest -> `47 passed`.
  - Local dialog regression -> `OK=31 PARTIAL=0 FAIL=0`.
  - VPS focused pytest -> `16 passed`.
  - VPS live eval -> `27` scenarios, `27` without style flags, `0` manual style-review flags.
- Current assessment:
  - Product replies no longer repeatedly start with `Добрый день`.
  - Handoff wording is better for Jivo chat.
  - Duplicate article follow-up by price works in live eval.

## Update 2026-05-17 (Human Manager Tone)

- Status: completed locally
- Done:
  - Reworked main and product prompts so the assistant answers like a first-line AMIX manager, not like a technical bot/card parser.
  - Added strict no-markdown rules: no `**`, no backticks, no markdown tables, no dry field-card formatting.
  - Changed duplicate-article behavior: when one article maps to several products, the bot asks the client to уточнить код товара с сайта или цену instead of dumping all rows.
  - Updated programmatic fallback answers to match the same conversational style when LLM is unavailable.
  - Added outgoing reply sanitizer to strip common markdown markers and list prefixes before sending/storing customer-facing text.
  - Added regression guard against markdown marker leakage.
  - Updated tests that expected old dry wording.
- Checks:
  - `python -m pytest -q` -> `46 passed`.
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Next:
  - Commit/push and sync VPS, then test real Telegram wording with live LLM.

## Update 2026-05-17 (Style Comparison Report)

- Status: completed locally
- Done:
  - Ran the same 31 dialog scenarios against pre-style-change commit `a5e7ad8` and current code.
  - Kept `DIALOG_EVALS.md` intact and created separate report `DIALOG_STYLE_COMPARISON.md`.
  - Confirmed both versions stay functionally green: `OK=31 PARTIAL=0 FAIL=0`.
  - Confirmed style changed materially: dry field labels dropped from `37` to `0`; duplicate-article flow now asks for code/price instead of dumping all product rows.
- Next:
  - Commit/push this comparison report and optionally continue with live LLM wording tests.

## Update 2026-05-17 (Grouped Product Facts + Backend Actions)

- Status: completed and deployed
- Done:
  - Updated product facts prompt to understand grouped lookup results: `queries`, `results`/`per_query_results`, `summary`.
  - Added `backend_actions` context for product-answer generation so the model knows whether search and handoff were already executed.
  - Added explicit bans on internal/service wording in customer replies: demo-mode phrases, backend/tool names, `product_lookup_result`, `exact_matches`, `handoff_to_manager`.
  - Adjusted assistant flow so product lookup can happen before manager handoff when a message contains both product IDs and a manager request.
  - Improved compact article candidate handling so alias queries do not duplicate a successful exact match.
  - Added grouped-result and handoff regression scenarios T-026..T-031.
  - Regenerated `DIALOG_EVALS.md` in the human-readable format.
- Checks:
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
  - `python -m pytest -q` -> `46 passed`.
- Deployed:
  - Commit `06c3840` pushed to GitHub.
  - VPS `/root/amix` pulled to `06c3840`.
  - Server checks: focused pytest -> `17 passed`; dialog regression -> `OK=31 PARTIAL=0 FAIL=0`.
  - `amix-telegram-demo.service` restarted and verified `active/running`.
- Next:
  - Run live Telegram demo checks on the customer-facing scenarios and tune wording if real LLM output differs from regression fallback.

## Update 2026-05-17 (Prompt Encoding Fix)

- Status: completed locally
- Done:
  - Checked `llm/prompts.py` encoding after IDE showed `\u0418...` escapes.
  - Confirmed file is UTF-8, but product facts prompt text was actually corrupted into `????`.
  - Restored `PRODUCT_FACTS_RESPONSE_PROMPT` as readable Russian UTF-8 text.
  - Replaced literal `\u04xx` escape strings in `build_product_facts_messages` with normal Cyrillic.
  - Verified runtime files do not contain `????` or literal `\u04xx` prompt fragments.
- Checks:
  - Focused pytest -> `17 passed`.
  - Dialog regression -> `OK=31 PARTIAL=0 FAIL=0`.
  - Full pytest -> `46 passed`.
- Next:
  - Commit/push and sync VPS because this fixes runtime prompt text.

## Update 2026-05-16 (Dialog Eval Logging)

- Status: completed
- Done:
  - Added persistent markdown history file `DIALOG_EVALS.md` for dialog test runs.
  - Added scenario runner `scripts/run_dialog_eval.py` that logs:
    - customer turns,
    - LLM planner raw JSON/mode,
    - lookup call query and result preview,
    - final bot reply.
  - First smoke-run recorded in `DIALOG_EVALS.md`.
  - Regression check: `python -m pytest` -> `32 passed`.
- Next:
  - Run eval script on VPS with active KIE key to capture real LLM planner/function-call behavior in logs and markdown.
  - Sync latest commit to server and restart `amix-telegram-demo.service`.

## Update 2026-05-16 (Backend-First Search + Tools)

- Status: completed
- Done:
  - Replaced planner-centric flow with backend-first lookup in `AssistantService`.
  - Added structured search result object in `database/repositories.py` via `search_products_structured(...)` with statuses:
    `exact_found`, `multiple_exact`, `similar_found`, `not_found`, `invalid_query`.
  - Added two explicit tool schemas in `llm/tool_schemas.py`:
    `search_products`, `handoff_to_manager`.
  - Rebuilt prompts to single main role + product-facts response:
    `SYSTEM_PROMPT`, `PRODUCT_FACTS_RESPONSE_PROMPT` in `llm/prompts.py`.
  - Refactored `llm/openai_client.py` to support tool-call parsing for OpenAI/KIE chat-completions style responses.
  - Added formal spec files:
    - `docs/LLM_IMPLEMENTATION_SPEC.md`
    - `docs/PROMPTS_AND_TOOLS_REFERENCE.md` (full snapshot of prompts/tools).
  - Updated and expanded tests under new architecture.
  - Regression: `python -m pytest -q` -> `34 passed`.
- Next:
  - Deploy this branch to VPS and run dialog eval with active KIE API key to verify real tool-calling behavior in runtime logs.

## Update 2026-05-16 (Duplicate Articles + Multiword Article Fix)

- Status: completed and deployed
- Done:
  - Fixed XML import upsert logic: products with a new `code` no longer collapse into an existing row only because `normalized_article` matches.
  - Rewrote article normalization/extraction in valid UTF-8.
  - Added multiword article extraction for values like `7843 silk brash`.
  - Preserved split-prefix matching for values like `МП 28ск`.
  - Reimported local `prices.xml`; duplicate article rows are restored locally.
  - Verified locally:
    - `МП 28ск` -> `multiple_exact`, 3 exact rows: `26167`, `26168`, `26169`.
    - `7843 silk brash` -> exact rows, no similar fallback.
  - Regression: `python -m pytest -q` -> `37 passed`.
- Deployed:
  - Commit `8b8255a` pushed to GitHub.
  - VPS `/root/amix` pulled to `8b8255a`.
  - Server XML reimported: `processed=6904 created=1464 updated=5440 errors=0`.
  - Server checks: `МП 28ск` -> 3 exact rows; `7843 silk brash` -> exact row; Telegram demo service active/running.
- Next:
  - Re-test live Telegram dialog from the user account and inspect `journalctl` logs if the LLM wording still needs tuning.

## Update 2026-05-16 (Final TZ Alignment Check)

- Status: completed locally
- Done:
  - Rechecked the final target logic: first-line manager, company Q&A, product lookup only via SQLite/search, complex questions via handoff.
  - Found one gap: complex questions in LLM-enabled mode relied mostly on model tool choice instead of backend rule.
  - Fixed backend handoff guard for подбор/аналог/совместимость/отличия/оформление заказа.
  - Narrowed handoff keywords so ordinary company questions like phone/address/order pickup are not forced to manager.
  - Regression: `python -m pytest -q` -> `39 passed`.
- Next:
  - Commit/push and sync VPS.

## Текущий статус

LLM-слой работает через `kie.ai` с моделью `gpt-5-2`, реальный XML AMIX `prices.xml` уже импортирован локально и на VPS, а Telegram demo service запущен на сервере и использует ту же SQLite-базу с `5440` товарами. Ближайший рабочий фокус теперь смещается с инфраструктуры на демонстрационный прогон и последующую Jivo-интеграцию с реальными payload.

## Этапы MVP

1. Подготовка каркаса проекта.
   Статус: completed.
   Состав: `PLAN.md`, `OPERATIONS.md`, структура каталогов, `main.py`, конфигурация, `.env.example`, `.gitignore`, Docker-файлы, базовые зависимости.
2. Интеграция входящего webhook Jivo и идемпотентной обработки событий.
   Статус: completed.
   Состав: быстрый ACK, сохранение сырого события, защита от дублей, фоновая обработка.
3. База данных и история диалогов.
   Статус: in progress.
   Состав: SQLite-модели, чаты, сообщения, статусы, handoff, ошибки обработки.
4. XML-импорт и поиск товаров.
   Статус: completed.
   Состав: парсинг XML, нормализация артикулов, upsert товаров, поиск точного и похожих артикулов.
5. OpenAI-слой и сценарии ответа.
   Статус: completed.
   Состав: безопасный prompt, диалоговый ответ без выдумывания фактов, вызов product lookup перед LLM-ответом.
9. Интеграция внешнего LLM-провайдера KIE.
   Статус: completed.
   Состав: изучение документации, env-конфигурация, поддержка `chat/completions`, тестовые live-запросы.
6. Передача менеджеру и дополнительные уведомления.
   Статус: completed.
   Состав: `INVITE_AGENT`, обработка `AGENT_UNAVAILABLE`, опциональные Telegram-уведомления.
7. Локальная проверка, тесты и подготовка к VPS.
   Статус: completed.
   Состав: pytest, скрипты симуляции, Docker, README, финальная сверка `.env` и `.gitignore`.
8. Telegram demo для предпросмотра заказчиком.
   Статус: completed.
   Состав: long polling bot, reuse SQLite/history/product lookup, demo-handoff сценарий, VPS-friendly runner.

## Уже сделано

- Изучен `AGENTS.md`.
- Подтверждена архитектурная схема: Jivo webhook -> быстрый ACK -> фон -> SQLite/OpenAI/XML -> ответ или handoff.
- Проверена актуальная документация Jivo Bot API.
- Созданы `README.md`, `.env.example`, `.gitignore`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`.
- Реализован `main.py` и базовые роуты `health` и Jivo webhook.
- Добавлены SQLite-модели, репозитории и логика сохранения событий/сообщений.
- Добавлены каркасы Jivo client, OpenAI client, Telegram notifier, XML importer и product search.
- Добавлены тесты критичных утилит и базовых сценариев.
- Выполнена локальная проверка: импорт приложения проходит, `python -m pytest` -> `8 passed`.
- По официальной документации Jivo уточнены входящие поля `site_id`, `channel`, `sender.url`, `sender.has_contacts`, `message.buttons` и жизненный цикл `AGENT_JOINED`.
- Терминальные статусы чата разделены на `agent_joined` и `closed`.
- Добавлены интеграционные tests для webhook: invalid token, дедупликация event, product lookup flow, handoff flow, `AGENT_JOINED` flow.
- Выполнена повторная локальная проверка: `python -m pytest` -> `13 passed`.
- Усилен `ProductXmlImporter`:
  - добавлены поля результата `status`, `skipped`, `errors`, `error_text`;
  - добавлена обработка missing-file/not-a-file;
  - добавлена fail-safe обработка `ElementTree.ParseError` с фиксацией failed import в БД;
  - добавлена защита по записям: ошибка одной записи не валит весь импорт.
- Обновлён `scripts/import_xml.py`:
  - расширен вывод итогов импорта;
  - возвращается `exit code 1` при failed-статусе или некорректном пути.
- Добавлены тесты `tests/test_xml_importer.py` для success/update, parse-fail и skipped-case.
- Выполнена повторная проверка: `python -m pytest` -> `16 passed`.
- Добавлен общий `core/assistant_service.py` для текстовой обработки сообщений вне привязки к Jivo transport.
- `core/message_processor.py` переведён на reuse общего assistant layer.
- Добавлен Telegram demo runtime:
  - `notifications/telegram_demo_bot.py`;
  - `scripts/run_telegram_demo.py`;
  - `deploy/amix-telegram-demo.service`.
- Добавлены тесты `tests/test_assistant_service.py`.
- Выполнена повторная проверка: `python -m pytest` -> `19 passed`.
- Выполнено первичное SSH-обследование VPS:
  - каталог `/root/amix` пуст;
  - на сервере есть `python3`, `git`, `systemd`;
  - на сервере пока нет `pip` и `docker`.
- На VPS выполнено:
  - установка `python3-pip` и `python3-venv`;
  - clone репозитория в `/root/amix`;
  - создание `.venv` и установка `requirements.txt`;
  - создание `/root/amix/.env` из `.env.example`;
  - установка systemd unit `amix-telegram-demo.service`.
- Изучена документация KIE по модели `gpt-5-2` и интеграции `chat/completions`.
- Текущий LLM-клиент поддерживает два провайдера: `openai` и `kie`.
- Добавлены env-настройки `LLM_PROVIDER`, `KIE_API_KEY`, `KIE_API_BASE_URL`, `KIE_CHAT_MODEL_PATH`, `KIE_REASONING_EFFORT`, `KIE_ENABLE_WEB_SEARCH`.
- Выполнены тестовые запросы к KIE:
  - через новый LLM-слой проекта;
  - прямым raw HTTP-запросом по документации.
- Raw-проверка KIE вернула `HTTP 200` и ответ `OK`, что подтверждает рабочий ключ и корректный endpoint.
- Реальный XML AMIX скопирован в `data/incoming_xml/prices.xml` и изучен:
  - корневой тег `КоммерческаяИнформация`;
  - записи лежат в `record`;
  - фактические поля: `Код`, `Артикул`, `ЦенаКорпоративная`, `ЦенаРозничная`, `ЕдиницаИзмерения`, `Вес`, `Объем`, `СвободныйОстаток`;
  - объём файла: `6904` записей.
- Исправлен production-баг в XML importer:
  - добавлены реальные алиасы `ценакорпоративная` и `ценарозничная`;
  - `scripts/import_xml.py` теперь сам создаёт таблицы перед импортом.
- Реальный XML импортирован локально:
  - `processed=6904`, `created=5440`, `updated=1464`, `errors=0`;
  - после исправления алиасов повторный импорт дал `updated=6904`;
  - в локальной базе заполнились `5353` розничных и `5337` корпоративных цен.
- Усилены guardrails assistant layer:
  - если клиент спрашивает цену/наличие без артикула, бот просит прислать артикул;
  - если артикул не найден, бот честно сообщает об этом и предлагает менеджера для подбора;
  - prompt уточнён под реальные пределы базы AMIX.
- Добавлены тесты:
  - на запрос цены/наличия без артикула;
  - на missing-article сценарий;
  - на импорт реальных русских тегов цен;
  - на нормализацию артикулов с кириллическими суффиксами.
- Выполнена повторная проверка: `python -m pytest` -> `24 passed`.
- Локальный блок автоматически зафиксирован в GitHub:
  - commit: `c50b719`
  - message: `Refine AMIX XML import and assistant guardrails`
- VPS синхронизирован с commit `c50b719`.
- На VPS выполнено:
  - `git pull --ff-only` в `/root/amix`;
  - загрузка `prices.xml` в `/root/amix/data/incoming_xml/prices.xml`;
  - обновление серверного `.env` с рабочим `TELEGRAM_BOT_TOKEN`;
  - импорт `prices.xml` в серверную SQLite;
  - включение и запуск `amix-telegram-demo.service`.
- Состояние Telegram demo на VPS:
  - systemd unit `amix-telegram-demo.service` — `enabled`;
  - сервис — `active/running`;
  - серверная база содержит `5440` товаров и `5353` розничных цен.
- Валидность Telegram bot token подтверждена через `getMe`; bot username: `testdemoNN_bot`.
- Исправлен поиск артикулов из "грязного" пользовательского ввода:
  - восстановлена корректная unicode-нормализация `article_utils`;
  - добавлен поиск по раскладочным вариантам (кириллица/латиница) в `get_product_by_article`/`get_similar_products`;
  - добавлена склейка короткого префикса с числовым токеном для запросов вида `МП 28ск`.
- На локальной базе подтверждены проблемные кейсы из демо-чата:
  - `ОЗ/700` теперь находит точный артикул и возвращает цену/остаток;
  - `МП 28ск` теперь находит точный артикул и возвращает цену/остаток.
- Выполнена проверка: `python -m pytest` -> `29 passed`.

## Что осталось сделать

- Уточнить реальные payload-структуры Jivo на стенде и скорректировать схемы/обработчик.
- Проверить реальные исходящие вызовы `BOT_MESSAGE` и `INVITE_AGENT` против рабочего endpoint Jivo.
- Довести OpenAI routing: отделить intent detection от генерации ответа и добавить явные guardrails для сложных консультаций.
- Проверить живой Telegram demo на сервере и подготовить ссылку/инструкцию для показа заказчику.
- Подготовить тестовый прогон с заказчиком через `@testdemoNN_bot`.
- Синхронизировать фиксы поиска артикулов на VPS и перезапустить `amix-telegram-demo.service`.
- Фиксы поиска артикулов уже синхронизированы на VPS (`ce33417`), `amix-telegram-demo.service` перезапущен и работает.

## Открытые вопросы

- Нужны реальные примеры payload Jivo, особенно для событий после handoff и недоступности агента.
- Нужно подтвердить фактический формат исходящего webhook URL Jivo для конкретного bot channel.
- Нужно понять, достаточно ли `BackgroundTasks` для пилота AMIX или нужен более надёжный local queue/worker уже на MVP-этапе.
- Нужно определить допустимую политику повторных импортов одного и того же файла (по checksum/mtime) для production-режима.
- Нужен сценарий выдачи заказчику доступа к Telegram demo: какой именно бот и какие тестовые чаты использовать.
- Нужен понятный тестовый Telegram-чат/аккаунт, на котором заказчику будут показывать демо.

## Технические риски

- Публичная Bot API-документация Jivo не описывает все возможные входящие события одинаково подробно.
- `BackgroundTasks` подходит для MVP, но не даёт надёжной очереди при падении процесса.
- Без sandbox-стенда Jivo пока невозможно полноценно подтвердить формат реальных исходящих payload и handoff-ответов.
- Без OpenAI API key демо останется только на product lookup и безопасном fallback без полноценного диалога.
- Если KIE API изменит формат `chat/completions`, потребуется скорректировать адаптер провайдера.

## Ближайший следующий шаг

Проверить живой диалог через `@testdemoNN_bot`, затем вернуться к следующему продуктному блоку: реальные Jivo payload и боевой `BOT_MESSAGE`/`INVITE_AGENT` flow.

## Обновление 2026-05-16

- Запущен переход на LLM-first чат-логику:
  - сначала LLM строит plan (`lookup`/`clarify`/`handoff`);
  - backend вызывает lookup-функцию БД по артикулу/коду;
  - финальный ответ клиенту формируется LLM по фактам функции.
- Добавлена функция `lookup_products()` с поддержкой:
  - exact по `code`;
  - exact по `normalized_article` (включая варианты раскладки);
  - similar-выдачи для уточнения.
- Промпты разделены по ролям:
  - planner prompt;
  - facts-response prompt.
- Сохранен аварийный legacy fallback только на случай недоступности LLM.
- Проверки: `python -m pytest` -> `30 passed`.

## Обновление 2026-05-16 - диалоговая регрессия

- Зафиксирован набор из 25 сценариев проверки поведения бота в `tests/dialog_eval_cases.json`.
- Добавлен автоматический прогон сценариев `scripts/run_dialog_regression_eval.py` с записью результата в `DIALOG_EVALS.md`.
- Добавлены pytest-проверки `tests/test_dialog_regression.py` для критичных кейсов:
  - точный поиск по артикулу и коду;
  - несколько товаров на один артикул;
  - точное совпадение главнее похожих;
  - грязный ввод артикула;
  - общие вопросы компании без поиска по товарам;
  - handoff для технических вопросов и оформления заказа.
- `AssistantService` приведён к backend-first товарной логике:
  - если в сообщении есть артикул/код, backend сам делает `search_products_structured` до ответа;
  - LLM получает результат поиска как факты и не должна придумывать товарные данные;
  - оформление заказа сначала проверяет остаток, затем передаёт менеджеру;
  - при недостаточном остатке бот сообщает факт и предлагает менеджера.
- Проверки:
  - `python -m pytest -q` -> `41 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=25 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

Изменения с диалоговой регрессией синхронизированы с GitHub и VPS. Следующий шаг: проверить живой Telegram demo на пользовательских сценариях из `DIALOG_EVALS.md` и отдельно пройти реальные вопросы заказчика в чате.

## Обновление 2026-05-16 - ужесточение регрессии

- Доработаны замечания по завышенному `OK` в отчёте:
  - приветствие стало обычным менеджерским ответом;
  - handoff-тексты больше не содержат фразы про демо-режим;
  - multi-query поиск теперь суммирует результаты по всем запросам;
  - сравнение двух артикулов сначала ищет оба товара, потом передаёт менеджеру;
  - `p am02 b s` теперь находится как exact compact match для `P-AM02/B-S`;
  - автопроверка запрещает пользовательские фразы `в демо-режиме`, `в рабочем режиме я бы`, `этот вопрос требует менеджера`.
- Проверки:
  - `python -m pytest -q` -> `44 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=25 PARTIAL=0 FAIL=0`.

## Обновление 2026-05-17 - уточнения товара и live semantic checks

- Доработана live-проверка смысловых ошибок, а не только стиля:
  - контактный вопрос должен содержать телефон/email;
  - вопрос только по наличию не должен автоматически показывать цены;
  - уточнение дубля по цене должно выбрать позицию, а не повторно просить код/цену;
  - цены не должны округляться;
  - shortage-сценарии не должны звучать как готовое оформление заказа.
- Для товарных уточнений добавлена backend-упаковка контекста без отдельного tool:
  - если клиент после `multiple_exact` пишет `цена 132`, backend передаёт LLM выбранную exact-позицию только при единственном совпадении по цене/коду;
  - если клиент спрашивает только наличие по одному товару, цены не передаются в LLM-контекст, чтобы бот не перегружал ответ.
- Проверки:
  - локально `python -m pytest -q` -> `64 passed`;
  - локально `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`;
  - VPS `python -m pytest -q` -> `64 passed`;
  - VPS live eval через KIE -> `31` сценарий, `31` без style flags, `31` без content flags.

## Ближайший следующий шаг

Перейти от одиночных live-сценариев к multi-turn сценариям: 2-4 сообщения клиента подряд с проверкой, что бот использует историю, предыдущий ответ и предыдущие результаты поиска без лишних повторных уточнений.

## Обновление 2026-05-18 - Telegram reset-команда

- Для ручного тестирования Telegram demo добавлена одна команда сброса контекста: `/newchat`.
- Команда очищает сообщения текущего Telegram-чата и handoff-записи, переводит чат обратно в `active`.
- При старте Telegram demo бот регистрирует команды меню через Telegram `setMyCommands`: `/start`, `/help`, `/newchat`.
- Проверки:
  - `python -m pytest -q` -> `66 passed`.

## Ближайший следующий шаг

Проверить `/newchat` в живом Telegram-чате, затем продолжить ручные multi-turn проверки уже без накопленного старого контекста.

## Обновление 2026-05-18 - LLM debug logs и уточнение цены

- Добавлены LLM debug-логи в `data/logs/llm_debug.jsonl`.
- Логируются:
  - стадия вызова (`llm_direct_request`, `product_facts_request`, `product_facts_response`, `llm_tool_call_result`);
  - `messages` с ролями, которые реально уходят в модель;
  - `transcript`, `product_lookup_result`, `backend_actions`;
  - ответ модели и tool calls.
- Исправлено распознавание уточнений вида `198 которая стоит` / `которая стоит 198` как выбора предыдущей позиции по цене.
- Проверки:
  - `python -m pytest -q` -> `68 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

После деплоя проверить живой Telegram-диалог с `/newchat`, затем задать `есть мп 28ск` и `198 которая стоит`; если ответ снова будет неверным, смотреть свежие строки `data/logs/llm_debug.jsonl`.

## Обновление 2026-05-18 - role-based LLM context

- Перестроена сборка LLM-запроса:
  - история больше не передаётся одним текстовым блоком `История диалога`;
  - последние сообщения идут как отдельные role-objects `user`, `assistant`, `tool`;
  - последнее сообщение клиента не дублируется отдельным блоком.
- Добавлен `INTERNAL_CONTEXT_JSON`:
  - `active_product`;
  - `last_product_lookup`;
  - `pending_clarification`;
  - настройки показа цен и handoff;
  - текущий канал `telegram_test`/`jivo`.
- Обновлён tool flow:
  - assistant tool call сохраняется в историю;
  - результат `search_products` сохраняется как `role=tool`;
  - Kie payload сохраняет `tool_calls`, `tool_call_id` и `name`.
- Пересобран `SYSTEM_PROMPT`:
  - убраны дубли;
  - добавлены правила по `всм`, `я спросил же`, скидкам, active product, наличию без цены и уточнениям после дублей.
- Обновлены schemas:
  - `search_products` получил `intent`, `use_dialog_context`, `context_note`, `requested_quantity`;
  - `handoff_to_manager` получил enum причин и `customer_message`.
- Проверки:
  - `python -m pytest -q` -> `71 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

После деплоя на VPS запустить live-прогон через реальную модель, обновить `LIVE_DIALOG_EVALS.md`, затем проверить в Telegram сценарии: `скидки есть?`, `всм`, `я спросил же скидки есть?`, `есть мп 28ск -> цена 132/198`.

## Обновление 2026-05-18 - live flags cleanup

- После первого VPS live-прогона role-based контекста обнаружены и исправлены:
  - общий вопрос по доставке иногда уходил в LLM и мог получить приветствие вместо ответа;
  - товарный ответ по коду мог содержать сухие поля с двоеточиями;
  - уточнение дубля по цене выбирало позицию, но могло не назвать код товара.
- Добавлен backend FAQ для базовых вопросов компании.
- Добавлена пост-обработка ответа:
  - убрать сухие price-label двоеточия;
  - добавить `Код товара ...` после resolved follow-up refinement.
- Проверки:
  - `python -m pytest -q` -> `74 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

Задеплоить правки, повторно прогнать live eval на VPS и проверить в Telegram сценарии со скидкой и уточнением дубля.

## Обновление 2026-05-18 - повторный live eval после cleanup

- Правки задеплоены на VPS commit `e777179`.
- Серверные проверки:
  - `.venv/bin/python -m pytest -q` -> `74 passed`;
  - `amix-telegram-demo.service` -> `active`.
- Повторный live-прогон через Kie:
  - сценариев: `31`;
  - без style flags: `31`;
  - без content flags: `31`;
  - на ручную проверку: `0`.
- `LIVE_DIALOG_EVALS.md` обновлён новым отчётом.

## Ближайший следующий шаг

Проверить вручную в Telegram через `/newchat`: сценарий со скидкой после товара, `всм`, `я спросил же скидки есть?`, `есть мп 28ск -> цена 132/198`.

## Обновление 2026-05-18 - cleanup LLM payload

- Уточнена схема product/prelookup вызова:
  - полный результат текущего поиска больше не дублируется в `INTERNAL_CONTEXT_JSON`;
  - compact state остаётся в `dialog_state.last_product_lookup`;
  - полный результат backend-prelookup передаётся только в `TOOL_RESULTS_JSON`;
  - `TOOL_RESULTS_JSON` теперь добавляется после role-based истории и текущего `user`.
- Разделены режимы на уровне payload:
  - backend-prelookup используется как final-answer request без tools;
  - настоящий tool-flow остаётся через `assistant.tool_calls` и `role=tool`.
- Обновлён Kie payload:
  - `temperature=0.6`;
  - `top_p=1`;
  - `parallel_tool_calls=false`;
  - `stream=false`;
  - `stream_options` проект не отправляет.
- Добавлены phase-логи:
  - `llm_request_started`;
  - `llm_response_received`;
  - `message_send_started`;
  - `message_sent_to_user`;
  - `message_send_failed`;
  - `error_after_send` для ошибок после отправки ответа при handoff.
- Проверки:
  - `python -m pytest -q` -> `74 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

Задеплоить cleanup payload на VPS, прогнать live eval через Kie и проверить свежий Kie payload: compact `INTERNAL_CONTEXT_JSON`, отдельный `TOOL_RESULTS_JSON` после истории, `stream=false` без `stream_options`.

## Обновление 2026-05-18 - VPS sync после Kie payload cleanup

- GitHub/VPS:
  - отправлен commit `8fd2e45` с cleanup LLM payload;
  - отправлен commit `d5514fe` с `temperature=0.6` и удалением `max_completion_tokens`;
  - `/root/amix` на VPS обновлён до `d5514fe`;
  - серверный `.venv/bin/python -m pytest -q` -> `74 passed`;
  - `amix-telegram-demo.service` перезапущен и проверен: `active/running`;
  - на VPS подтверждено: `kie_temperature=0.6`, `kie_max_completion_tokens` отсутствует.

## Ближайший следующий шаг

Проверить живой Telegram-диалог и свежие Kie logs: payload должен содержать `temperature=0.6`, не содержать `max_completion_tokens`, а full lookup должен быть только в `TOOL_RESULTS_JSON`.

## Обновление 2026-05-18 - synthetic tool history и provider fallback

- Backend-prelookup теперь сохраняется в историю как synthetic tool-flow:
  - `assistant_tool_call` с `search_products`;
  - `role=tool` с JSON результата;
  - затем финальный `assistant`/bot ответ.
- `INTERNAL_CONTEXT_JSON` стал компактнее:
  - удалён `current_user_message`;
  - полный lookup больше не кладётся внутрь context;
  - добавлен `dialog_state.product_memory`;
  - `pending_clarification.allowed_clarifications` ограничен `code` и `retail_price`.
- Обновлены правила ответа:
  - убрать просьбы прислать ссылку/фото при дублях артикула;
  - при `stock_only` не показывать цены;
  - корпоративную цену показывать только по прямому запросу;
  - при provider timeout/rate-limit не отправлять стандартное приветствие.
- Kie-настройки:
  - `temperature=0.35`;
  - `stream=false`;
  - `stream_options` не отправляется;
  - добавлены connect/read timeout и retry budget.
- Добавлены live-сценарии:
  - память первого товара после смены темы;
  - `не понял` после уточнения;
  - цена без корпоративной;
  - дубль артикула без просьбы ссылки/фото.
- Проверки:
  - `python -m pytest -q` -> `80 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

Задеплоить правки на VPS и запустить live-прогон через Kie уже на расширенных `35` сценариях.

## Обновление 2026-05-18 - деплой synthetic tool history

- Правки задеплоены на VPS commit `63b15d3`.
- Серверные проверки:
  - `.venv/bin/python -m pytest -q` -> `80 passed`;
  - `amix-telegram-demo.service` -> `active/running`;
  - Kie runtime settings: `temperature=0.35`, `stream=false`, `max_completion_tokens` отсутствует.
- Полный live-прогон на VPS был запущен, но не завершился за 20 минут из-за долгого Kie running/provider состояния; процесс остановлен, чтобы не плодить зависшие задачи.
- Добавлен targeted режим `scripts/run_live_dialog_eval.py --case L-032 --case L-033 ...`.
- Targeted live-прогон `L-032`-`L-035`:
  - сценариев: `4`;
  - без style flags: `4`;
  - без content flags: `3`;
  - на ручную проверку: `1`.
- `L-032` упал не из-за приветственного fallback, а из-за `rate_limit_or_quota`: бот ответил безопасным provider-delay текстом. `L-033`, `L-034`, `L-035` прошли без content flags.

## Ближайший следующий шаг

Когда Kie перестанет отдавать `rate_limit_or_quota`, повторить полный live-прогон на `35` сценариях или отдельно перезапустить `L-032`, чтобы проверить память первого товара без provider error.

## Обновление 2026-05-18 - transcript/tool cleanup

- Найдена причина странных queries вроде `МП28СКINTENTPRODUCTINFO`: служебный `role=tool` JSON попадал в legacy transcript как текст бота.
- `get_transcript()` теперь отдаёт только реальные реплики клиента и финальные ответы бота.
- Kie failure body `status=failure`, `error_code=500`, `Server exception...` и пустой ответ теперь считаются retryable provider error, а не успешным пустым ответом.
- Follow-up `а есть мп дешевле?` теперь использует историю товара и backend prelookup.
- Fallback по `дешевле` теперь показывает варианты с кодами, ценами и остатком, если Kie недоступен.
- Проверки:
  - `python -m pytest -q` -> `83 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

Задеплоить fix на VPS, затем повторить Telegram-сценарий `/newchat -> есть мп 28ск -> 198 которая стоит -> сколько стоит 7843 silk brash -> а есть мп дешевле?` и проверить, что больше нет мусорных queries и обычного fallback.

## Обновление 2026-05-18 - Gemini endpoint

- KIE endpoint переключён на Gemini: `/gemini-3-pro/v1/chat/completions`.
- `stream` оставлен `false`, `include_thoughts` не включался, потому что сервис сейчас работает с обычным JSON-ответом и не должен логировать reasoning/thoughts.
- Проверки:
  - `python -m pytest -q` -> `83 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

Задеплоить Gemini endpoint на VPS, обновить серверный `.env`, перезапустить Telegram demo service и проверить в Kie logs, что path стал `/gemini-3-pro/v1/chat/completions`.

## Обновление 2026-05-18 - cleanup product follow-up queries

- Убрана опасная подстановка article candidates из полного transcript для коротких уточнений.
- `product_memory` теперь используется как контекст для модели, а не как источник backend search queries.
- Для уточнений вроде `198 которая` backend берёт последний pending multiple-exact lookup и при необходимости переищет только его артикул, без старых товаров и цен из истории.
- Если найдено точное совпадение, `similar_matches` вычищаются из LLM-visible результата, включая nested `results/per_query_results`.
- `role=tool` content для модели теперь компактный и русскоязычный; raw lookup остаётся только в payload БД для восстановления product memory.
- Цены форматируются с пробелами в тысячах, например `50 820 руб.`.
- Проверки:
  - `python -m pytest -q` -> `85 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

Задеплоить fix на VPS, проверить серверные тесты и перезапустить `amix-telegram-demo.service`.

## Обновление 2026-05-18 - deploy follow-up cleanup

- Commit `c3d5679` задеплоен на VPS в `/root/amix`.
- Серверные проверки:
  - `.venv/bin/python -m pytest -q` -> `85 passed`;
  - `amix-telegram-demo.service` -> `active/running`.

## Ближайший следующий шаг

Проверить новый Telegram/Kie сценарий: `есть мп 28ск -> 198 которая -> сколько стоит 7843 silk brash -> а есть мп дешевле?`, и убедиться в Kie payload, что больше нет stale queries `1108035`/`50820` на уточнении по МП.

## Обновление 2026-05-19 - real handoff action guard

- Исправлена live-проблема, где модель могла написать клиенту `Передаю вопрос менеджеру`, но в истории не было реального handoff-действия.
- Любой backend handoff теперь сохраняется как `assistant_tool_call` + `role=tool` с `handoff_to_manager`, включая Telegram demo mode.
- Если модель всё же вернула текст с обещанием передачи менеджеру без tool-call, backend фиксирует handoff сам с причиной `bot_uncertain`.
- После `handoff_requested` новые сообщения в этом чате больше не запускают обычный товарный сценарий; бот отвечает только `Менеджер уже вызван, он подключится к диалогу.`
- Промпты дополнены запретом обещать передачу менеджеру без `handoff_to_manager` или `backend_actions.handoff_to_manager_called=true`.
- Проверки:
  - `python -m pytest -q` -> `87 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

Задеплоить handoff guard на VPS, прогнать серверный pytest и перезапустить `amix-telegram-demo.service`.

## Обновление 2026-05-19 - deploy real handoff guard

- Commit `72f0795` задеплоен на VPS в `/root/amix`.
- Серверные проверки:
  - `.venv/bin/python -m pytest -q` -> `87 passed`;
  - `amix-telegram-demo.service` -> `active/running`.

## Ближайший следующий шаг

Проверить в Telegram сценарий `чем л отличается от пр? -> а 14.023пр сколько именно осталось? -> ну позови менеджера тогда`: после первого handoff бот должен отвечать только `Менеджер уже вызван, он подключится к диалогу.` и не запускать товарный поиск заново.

## Обновление 2026-05-19 - turn coalescing for fast consecutive messages

- До этой итерации логика отмены устаревшего LLM turn не была реализована:
  - Telegram polling блокировался на текущем `handle_client_message()` и не забирал новые updates до ответа LLM;
  - Jivo CLIENT_MESSAGE запускал обработку каждого event отдельно, без `active_turn/superseded`.
- Добавлен in-process `ChatTurnCoordinator`:
  - входящее сообщение сохраняется сразу;
  - ответ планируется с коротким debounce (`TURN_DEBOUNCE_SECONDS`, default `1.2`);
  - новое сообщение в том же чате увеличивает generation и делает старый turn устаревшим;
  - если старый LLM-запрос вернулся после нового сообщения, его ответ не сохраняется и не отправляется.
- `AssistantService` разделён на:
  - `record_client_message()` для немедленного сохранения user-сообщения;
  - `handle_pending_client_messages()` для ответа по всем user-сообщениям после последнего bot-ответа.
- Telegram demo теперь не блокирует polling на LLM: normal messages сохраняются и обрабатываются coordinator worker’ом.
- Jivo CLIENT_MESSAGE использует тот же coordinator; для Jivo delay принудительно не ниже `0.05s`, чтобы worker не стартовал до commit входящего event.
- Проверки:
  - focused pending/superseded/Jivo tests -> `7 passed`;
  - `python -m pytest -q` -> `89 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Ближайший следующий шаг

Задеплоить turn coalescing на VPS и проверить Telegram live: отправить два сообщения подряд до ответа бота, убедиться, что в Kie уходит один актуальный turn с двумя `user` сообщениями в истории, а старый ответ не приходит.

## Обновление 2026-05-19 - deploy turn coalescing

- Commit `b0c62d6` задеплоен на VPS в `/root/amix`.
- Серверные проверки:
  - `.venv/bin/python -m pytest -q` -> `89 passed`;
  - `amix-telegram-demo.service` -> `active/running`.

## Ближайший следующий шаг

Проверить live в Telegram: отправить два сообщения подряд быстрее ответа бота. Ожидаемо должен прийти только один финальный ответ по последнему актуальному turn, без старого ответа от первого LLM-запроса.

## Обновление 2026-05-19 - direct Google AI Studio provider

- Статус: completed and deployed.
- Цель:
  - добавить прямой LLM-провайдер Google AI Studio/Gemini API через OpenAI-compatible `chat/completions`;
  - оставить Kie-интеграцию в коде и конфиге как быстрый fallback через `LLM_PROVIDER=kie`;
  - переключить VPS на новый provider через `.env`, не сохраняя ключи в репозитории;
  - протестировать реальный запрос именно на VPS.
- Важные ограничения:
  - `gemini-3-pro-preview` по официальной документации уже выключен;
  - актуальная Pro-замена должна быть настраиваемой через `GOOGLE_AI_MODEL`;
  - если Free tier не пропускает Pro-модель, переключить runtime на доступную модель и зафиксировать результат проверки.
- Сделано:
  - добавлен `LLM_PROVIDER=google_ai_studio` для прямого Google AI Studio/Gemini API;
  - Kie-интеграция оставлена в коде и `.env.example`, возврат делается через `LLM_PROVIDER=kie`;
  - VPS `/root/amix` обновлён до commit `a434d96`;
  - серверный `.env` переключён на `google_ai_studio`, ключ хранится только на VPS;
  - runtime-модель на VPS: `gemini-3-flash-preview`.
- Проверки:
  - локально `python -m pytest -q` -> `90 passed`;
  - локально `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`;
  - VPS `.venv/bin/python -m pytest -q` -> `90 passed`;
  - VPS smoke direct Google chat completion -> `error_type=None`;
  - VPS smoke tool-call -> `search_products` parsed successfully;
  - `amix-telegram-demo.service` -> `active/running`.

## Обновление 2026-05-19 - LLM audit log

- Статус: in progress.
- Цель:
  - хранить последние `LLM_AUDIT_LOG_MAX_ENTRIES` реальных LLM provider-вызовов в `data/logs/llm_audit_recent.json`;
  - писать полный JSON запроса, raw JSON ответа, latency, usage tokens и примерную стоимость в USD/RUB;
  - не писать API-ключи в audit-файл;
  - дать удобный просмотр через `python scripts/show_llm_audit.py --limit 20`.
- Локальные проверки:
  - `python -m pytest tests\test_llm_client.py -q` -> `7 passed`;
  - `python -m pytest -q` -> `91 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- VPS:
  - `.env` дополнен audit-настройками;
  - `.venv/bin/python -m pytest -q` -> `91 passed`;
  - smoke direct Google request записал retryable `503` attempt и последующий successful attempt;
  - cost estimate учитывает Gemini thinking tokens через `total_tokens - prompt_tokens`;
  - `scripts/show_llm_audit.py` используется для просмотра последних записей.

## Обновление 2026-05-20 - МП/ОЗ и вопросы по весу

- Статус: in progress.
- Причина:
  - в live-диалоге вопрос `МП/ОЗ у него какая масса?` был ошибочно привязан к предыдущему товару `26141` / `1108035`;
  - backend не распознал `МП/ОЗ` как явный артикул, потому что старое извлечение артикулов требовало наличие цифр;
  - из-за этого LLM получила lookup по `1108035`, где вес пустой, и ответила, что веса нет.
- Сделано локально:
  - `extract_article_candidates` теперь принимает явные артикулы без цифр, если это короткий слэш-формат вроде `МП/ОЗ`;
  - обычные слова со слэшем/дефисом без товарного формата не превращаются в поиск;
  - compact product memory теперь сохраняет `weight` и `volume`;
  - programmatic fallback по вопросам веса показывает вес по найденным позициям, включая несколько точных вариантов;
  - sanitizer убирает фразу про "воспользоваться поиском" и заменяет "база данных" на "текущие данные".
- Проверки:
  - `PYTHONPATH=. python -m pytest tests/test_article_utils.py tests/test_assistant_service.py -q` -> `60 passed`;
  - `PYTHONPATH=. python -m pytest -q` -> `101 passed`.
- Ближайший следующий шаг:
  - live-проверка в Telegram: повторить сценарий `26141 какая цена` -> `МП/ОЗ у него какая масса?` и убедиться, что ответ строится по `МП/ОЗ`, а не по `1108035`.
- VPS:
  - `/root/amix` обновлён до commit `c008d45`;
  - `.venv/bin/python -m pytest -q` -> `101 passed`;
  - `amix-telegram-demo.service` перезапущен и активен;
  - серверная проверка `search_products_structured("МП/ОЗ")` -> `multiple_exact`, 20 точных позиций;
  - серверная проверка fallback по весу выводит коды и веса позиций `МП/ОЗ`.

## Обновление 2026-05-20 - защита follow-up и новых безцифровых артикулов

- Статус: in progress.
- Причина:
  - live-диалог показал, что `который 194р стоит` был ошибочно обработан как новый поиск `194р`, а не как уточнение предыдущего списка `МП/ОЗ`;
  - `МП ЦК белая она сколько весит` не распознавалось как новый товарный запрос, и backend подставлял предыдущий `МП/ОЗ`;
  - модель смогла вывести коды `27790-27793`, которых не было в текущем tool-result, то есть нарушила фактологический контур.
- Сделано локально:
  - короткая цена с суффиксом `р/руб/₽` теперь считается уточнением предыдущего списка;
  - добавлен извлекатель named product query для фраз вроде `МП ЦК белая`;
  - добавлен guard: если LLM-ответ упоминает код товара, которого нет в lookup-result, ответ заменяется безопасным programmatic fallback;
  - добавлены регрессионные тесты на все три сценария.
- Проверки:
  - `PYTHONPATH=. python -m pytest tests/test_assistant_service.py tests/test_article_utils.py -q` -> `65 passed`;
  - `PYTHONPATH=. python -m pytest -q` -> `106 passed`.
- VPS:
  - `/root/amix` обновлён до `bb5495a`;
  - `.venv/bin/python -m pytest -q` -> `106 passed`;
  - `МП ЦК белая` на серверной базе находится как код `28834`, вес `0.538`;
  - `amix-telegram-demo.service` активен.

## Обновление 2026-05-20 - Google tool history log shape

- Статус: in progress.
- Причина:
  - Google Logs подтвердили, что `assistant.tool_calls` + `role=tool` отображаются хронологически как `functionCall` и `functionResponse`;
  - `system`-сообщения с `TOOL_RESULTS_JSON` отображаются в `systemInstruction`, поэтому они хуже подходят для хронологической истории;
  - серверный audit показал HTTP 400: Google отклоняет финальный запрос, который заканчивается на `functionResponse`, с ошибкой про отсутствующий `thought_signature` у `functionCall`;
  - успешный log-shape тест имел дополнительное user-сообщение после `functionResponse`, и прямой серверный повтор подтвердил, что такая форма проходит HTTP 200.
- Сделано локально:
  - для Google AI Studio добавлена неперсистентная финальная user-инструкция после последнего `role=tool`;
  - tool history остается в payload хронологически, без возврата к `TOOL_RESULTS_JSON` как основному формату;
  - добавлен тест на payload, который заканчивается tool result.
- Проверки:
  - `PYTHONPATH=. pytest tests/test_llm_client.py::test_google_ai_studio_payload_preserves_tool_role_history tests/test_llm_client.py::test_google_ai_studio_payload_appends_final_instruction_after_tool_result -q` -> `2 passed`.
  - `PYTHONPATH=. pytest -q` -> `113 passed`.
  - VPS direct Google shape tests: `functionResponse` last -> HTTP 400, `functionResponse` + user instruction -> HTTP 200.
- VPS:
  - `/root/amix` обновлён до commit `b46dd4e`;
  - `.venv/bin/python -m pytest -q` -> `113 passed`;
  - `amix-telegram-demo.service` перезапущен и активен;
  - smoke через `AssistantService` после tool call завершился HTTP 200, финальный payload содержит `assistant -> tool -> user final instruction`.

## Обновление 2026-05-20 - восстановление товара 14.023пр на VPS

- Статус: completed.
- Причина:
  - live-лог показал корректный вызов функции с query `14.023пр`, но функция вернула `не_найдено`;
  - на сервере у товара `code=770` поля поиска были повреждены как `14.023??.`, `14023??`, `??`.
- Сделано:
  - восстановлены поля `article`, `normalized_article`, `unit` для `code=770` и контрольной пары `code=769`;
  - проверены Unicode-кодпоинты, чтобы исключить визуальную ошибку терминала;
  - подтверждено, что `_search_products_by_queries(["14.023пр", "xyz-999"])` возвращает `exact_found` по `14.023пр` и `not_found` по `xyz-999`.

## Обновление 2026-05-31 - минимальная админ-страница базы товаров

- Статус: completed locally.
- Цель:
  - добавить простую светлую одностраничную панель без отдельных разделов, логов и таблиц;
  - оставить только статус, несколько кратких показателей, скачивание текущей базы и загрузку новой XML-выгрузки.
- Сделано:
  - добавлен защищённый Basic Auth endpoint `/admin`;
  - добавлен XML-экспорт текущих товаров через `/admin/products.xml`;
  - добавлена загрузка XML через `/admin/products/import` с сохранением файла в `data/incoming_xml/` и запуском существующего `ProductXmlImporter`;
  - добавлены настройки `ADMIN_USERNAME` и `ADMIN_PASSWORD`;
  - интерфейс сделан светлым, с ограниченной шириной контента и мобильной адаптацией.
- Проверки:
  - `python -m pytest tests/test_admin_panel.py -q` -> `4 passed`;
  - `python -m pytest -q` -> `117 passed`.
- Следующий шаг:
  - проверить страницу пользователем по адресу VPS;
  - после появления домена и Jivo настроить nginx/HTTPS и закрыть прямой порт, если потребуется.
- VPS:
  - `/root/amix` обновлён до commit `3eb1b8d`;
  - `ADMIN_PASSWORD` задан в серверном `.env` без записи в Git;
  - создан и запущен `amix-api.service` на порту `8010`;
  - `/admin` проверен снаружи: без авторизации `401`, с Basic Auth `200`.

## Обновление 2026-05-31 - cookie login для админки

- Статус: deployed on VPS.
- Цель:
  - убрать встроенное браузерное окно Basic Auth;
  - сделать отдельную страницу `/admin/login` с вводом пароля;
  - сохранять вход в cookie, чтобы пользователь не вводил пароль каждый раз на том же устройстве;
  - заменить системную кнопку выбора файла на кастомную область "Выберите файл или перенесите сюда".
- Сделано:
  - `/admin` без сессии теперь редиректит на `/admin/login`;
  - `/admin/login` принимает только пароль, без логина;
  - после правильного пароля ставится signed HttpOnly cookie `amix_admin_session` на 30 дней;
  - добавлен `/admin/logout`;
  - загрузка XML оформлена как drag-and-drop/file зона без нативной системной кнопки.
- Проверки:
  - `python -m pytest tests/test_admin_panel.py -q` -> `6 passed`;
  - `python -m pytest -q` -> `119 passed`;
  - локально через Playwright сняты и проверены скриншоты `/admin/login` и `/admin`;
  - на VPS `.venv/bin/python -m pytest tests/test_admin_panel.py -q` -> `6 passed`;
  - снаружи проверено: `/admin` без cookie редиректит на `/admin/login`, после ввода пароля cookie открывает админку.
- Следующий шаг:
  - отдать пользователю ссылку и пароль отдельным каналом;
  - после появления домена и HTTPS перевести доступ с прямого `:8010` на нормальный URL.

## Обновление 2026-06-04 - автообновление XML по URL

- Статус: deployed on VPS.
- Цель:
  - использовать постоянную ссылку `https://amix-tk.ru/files/1C/prices.xml` как основной источник актуальной базы товаров;
  - автоматически скачивать XML и импортировать его в существующую таблицу товаров каждые 30 минут;
  - оставить ручную загрузку в админке как аварийный запасной вариант;
  - добавить ручной запуск обновления по URL из админки для проверки без ожидания расписания.
- Сделано:
  - добавлен `ProductRemoteXmlImporter`: скачивает XML по URL, сохраняет файл в `data/incoming_xml/` и передаёт его в существующий `ProductXmlImporter`;
  - добавлен full-sync режим для remote-импорта: после успешного XML без ошибок удаляются товары, которых нет в свежей выгрузке;
  - добавлен `ProductsXmlAutoImportRunner`, который запускается в FastAPI lifespan при `PRODUCTS_XML_AUTO_IMPORT_ENABLED=true`;
  - добавлены настройки `.env`: URL, включение автоимпорта, интервал, импорт при старте и timeout;
  - в админке добавлена кнопка `Обновить по ссылке` и отображение источника XML.
- Проверки:
  - `python -m pytest -q` -> `125 passed`;
  - локальный smoke с реальной ссылкой на временной SQLite: `processed=6931`, `product_count=6931`, `errors=0`;
  - VPS `.venv/bin/python -m pytest -q` -> `125 passed`;
  - VPS remote import: `processed=6931`, `deleted=215`, `product_count=6931`, `errors=0`;
  - `amix-api.service` после рестарта активен, journal показывает `Remote products XML auto-import completed`;
  - внешний `/admin` показывает кнопку `Обновить по ссылке` и источник `https://amix-tk.ru/files/1C/prices.xml`.

## Обновление 2026-07-16 - количества по позициям и защита остатка

- Статус: локальная реализация и первый независимый аудит завершены; live-eval на VPS и финальное ревью остаются.
- Backend больше не классифицирует текст клиента и не хранит скрытый сценарный контекст заказа. Gemini получает полную хронологическую историю, включая вызовы функций и их результаты.
- В runtime оставлены ровно две функции: `search_products` и `handoff_to_manager`. У `search_products` нет поля intent: модель передаёт только товары в исходном порядке и необязательное количество каждой позиции.
- Код поиска занимается только сопоставлением переданной строки с каталогом и сравнением запрошенного количества с остатком. Решение, когда искать, что уточнить и когда передать менеджеру, описано в общем системном промпте.
- Удалены старый backend-генератор товарных ответов, неиспользуемые поисковые обёртки, `backend_notes`, `search_type`, пустые `category/tags` и мёртвый тест старого `backend_actions/prelookup`.
- По независимому аудиту исправлены: откат ошибочной транзакции, удаление недоставленной или устаревшей ветки истории, гонка `AGENT_JOINED` с handoff, повтор failed-события, восстановление незавершённых событий и остановка отложенных задач вместе с приложением.
- Локальная проверка: `python -m pytest -q` -> `132 passed`; dialog regression -> `PASS=9 FAIL=0`; deterministic history-eval -> `27/27` сценариев и `123/123` ходов; `compileall` и `git diff --check` прошли.
- Ограничение проверки: fake history-eval подтверждает структуру и исполнение функций, но не качество ответов Gemini.
- Следующий шаг: прогнать настоящую Gemini на VPS по тем же многоходовым сценариям, проверить тексты, выполнить финальное независимое ревью и только затем обновить production-сервисы.

## Обновление 2026-07-16 - финальная model-driven архитектура

- Статус: completed and deployed.
- Архитектурная граница зафиксирована:
  - backend не классифицирует клиентский текст по словам, регулярным выражениям, словарям или локальным сценариям;
  - Gemini получает полную хронологическую историю `user` / `assistant` / `tool` без сжатия вызовов функций в системный контекст;
  - в runtime доступны ровно две функции: `search_products` и `handoff_to_manager`;
  - сопоставление строки с каталогом и проверка количества выполняются только внутри `search_products` после того, как модель сама выбрала запрос;
  - состояние заказа существует только в полной истории диалога, отдельного `order_draft` и функции его обновления нет.
- Исправлена совместимость с Gemini 3: `thought_signature` вызова функции сохраняется в истории и дословно возвращается провайдеру в следующем раунде.
- Проверки:
  - локально `python -m pytest -q` -> `133 passed`;
  - deterministic history-eval, три повтора -> `27/27` сценариев и `123/123` ходов;
  - настоящий Gemini на VPS -> `9/9` сценариев и `41/41` ходов, `PASS`;
  - отдельные нестабильные сценарии повторены по три раза: `3/3` и `3/3`, все ходы пройдены;
  - полный live-прогон: 53 обращения к Gemini, 170 875 токенов, около 5,59 рубля по настроенной оценке тарифа.
- Отчёты сохранены локально в `outputs/amix-live-be3db6e.md` и `outputs/amix-live-be3db6e.json`.
- Production:
  - VPS fast-forward обновлён до `060e107` без изменения `.env`, SQLite и XML-данных;
  - серверный `python -m pytest -q` -> `133 passed`;
  - `amix-api.service` и `amix-telegram-demo.service` -> `active/running`;
  - внутренний и внешний `/health` -> `{"status":"ok"}`;
  - свежих ошибок в journal после перезапуска нет.
- Следующий шаг: наблюдать реальные Jivo-диалоги и корректировать поведение только общими правилами промпта и тестовыми сценариями, не добавляя семантический routing в backend.
