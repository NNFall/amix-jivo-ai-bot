# Iteration 69 - natural conversational tone evaluation (2026-07-20)

- Kept the architecture model-driven: no customer-language dictionaries, regex routing, response templates or new functions were added.
- Asked an independent agent to review Russian first-line chat tone. Its main recommendation was to use simple syntax, variable rhythm and useful direct answers rather than mechanically inserting conversational filler.
- Added generalized prompt rules to react to the meaning of the message, vary sentence openings, avoid mirrored questions and formal empathy, skip unnecessary field acknowledgements, and move through order intake one natural step at a time.
- Added a focused prompt regression test with a verified red-green cycle.
- Local and isolated VPS target verification: `python -m pytest tests/test_model_driven_assistant.py tests/test_llm_client.py -q` -> `27 passed`.
- Ran three real multi-turn dialogs through Google AI Studio `gemini-3.1-flash-lite` in an isolated VPS worktree. Final result: `3/3` scenarios, `18/18` turns, `PASS`.
- The final live run used 23 Gemini calls, 86 348 tokens, 28.532 seconds of provider latency and an estimated 2.6991 RUB.
- Saved readable and machine-readable evidence locally as `outputs/amix-human-live-0d6779d.md` and `outputs/amix-human-live-0d6779d.json`.
- Production deploy is recorded after the final fast-forward and health checks below.

# Iteration 68 - model-driven two-tool simplification and Jivo lifecycle (2026-07-17)

- Removed the remaining backend semantic routing architecture: no customer-language keyword lists, regex intent classification, prelookup response routes, `active_product`, `product_memory`, `pending_clarification` or order-draft function remain in the active runtime.
- Kept exactly two model tools: `search_products` and `handoff_to_manager`.
- Replaced partial/merged context with the complete persisted chronological dialog, including assistant function calls and function results in their original positions.
- Kept backend product work limited to executing model-supplied queries, catalog-identifier normalization and per-product quantity availability comparison.
- Simplified the system prompt into generalized policies for factual grounding, stock privacy, natural order collection, corrections, complete summary, explicit confirmation and manager handoff.
- Removed alternate product/company prompt builders, the old `llm/tools.py` compatibility layer, deleted settings switches for backend prelookup/FAQ rewriting and removed the unused `OrderDraft` ORM model without touching the production database table.
- Reworked dialog/evaluation scripts so they call `AssistantService` and observe actual chronological tool history rather than preclassifying customer text in the harness.
- Hardened Jivo background processing: client events stay in progress until delivery, superseded turns receive their own terminal status, failed sends discard only generated undelivered history, failed events can be retried, and a Jivo handoff is persisted only after `INVITE_AGENT` succeeds.
- Preserved LLM usage records across later outbound failures while rolling back stale assistant/tool/handoff side effects.
- Corrected Google tool continuation so function calls and function responses remain chronological and the model can make another tool call instead of receiving an artificial user instruction.
- TDD evidence: the new event-lifecycle and failed-delivery tests failed against the prior implementation, then passed after the minimal transport fix.
- Local verification: `python -m pytest -q` -> `124 passed`; `python scripts/run_dialog_regression_eval.py` -> `PASS=9 FAIL=0`; fake history-order evaluation repeated three times -> `PASS`, 27/27 scenarios and 123/123 turns; `python -m compileall` passed; `git diff --check` reported only line-ending warnings.
- Local full reports: `outputs/history-order-fake.json` and `outputs/history-order-fake.md`; these are ignored from Git to avoid committing multi-megabyte transcripts.
- Started three independent read-only reviews for architecture, prompt/transcript quality and Jivo concurrency. Production services remain unchanged pending live VPS verification and review closure.

# Iteration 67 - final history-order guards and reproducible local gate (2026-07-16)

- Re-audited the live v5 transcripts and independent findings instead of accepting the earlier partial pass.
- Closed premature handoff paths for active orders even when Gemini supplies a vague summary or a non-order reason; a correction such as "поменяйте" is not treated as confirmation.
- A manager handoff now requires a summary containing products and quantities, fulfillment, desired timing, payment, customer name and phone, plus INN for invoice payment.
- Distinguished a real phone from a 10/12-digit INN and removed the false-positive name marker where the word "Клиент:" alone could satisfy the contact-name requirement.
- Added a second Jivo state/current-turn check after `INVITE_AGENT`, so an operator joining during the invite race prevents the bot from sending another message.
- Kept the direct AMIX tool boundary at exactly `search_products` and `handoff_to_manager`; Kie web search can no longer become a third tool when AMIX tools are supplied.
- Strengthened stock privacy for bare numeric availability, full Russian unit words and future promises to reveal the exact stock. Historical messages and final replies consume complete unit words and preserve sentence punctuation.
- Strengthened the evaluation oracle: customer turns must match in exact order; assistant tool calls and tool results must be balanced chronologically; semantic exact-stock promises fail; every order handoff scenario checks the full manager summary.
- Added and executed the new regressions failing-first before each production fix.
- Fresh local verification: `python -m pytest -q` -> `224 passed`; `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Fake history-order evaluation with three repetitions -> `PASS`, 27/27 scenario runs and 123/123 turns; evidence saved to ignored local JSON/Markdown files under `data/logs/`.
- Static checks: exactly two tool names printed from `OPENAI_TOOLS`; no runtime `update_order_draft`/`get_order_draft` references; `python -m compileall` and `git diff --check` passed.
- A reviewer correctly refused to certify a moving worktree; final independent reviews will be restarted against the stable commit after the server live evaluation.
- Production services were not changed in this iteration yet.

# Iteration 66 - history-driven order implementation and local verification (2026-07-16)

- Replaced runtime order-draft orchestration with conversation-history-driven behavior; the model now receives the complete chronological chat, including assistant function calls and function results.
- Removed `update_order_draft` from tool declarations, execution, retries, context generation and guards. The only model tools are `search_products` and `handoff_to_manager`.
- Kept the legacy `order_drafts` table/model for one rollback window, but confirmed that runtime routing and evaluation do not read or write it.
- Reworked the order prompt into compact generalized rules: collect missing details naturally, apply customer corrections, summarize the complete order, ask for explicit confirmation and only then hand off to a manager.
- Added per-product requested quantities to `search_products`; each product is checked independently without exposing exact free stock.
- Sanitized historical product tool results before sending them to Gemini so old exact stock values are not reintroduced through the transcript.
- Added direct-response and fallback guards against exact-stock, price and weight disclosure in quantity-only conversations; preserved fractional quantities without integer truncation.
- Kept the three-attempt protection per product code and removed automatic shortage handoff during order collection.
- Added `scripts/run_history_order_eval.py` with isolated SQLite, fake/live provider modes, repeated scenarios, full chronological evidence, function calls/results, latency, token/cost accounting, manifest hashes and JSON/Markdown reports.
- Expanded evaluation coverage to multi-product quantities, corrections, delivery and pickup, invoice payment with INN, free descriptions, ambiguous and missing products, cancellation, summary, confirmation and manager handoff.
- Fresh local verification: `python -m pytest -q` -> `171 passed`; `python -m compileall api core database jivo llm products scripts -q` -> passed; `git diff --check` -> passed.
- Dialog regression: `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Fake history-order evaluation with two independent repetitions -> `PASS`, 10/10 scenario runs and 46/46 customer turns.
- Started independent read-only reviews for code/privacy, prompt/order behavior and evaluation methodology. Live Gemini server evaluation and production deployment remain pending.

# Iteration 65 - history-driven order flow design (2026-07-16)

- The user rejected any separate order-draft or final-summary function and approved a model-driven order flow using only `search_products` and `handoff_to_manager`.
- Inspected the current order service, prompt, tool schemas, handoff guard, message history and existing order tests before proposing changes.
- Confirmed that the current model context is limited to 20 database rows and that assistant/tool records consume the same limit.
- Ran four independent read-only reviews covering architecture, prompt policy, code-removal impact and live-evaluation methodology.
- Accepted the shared findings that the draft duplicates conversation state, the search schema cannot express different quantities per product, full-history construction must be fixed, and failed Jivo invites must not produce a success promise.
- Rejected proposals to retain `update_order_draft` or replace it with a new final-summary function because they conflict with the approved two-tool architecture.
- Baseline before implementation: `python -m pytest -q` -> `166 passed`.
- Wrote `docs/superpowers/specs/2026-07-16-history-driven-order-flow-design.md` with the approved runtime boundary, prompt principles, history rules and verification strategy.
- Translated the specification into Russian after the user clarified that project-facing design documents must be directly readable without English.
- Created the implementation plan `docs/superpowers/plans/2026-07-16-history-driven-order-flow.md` with RED/GREEN steps, exact file scopes, live-evaluation evidence and independent review gates.
- No production code or VPS service was changed in this design iteration.

# Iteration 64 - independent audit of live multi-turn evaluation (2026-07-16)

- Reopened the 2026-07-15 live evaluation after the first order transcript contradicted its 10/10 verdict.
- Ran four independent read-only reviews with separate scopes: current requirements, order/tool code, evaluation methodology, and dialogue/prompt quality.
- Verified the critical MT-01 evidence directly in the raw JSON: code 770 maps to `14.023пр.`, code 28834 maps to `МП ЦК белая`, but the product turn called only `search_products`, used scalar `requested_quantity=2`, and left `order_draft.data.items` empty.
- Verified that the requested items 770 x 2 and 28834 x 3 were persisted only on the next customer turn about delivery.
- Confirmed the implementation cause: the forced `update_order_draft` retry runs only when the model returns no tools, so a wrong `search_products` call bypasses it; the search schema cannot represent per-item quantities.
- Confirmed additional code risks: first-tool return behavior, full-list item replacement, missing code-to-article identity in multi-product replies, mismatched handoff reason enums, and an ignored `False` return from Jivo `invite_agent`.
- Corrected the evaluation to 4.0/10 scenario-average and 4.1/10 turn-weighted; MT-01 is 6/10, not 10/10.
- Classified the original run as a real-Gemini service-layer smoke only. It did not exercise Jivo webhook/background/debounce/supersession/outbound/lifecycle behavior and did not contain machine assertions or a reproducibility manifest.
- Added `data/logs/live_multiturn_dialogs_2026-07-16-independent-audit.md` and marked the original report's score as superseded.
- No production code, VPS configuration or deployed service was changed during the audit.

# Iteration 63 - confirmed AMIX order contact fields (2026-07-14)

- Received AMIX's final clarification through Artem: collect name, phone and INN.
- Narrowed the design so every order requires name and phone; bank transfer additionally requires only INN.
- Kept customer type, company/IP name, KPP and email backward-compatible and optional when volunteered by the customer.
- Added failing tests first. The old implementation failed both expected cases: it required extra bank-transfer fields and accepted email instead of phone for other orders.
- Updated order validation, Gemini prompt, tool-field descriptions and fallback questions.
- Focused red run: `2 failed`; focused green run: `4 passed`; order/assistant regression: `87 passed`.
- Independent review found no defects and identified one test-coverage risk: voluntary invoice fields were not explicitly verified. Added service and tool-schema coverage for preserving those fields.
- Final local verification after review: focused optional-field checks -> `2 passed`; full `python -m pytest -q` -> `166 passed`; dialog regression -> `OK=31 PARTIAL=0 FAIL=0`; compile and diff checks passed.
- Committed as `8c5d963`, pushed the feature branch, fast-forwarded `master` and pushed `master`.
- VPS `/root/amix` updated from `5f85a04` to `8c5d963`; server `python -m pytest -q` -> `166 passed`; both services -> `active`; local and public healthchecks -> `200`; no warning-level journal entries after restart.
- The first isolated live Gemini smoke supplied every field in one long message. Gemini retained the order, timing, name, phone and INN but asked one follow-up for fulfillment/payment, so the draft correctly remained `collecting` rather than fabricating values.
- A two-turn isolated live Gemini smoke passed: draft `awaiting_confirmation`; no missing fields; contact keys `name,phone`; payment keys `inn,method`; zero handoffs; chronological roles included both tool calls and tool results. The temporary database was removed and production statistics were not changed.

# Iteration 62 - order intake and cumulative LLM usage (2026-07-13)

- Fixed source requirements in `docs/superpowers/specs/2026-07-13-order-intake-and-llm-usage-design.md` before implementation.
- Created branch `codex/order-intake-audit` from clean commit `95e9722`.
- Baseline: `python -m pytest -q` -> `133 passed`.
- Added structured order drafts with items, quantities, desired timing, fulfillment, payment, contacts and bank-transfer invoice details.
- Replaced immediate order handoff with model-driven `update_order_draft` calls and a backend guard requiring a complete draft plus explicit customer confirmation.
- Kept direct manager requests immediate and kept PDF/Excel/photo parsing out of scope.
- Added safe product checks that return only found state and requested-quantity availability, never exact stock.
- Added cumulative SQLite `llm_calls` records for provider/model/purpose, tokens, inferred thinking tokens, latency and estimated USD/RUB cost.
- Added LLM totals to the existing `/admin` page; retained the rotating raw JSON provider audit.
- Updated Gemini 3.1 Flash-Lite paid pricing to USD 0.25/1M input and USD 1.50/1M output including thinking, based on official Google pricing reviewed on 2026-07-13.
- Added the requested not-found wording because zero-stock products can be omitted from the XML.
- TDD evidence: focused tests were first run failing for missing order service, immediate handoff, missing usage persistence, desired timing and not-found guard, then passed after implementation.
- First independent review found six issues: alternative handoff-reason bypass, confirmation without a shown canonical summary, usage rollback after later failure, missing bank-transfer phone/payer type, unsafe order-flow not-found text and sensitive debug logs enabled by default.
- Added six failing regression tests reproducing those findings; all six failed for the expected reasons before production changes.
- Fixed the order state transition (`ready_for_confirmation` -> persisted canonical summary -> `awaiting_confirmation`) and required that summary to immediately precede explicit customer confirmation.
- Blocked every model-originated handoff reason while an active order has not passed the confirmation invariant; direct customer requests for a manager remain immediate.
- Made per-call LLM usage durable before later Jivo operations, required phone for bank-transfer orders, included payer type in the summary, guarded order not-found wording and disabled sensitive debug logs by default.
- Focused first-review regressions -> `6 passed`.
- A final independent agent review then found seven additional issues: stale order state after cancellation, blocked dissatisfaction handoff, false handoff promise on Jivo invite failure, exact-stock leakage path, quantity required too early, unknown stock treated as unavailable and unmasked order PII in provider audit.
- Added eight focused failing tests reproducing those findings; all failed for the expected reasons before fixes.
- Fixed conditional order-turn transactions, dissatisfaction handoff, Jivo invite/send ordering, exact-stock context/output guards, optional initial quantity, unknown-stock semantics and audit redaction/file permissions.
- Focused second-review regressions -> `8 passed`.
- Final local verification after all review fixes: `python -m pytest -q` -> `161 passed`; `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Initial VPS deployment of `0d73c03`: server `pytest` -> `161 passed`; tables `order_drafts` and `llm_calls` created; both services restarted active; external health -> `200`.
- First isolated live Gemini smoke was invalid because the SSH test text was corrupted by terminal encoding and was discarded with its temporary database.
- Unicode-safe live Gemini smoke exposed a real gap: the model correctly asked for order items but returned plain text without calling `update_order_draft`, so no draft was created.
- Added a failing regression and an order-tool retry: for an explicit order, a plain-text first response is discarded and Gemini is called again with `update_order_draft` selected as the required function.
- Verification after the live-smoke fix: focused tests -> `2 passed`; full `python -m pytest -q` -> `162 passed`; dialog regression -> `OK=31 PARTIAL=0 FAIL=0`.
- Deployed corrective commit `e96b7ef`; server `python -m pytest -q` -> `162 passed`; both `amix-api.service` and `amix-telegram-demo.service` -> `active`.
- Isolated live Gemini smoke for the initial order request passed on a temporary SQLite database: roles `client, assistant_tool_call, tool, bot`; draft `collecting`; two LLM calls; zero handoffs.
- Isolated live Gemini confirmation smoke passed with synthetic product/contact data: complete order -> canonical summary and `awaiting_confirmation`; explicit confirmation -> `handed_off`; exactly one `order_creation` handoff; three LLM calls.
- Temporary smoke databases were removed. Production dialog data and cumulative project statistics were not polluted by the smoke tests.
- External `https://amix.cifresh.ru/health` -> `200 {"status":"ok"}`; no warning-level service journal entries after restart.
- Earlier structural checks: `python -m compileall api core database jivo llm products scripts -q` -> passed; `git diff --check` -> passed (line-ending warnings only).
- `ruff` was not available in the environment (`No module named ruff`).
- Pending: commit/push and VPS deployment.

# Iteration 59 - amix.cifresh.ru DNS and VPS reachability check

- Goal: configure `amix.cifresh.ru` on the AMIX VPS with Nginx and SSL.
- DNS:
  - `amix.cifresh.ru` resolves to the AMIX VPS.
- Initial reachability:
  - The first probe timed out on SSH/HTTP/HTTPS/app ports, so configuration was paused until the VPS became reachable.
  - A later probe confirmed SSH/HTTP/HTTPS/app ports were reachable and `/root/amix` exists on the connected VPS.
- Nginx:
  - Added `/etc/nginx/sites-available/amix.cifresh.ru`.
  - Enabled it via `/etc/nginx/sites-enabled/amix.cifresh.ru`.
  - Proxy target: local AMIX FastAPI service on port `8010`.
  - `client_max_body_size` set to `50m`.
  - `nginx -t` passed before reload.
- SSL:
  - Issued Let's Encrypt certificate for `amix.cifresh.ru` using Certbot Nginx plugin.
  - Certbot enabled HTTPS and HTTP-to-HTTPS redirect.
  - Certificate expiry reported by Certbot: 2026-09-13; auto-renew task is installed by Certbot.
- Verification:
  - Local-on-VPS Nginx check with Host `amix.cifresh.ru`:
    - `/health` -> `200 {"status":"ok"}`.
    - `/admin` -> `303` to `/admin/login`.
  - External check:
    - `http://amix.cifresh.ru/health` -> `301` to HTTPS.
    - `https://amix.cifresh.ru/health` -> `200 {"status":"ok"}`.
    - `https://amix.cifresh.ru/admin` -> `303` to `/admin/login`.
    - `https://amix.cifresh.ru/admin/login` -> `200` login page.
- Jivo webhook token:
  - Updated server `.env` with a generated `JIVO_WEBHOOK_TOKEN`; the token is intentionally not stored in repository docs.
  - Restarted `amix-api.service`; service returned to `active/running`.
  - Verified webhook token guard:
    - wrong token -> `403 Invalid webhook token`;
    - generated token with empty JSON -> token accepted, then `400` validation error for missing Jivo event fields.
- Jivo provider connection:
  - Received provider id from Jivo and configured server `.env` with `JIVO_BOT_API_URL` pointing to `bot.jivosite.com`.
  - Restarted `amix-api.service`.
  - Verified via venv settings load:
    - outbound Jivo URL is configured;
    - webhook token is configured;
    - outbound host is `bot.jivosite.com`.
  - Public checks:
    - `https://amix.cifresh.ru/health` -> `200 {"status":"ok"}`;
    - incoming webhook with configured token and empty JSON -> token accepted, then `400` validation error for missing Jivo event fields.

# OPERATIONS

## Iteration 64 - isolated live multi-turn dialog evaluation (2026-07-15)

- Created branch `codex/live-multiturn-eval-20260715` from the current clean project revision.
- Built six realistic multi-turn scenarios covering:
  - an order by two product codes with delivery and bank-transfer payment;
  - an order described without codes or articles;
  - protected quantity checks and repeated stock probing;
  - refinement of the duplicate article `МП/ОЗ` by price and code;
  - safe not-found handling and a later correction;
  - technical comparison, manager handoff and post-handoff bot silence.
- Ran the scenarios on the VPS through the production-configured Google AI Studio provider and `gemini-3.1-flash-lite`.
- Used the real `AssistantService` and real local tools `search_products`, `update_order_draft` and `handoff_to_manager` against a temporary SQLite database containing a copy of the current 6,923-product catalog.
- Kept handoff in `demo` mode and disabled outbound Jivo effects. No production chats, product rows, LLM totals or customer data were modified.
- The first run was invalid because PowerShell-to-SSH piping replaced Cyrillic with question marks. It was preserved as `data/logs/live_multiturn_dialogs_2026-07-15-invalid-encoding.json`, excluded from all scoring and repeated with explicit UTF-8 console/output encoding.
- Valid run totals:
  - 6 scenarios and 37 customer turns;
  - 45 real Gemini calls;
  - 258,493 prompt, 2,748 completion and 7,731 thinking tokens; 268,972 total;
  - estimated cost USD 0.080342 / RUB 8.0342;
  - average response 1.54 s, median 1.38 s, P95 3.09 s, maximum 4.31 s.
- Initial manual score: 7.2/10; reduced to 6.7/10 after independent review found that MT-05 did not achieve missing-code recovery.
- Passed behavior:
  - both order flows collected the required data, showed a canonical summary and handed off only after explicit confirmation;
  - INN was requested only for bank-transfer payment;
  - free-form products were retained without inventing a technical selection;
  - exact stock was not exposed;
  - every handoff promise had a real handoff event;
  - normal consultation stopped after handoff;
  - the agreed safe not-found wording was used.
- Confirmed defects:
  - repeated quantity checks answered from `active_product` do not enter the stock-guard counter, so the three-attempt handoff did not fire;
  - `Код товара 27818.` was searched as literal code `27818.`, so the existing product was missed;
  - the initial `МП/ОЗ` result was limited to 20 of 962 matching products, preventing price refinement to code `27818`;
  - `по 5 штук каждого` during a product check started order intake even though the customer had not asked to order;
  - `На сайте вроде был такой товар` caused immediate handoff, so a later corrected code and follow-up questions were not processed.
- Independent review recalculated all totals and confirmed the transcripts, costs, latency, order states and handoff events. It also noted that the saved JSON independently proves a 20-item `МП/ОЗ` slice, while the exact catalog count of 962 came from the direct temporary-database measurement made before cleanup.
- Saved the complete machine log to `data/logs/live_multiturn_dialogs_2026-07-15.json` and the full reviewed transcript/report to `data/logs/live_multiturn_dialogs_2026-07-15.md`.
- Removed the temporary VPS SQLite database and remote result file after downloading the evidence.
- This iteration is evaluation-only. The five confirmed defects remain for a separate TDD fix iteration.

## 2026-06-16 - Live Jivo dialog log audit and SQLite lock hardening

- Checked live Jivo webhook logs on VPS after provider connection.
- Findings:
  - Jivo sends real `CLIENT_MESSAGE` events to `https://amix.cifresh.ru/webhooks/jivo/...`.
  - Bot replies are sent to Jivo outbound endpoint and Jivo returns `HTTP 200 OK`.
  - Latest live chats:
    - chat `16548`: user `тест` -> bot greeting;
    - chat `16548`: user asked stock for code `10335` -> bot replied `25 штук`;
    - chat `16548`: user sent a list of product codes -> bot checked availability and replied with found/not-found codes;
    - chat `16549`: user `Добрый день` -> bot greeting;
    - chat `16549`: user `тест это` -> bot acknowledged test;
    - chat `16549`: user asked address -> bot returned Saint Petersburg address.
  - During rapid/retried Jivo events, the app returned several `500` responses caused by `sqlite3.OperationalError: database is locked`.
- Root cause:
  - SQLite was used without explicit busy timeout and WAL mode, so concurrent webhook inserts/background processing could fail immediately under write contention.
- Fix:
  - Added SQLite `timeout=30` connect arg.
  - Added SQLite connection PRAGMAs: `journal_mode=WAL` and `busy_timeout=30000`.
- Local verification:
  - `python -m pytest tests/test_database_db.py -q` -> `2 passed`.
  - `python -m pytest -q` -> `127 passed`.

## 2026-05-20 - Google log-shape diagnostics

- По запросу пользователя отправлены с VPS прямые Google OpenAI-compatible запросы, без нашего provider-adapter merge, чтобы проверить, как Google AI Studio Logs отображает разные формы истории.
- Отправлены 3 payload-варианта:
  - `AMIX_LOG_SHAPE_TEST_A_TOOL_ROLE_20260520`: хронологическая история с `assistant.tool_calls` и следующим `role=tool`;
  - `AMIX_LOG_SHAPE_TEST_B_MIDDLE_SYSTEM_20260520`: `TOOL_RESULTS_JSON` как отдельное `system` сообщение посередине истории;
  - `AMIX_LOG_SHAPE_TEST_C_MERGED_SYSTEM_20260520`: текущий стиль с merged `systemInstruction` сверху.
- Все 3 запроса вернули HTTP 200, значит Google OpenAI-compatible endpoint технически принимает хронологический `assistant.tool_calls` + `role=tool` payload.
- Цель проверки - не качество ответа, а отображение в Google Logs: нужно посмотреть, покажет ли Google UI tool-call/tool-result в `contents`, или всё равно схлопнет/спрячет их.
- По логам пользователя:
  - вариант `A` показал хронологический `functionCall` в `role=model` и следующий `functionResponse` в `role=user`;
  - вариант `B` показал, что `system` посередине уезжает в `systemInstruction`;
  - вариант `C` подтвердил текущий merged-system стиль.
- Дополнительно с VPS отправлен `AMIX_LOG_SHAPE_TEST_D_TOOL_HISTORY_NO_TOOLS_20260520`: completed tool history без `tools` в финальном запросе тоже принят Google, HTTP 200.
- Изменено локально:
  - убран Google-specific перевод tool-history в `TOOL_RESULTS_JSON`;
  - для Google теперь сохраняется хронология `assistant.tool_calls` + `role=tool`, как для остальных провайдеров;
  - merge нескольких `system` сообщений для Google оставлен.
- Проверки:
  - `python -m pytest tests\test_assistant_service.py::test_assistant_service_preserves_tool_history_for_google_provider tests\test_llm_client.py::test_google_ai_studio_payload_preserves_tool_role_history -q` -> `2 passed`;
  - `python -m pytest -q` -> `112 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## 2026-05-20 - Strict check-only and FAQ guards

- По свежим Google AI Studio логам подтверждено: после merge system messages полный prompt, `INTERNAL_CONTEXT_JSON` и `TOOL_RESULTS_JSON` уже доходят до Google; проблема осталась в политике ответа модели.
- Найдено:
  - запрос `тогда проверьте 14.023пр и xyz-999` модель трактовала как общий product_info и называла цену/вес, хотя клиент просил только проверить позиции;
  - FAQ rewrite для адреса добавлял приглашение `Будем рады видеть вас!`, которого не было в `safe_answer`.
- Изменено:
  - `core/assistant_service.py`: обычные product-check фразы `проверь`, `посмотр`, `уточн`, `узнай`, `найди` считаются stock/check-only, если нет явного запроса цены, веса, массы, размера, сравнения, скидки или заказа;
  - `core/assistant_service.py`: полный tool-result снова сохраняет цену/вес для последующих вопросов клиента;
  - `core/assistant_service.py`: final-answer guard оставлен - если модель в check-only ответе всё равно пишет цену/вес или начинает предлагать менеджера/аналоги/заказ без запроса, клиенту уходит программный fallback только по наличию/найдено-не найдено;
  - `core/assistant_service.py`: снят жёсткий FAQ-guard на нейтральные вежливые фразы вроде `Будем рады видеть вас`;
  - `llm/prompts.py`: prompt явно фиксирует, что `проверьте/посмотрите/уточните` по артикулу без других полей - это проверка наличия/существования, а не запрос всей карточки;
  - `llm/prompts.py`: FAQ rewrite prompt возвращён к запрету только новых фактов/обещаний, без запрета короткой вежливой переформулировки;
  - `tests/test_assistant_service.py`: обновлены регрессии для полного tool-result, check-only final guard и разрешённого FAQ polite rewrite.
- Проверки:
  - `python -m pytest tests\test_assistant_service.py::test_assistant_service_keeps_full_tool_result_but_guards_stock_only_reply tests\test_assistant_service.py::test_assistant_service_treats_plain_product_check_as_stock_only tests\test_assistant_service.py::test_assistant_service_allows_company_faq_polite_rewrite tests\test_assistant_service.py::test_assistant_service_keeps_prices_for_stock_only_context -q` -> `4 passed`;
  - `python -m pytest tests\test_assistant_service.py::test_assistant_service_treats_plain_product_check_as_stock_only tests\test_assistant_service.py::test_assistant_service_treats_manager_offer_as_stock_only_leak -q` -> `2 passed`;
  - `python -m pytest -q` -> `111 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - commit `46966c3` (`Harden check-only and FAQ responses`);
  - commit `a138f78` (`Allow polite FAQ rewrites and keep tool facts`);
  - commit `c162b45` (`Guard check-only replies from manager offers`);
  - push: `origin/master`.
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` до `c162b45`;
  - подтверждено окружение: `LLM_PROVIDER=google_ai_studio`, `GOOGLE_AI_MODEL=gemini-3.1-flash-lite`, `ASSISTANT_BACKEND_PRELOOKUP_ENABLED=false`;
  - `.venv/bin/python -m pytest -q` -> `111 passed`;
  - `amix-telegram-demo.service` перезапущен, состояние `active/running/enabled`;
  - smoke без Telegram-отправки: `Проверьте 14.023пр и xyz-999` -> ответ только про наличие `14.023пр.` и не найденный `xyz-999`, без цены/веса и без предложения менеджера;
  - в сохранённом tool-result для этого же smoke цена `473 руб` и вес `0.070` остались, чтобы следующие вопросы могли использовать контекст;
  - smoke без Telegram-отправки: `а где вы находитесь` -> адрес с короткой вежливой фразой `Будем рады вас видеть`.

## 2026-05-20 - Switchable LLM-first product search

- По запросу пользователя временно отключается автоматический backend-prelookup, чтобы проверить режим, где модель сама решает, когда вызывать `search_products`.
- Добавлена настройка `ASSISTANT_BACKEND_PRELOOKUP_ENABLED`.
- При значении `false` backend больше не выполняет заранее товарный поиск по:
  - явным артикулам в текущем сообщении;
  - уточнениям по цене;
  - контекстным follow-up вроде "по второму";
  - order/technical/manager prelookup веткам.
- Backend в этом режиме только исполняет `search_products`, если LLM сама вернула tool call, и сохраняет историю как `assistant_tool_call` + `tool`.
- Для LLM-first stock-only сценария исправлен порядок применения политики: tool-result, который видит модель, теперь уже очищен от цен, корпоративных цен, веса и объёма.
- Добавлен guard: если модель всё равно пишет цену или вес в ответе на вопрос только про наличие, ответ заменяется безопасным программным fallback по остатку.
- Дефолт оставлен `true`, чтобы без изменения `.env` старый режим не поменялся.
- Добавлен регрессионный тест на отключенный prelookup для артикульного вопроса.
- Тестовая фикстура явно выставляет `ASSISTANT_BACKEND_PRELOOKUP_ENABLED=true`, чтобы серверный `.env=false` не ломал тесты старого дефолтного сценария.
- Проверки:
  - `python -m pytest tests\test_assistant_service.py::test_assistant_service_can_disable_backend_prelookup_for_article_query tests\test_assistant_service.py::test_assistant_service_uses_backend_prelookup_for_article_query -q` -> `2 passed`;
  - `python -m pytest -q` -> `108 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - commit `daf9b10` (`Add switchable LLM-first product search`);
  - commit `407ac06` (`Isolate backend prelookup test default`);
  - commit `1f70810` (`Harden stock-only LLM tool results`).
- VPS:
  - `/root/amix` обновлён до `1f70810`;
  - `.env` установлен `ASSISTANT_BACKEND_PRELOOKUP_ENABLED=false`;
  - `.venv/bin/python -m pytest -q` -> `108 passed`;
  - `amix-telegram-demo.service` перезапущен, состояние `active/running/enabled`;
  - smoke без Telegram-отправки подтвердил LLM-first flow: `client`, `assistant_tool_call`, `tool`, `bot` с payload sources `llm_tool_call`, `tool_result`, `llm_tool_search`;
  - smoke на `нужно наличие 14.023пр` вернул только наличие: `220 шт`, без цены/веса.

## 2026-05-20 - Google systemInstruction merge

- По Google AI Studio Logs пользователя проверен turn `МП/ОЗ` в чате `telegram:7476208806`.
- Сравнение:
  - Google Logs показывали `systemInstruction` только как последний `TOOL_RESULTS_JSON`;
  - `contents` в Google Logs содержали только `user/model` историю;
  - серверный audit показывал, что OpenAI-compatible HTTP request отправлял полный первый `system` prompt, но Google bridge при native-конвертации фактически оставлял один `systemInstruction`.
- Вывод: проблема не в том, что backend не сформировал prompt, а в нескольких `system` сообщениях для Google OpenAI-compatible endpoint.
- Исправлено:
  - для provider `google_ai_studio` все `system` сообщения объединяются в одно перед HTTP-запросом;
  - в промпт добавлено общее правило, что явный новый артикул/код/товар в последнем сообщении важнее старого `active_product`.
- Проверки:
  - `python -m pytest tests\test_llm_client.py::test_openai_service_uses_google_ai_studio_provider -q` -> `1 passed`;
  - `python -m pytest -q` -> `108 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## 2026-05-16 - Iteration 16

- Получена внешняя спецификация по целевой архитектуре (backend-first поиск + 2 tools) и принята как базовый ориентир доработки.
- Добавлена фиксация спецификации в репозитории:
  - `docs/LLM_IMPLEMENTATION_SPEC.md` — архитектурные правила и приоритеты.
  - `docs/PROMPTS_AND_TOOLS_REFERENCE.md` — полный snapshot промптов и tool-схем.
- Выполнен рефакторинг LLM-слоя и ассистента:
  - `llm/prompts.py` переписан на единый `SYSTEM_PROMPT` + `PRODUCT_FACTS_RESPONSE_PROMPT`;
  - `llm/tool_schemas.py` добавлены `search_products` и `handoff_to_manager`;
  - `llm/openai_client.py` добавлена поддержка tool-calls для OpenAI/KIE chat completion style;
  - `core/assistant_service.py` переведён на backend-first поток:
    - prelookup по кандидатам до LLM;
    - LLM tools auto при отсутствии prelookup;
    - handoff через tool/rule;
    - логирование lookup/tool-этапов.
- Усилен поиск в БД:
  - `database/repositories.py` добавлен `search_products_structured(...)` со status/notes/exact/similar-count;
  - исключение дублей exact в similar.
- Актуализированы QA-скрипты и тесты:
  - `scripts/run_dialog_eval.py` адаптирован под новый flow;
  - `tests/test_assistant_service.py` переписан под backend-first + tools;
  - `tests/test_product_search.py` переписан, добавлен test на structured-result и disjoint exact/similar.
- Запуск проверок:
  - `python -m pytest -q` -> `34 passed`.
  - `python scripts/run_dialog_eval.py --scenario products_only --output DIALOG_EVALS.md` -> успешно.

## 2026-05-16 - Iteration 17

- По скриншоту Telegram и XML-фрагменту выявлены две реальные ошибки:
  - `7843 silk brash` извлекался как короткий кандидат `7843` и уходил в похожие.
  - `МП 28ск` показывал один товар вместо трёх, потому что импорт схлопывал одинаковые артикулы с разными кодами.
- Исправлено:
  - `database/repositories.py`: `upsert_product(...)` теперь при наличии `code` ищет существующую запись только по `code`; fallback по `normalized_article` применяется только когда кода нет.
  - `products/article_utils.py`: модуль переписан в корректном UTF-8, восстановлена нормализация кириллица/латиница.
  - Добавлено узкое извлечение multiword-артикулов вида `7843 silk brash`.
  - Сохранено извлечение split-prefix артикула `МП 28ск`.
- Добавлены тесты:
  - full multiword article extraction;
  - mapping `МП 28ск` -> `MP28CK`;
  - XML import with duplicate articles and different codes.
- Выполнено:
  - `python -m pytest -q` -> `37 passed`;
  - `python scripts/import_xml.py --path data/incoming_xml/prices.xml` -> `processed=6904 created=1464 updated=5440 errors=0`;
  - локальная проверка `search_products_structured("МП 28ск")` -> `multiple_exact`, exact codes `26167`, `26168`, `26169`;
  - локальная проверка `search_products_structured("7843 silk brash")` -> exact match, без подмены similar.
- GitHub:
  - commit: `8b8255a`
  - message: `Fix duplicate article import and multiword article lookup`
  - push: `origin/master`
- VPS deployment:
  - `/root/amix` обновлён через `git pull --ff-only` до `8b8255a`;
  - выполнен повторный импорт `/root/amix/data/incoming_xml/prices.xml`;
  - результат импорта: `processed=6904 created=1464 updated=5440 skipped=0 errors=0`;
  - выполнены серверные тесты: `29 passed`;
  - `amix-telegram-demo.service` перезапущен;
  - статус сервиса: `ActiveState=active`, `SubState=running`, `UnitFileState=enabled`.
- VPS verification:
  - `search_products_structured("МП 28ск")` -> `multiple_exact`, `exact_matches_count=3`, codes `26167`, `26168`, `26169`;
  - `search_products_structured("7843 silk brash")` -> `exact_found`, `exact_matches_count=1`, code `26139`;
  - `similar_matches_count=0` в обоих проверенных кейсах.
- Final VPS sync:
  - после journal-коммита сервер дополнительно синхронизирован до `7057bf4`;
  - `amix-telegram-demo.service` остался `active/running`.

## 2026-05-16 - Iteration 18

- Выполнена сверка реализации с итоговым пунктом ТЗ:
  - обычные вопросы по компании должны отвечаться из `COMPANY_REFERENCE_CONTEXT`;
  - товарные вопросы должны идти только через SQLite/search;
  - сложные вопросы должны уходить в handoff.
- Найдено несоответствие:
  - в LLM-enabled режиме сложные вопросы могли зависеть от выбора модели и её tool-call `handoff_to_manager`;
  - `HandoffService` слишком широко считал слова `телефон` и `заказ` причиной handoff, что конфликтовало с обычными вопросами "как связаться" и "как забрать заказ".
- Исправлено:
  - `core/handoff_service.py` переписан с более точными группами правил:
    - явный запрос менеджера/оператора;
    - оформление заказа;
    - подбор, аналоги, совместимость, отличия, замена, нестандартные условия;
  - `core/assistant_service.py` теперь применяет backend handoff guard до prelookup/LLM для сложных вопросов.
- Добавлены тесты:
  - backend принудительно делает handoff для `подберите аналог`;
  - обычный вопрос про адрес/телефон не уходит в handoff и остаётся в LLM company-Q&A ветке.
- Проверка:
  - `python -m pytest -q` -> `39 passed`.

## 2026-05-16 - Iteration 15

- Goal: add persistent history for dialog test runs and make LLM/planner/lookup behavior auditable.
- Created `DIALOG_EVALS.md` as a versioned markdown log for dialog evaluations.
- Added `scripts/run_dialog_eval.py`:
  - runs predefined dialog scenarios (`smoke`, `products_only`);
  - stores provider/model + prompt fingerprint;
  - stores per-turn planner payload/mode, lookup call result preview, and final assistant reply;
  - appends every run to `DIALOG_EVALS.md`.
- Executed `python scripts/run_dialog_eval.py --scenario smoke --output DIALOG_EVALS.md`.
- Executed `python -m pytest -q` -> `32 passed`.
- Result: project now has repeatable dialog QA history in markdown, ready for iterative prompt tuning and response quality review.

## 2026-05-10 21:14:46 +05:00 - Итерация 1

- Изучен `AGENTS.md` как главный контекст проекта.
- Подтверждена цель проекта: собрать production-oriented MVP сервиса `amix-jivo-ai-bot` для первой линии в Jivo.
- Зафиксированы ключевые ограничения:
  - быстрый HTTP-ответ webhook;
  - фоновая обработка;
  - SQLite для истории;
  - XML как источник фактов о товарах;
  - OpenAI только как диалоговый слой;
  - handoff сложных кейсов через `INVITE_AGENT`.
- Проверена актуальная документация Jivo Bot API:
  - https://www.jivochat.com/docs/bot/
  - https://www.jivo.ru/help/api/bot-api.html
- Из документации Jivo зафиксированы критичные правила:
  - входящий webhook должен отвечать не дольше 3 секунд;
  - Jivo повторяет запрос до 2 раз при проблемах доставки;
  - для исходящих действий бота используются события `BOT_MESSAGE` и `INVITE_AGENT`;
  - для MVP критичны входящие события `CLIENT_MESSAGE`, `AGENT_UNAVAILABLE`, `CHAT_CLOSED`;
  - событие `AGENT_JOINED` в текущей публичной Bot API-документации явно не раскрыто, поэтому каркас должен безопасно переживать неизвестные события и прекращать активность при закрытии чата.
- Созданы каталоги каркаса проекта:
  - `api/`
  - `core/`
  - `jivo/`
  - `llm/`
  - `products/`
  - `database/`
  - `notifications/`
  - `scripts/`
  - `data/`
  - `tests/`
- Запущенные команды:
  - `Get-ChildItem -Force`
  - `Get-Content AGENTS.md`
  - `python -c ... Path('AGENTS.md').read_text(...)`
  - `Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"`
  - создание каталогов через `New-Item -ItemType Directory -Force`
- Текущее действие: формирование первичного MVP-каркаса, конфигурации и служебных файлов.

## 2026-05-10 21:15-21:18 +05:00 - Итерация 2

- Создан первичный каркас проекта без папки `app`.
- Добавлены root-файлы:
  - `README.md`
  - `PLAN.md`
  - `OPERATIONS.md`
  - `.env.example`
  - `.gitignore`
  - `requirements.txt`
  - `Dockerfile`
  - `docker-compose.yml`
  - `settings.py`
  - `main.py`
- Добавлены рабочие каталоги и модули:
  - `api/`
  - `core/`
  - `jivo/`
  - `llm/`
  - `products/`
  - `database/`
  - `notifications/`
  - `scripts/`
  - `tests/`
- Реализована базовая логика:
  - FastAPI приложение с lifespan-инициализацией базы;
  - `GET /health` и `GET /ready`;
  - `POST /webhooks/jivo/{bot_token}` с валидацией токена;
  - быстрый ACK webhook и вынос обработки в `BackgroundTasks`;
  - SQLite-модели для событий, чатов, сообщений, товаров, импортов, handoff и ошибок;
  - репозитории для идемпотентной регистрации Jivo event и работы с историей;
  - базовый `JivoClient` для `BOT_MESSAGE` и `INVITE_AGENT`;
  - базовый `OpenAIService`;
  - базовый XML importer и поиск товара по нормализованному артикулу;
  - эвристики handoff для сложных кейсов.
- Добавлены тесты:
  - `tests/test_article_utils.py`
  - `tests/test_product_search.py`
  - `tests/test_jivo_events.py`
- Запущенные команды:
  - `python -m pip install -r requirements.txt`
  - `python -m pytest`
  - `python -c "from main import app; print(app.title)"`
- Результаты проверок:
  - все тесты прошли: `8 passed`;
  - импорт приложения успешен;
  - заголовок приложения: `amix-jivo`.
- Исправлена техническая мелочь:
  - заменён `datetime.utcnow()` на timezone-aware `datetime.now(UTC)`, чтобы убрать deprecation warnings в Python 3.13.
- Состояние этапа:
  - первый значимый этап "MVP-каркас проекта" завершён;
  - следующий шаг: инициализация git и первый commit каркаса.

## 2026-05-10 21:19 +05:00 - Итерация 3

- Инициализирован git-репозиторий: `git init`.
- Проверена локальная git-конфигурация:
  - `user.name = Nikita`
  - `user.email = nikitanovyj1@gmail.com`
- Проверено отсутствие локального `.env` перед коммитом.
- Выполнен первый commit каркаса:
  - commit: `02c3056`
  - message: `Initialize amix-jivo MVP scaffold`
- Git warnings по CRLF/LF при `git add` зафиксированы как средовые и не блокируют работу.
- Текущее состояние после commit:
  - первый этап каркаса зафиксирован в git;
  - следующий рабочий блок: уточнение реальных Jivo payload и XML-структуры AMIX.

## 2026-05-10 21:20-21:27 +05:00 - Итерация 4

- Повторно сверена официальная Jivo Bot API-документация по актуальным страницам:
  - https://www.jivochat.com/docs/bot/
  - https://www.jivochat.com/help/api/bot-api.html
- Дополнительно зафиксировано по документации:
  - входящий `CLIENT_MESSAGE` в публичных примерах несёт поля `site_id`, `channel`, `sender.url`, `sender.has_contacts`;
  - `AGENT_JOINED` явно присутствует в help-документации и должен останавливать дальнейшие сообщения бота;
  - бот-провайдер должен безопасно переживать события без текстового `message.text`, включая служебные и lifecycle events.
- Усилены схемы Jivo:
  - добавлены `JivoButton`, `JivoChannel`;
  - расширены `JivoSender` и `JivoMessage`;
  - `JivoIncomingEvent` теперь принимает дополнительные поля из официальных примеров.
- Усилен runtime message processing:
  - разделены terminal statuses чата: `agent_joined` и `closed`;
  - добавлена защита от отправки ответа в чат со статусом `agent_joined` или `closed`.
- Добавлены интеграционные тесты webhook через `fastapi.testclient`:
  - invalid token;
  - идемпотентность и дедупликация одного `CLIENT_MESSAGE`;
  - сценарий product lookup по артикулу;
  - сценарий handoff на менеджера;
  - сценарий `AGENT_JOINED` с корректным terminal status.
- Добавлен `tests/conftest.py` для изолированного SQLite-файла на каждый тест и подмены runtime settings/database engine.
- Запущенные команды:
  - `python -m pytest`
  - `python -c "from main import app; print(app.title)"`
  - `git status --short`
  - `git diff --stat`
- Результаты проверок:
  - все тесты прошли: `13 passed`;
  - импорт приложения успешен;
  - приложение по-прежнему поднимается с title `amix-jivo`.
- Состояние этапа:
  - второй рабочий блок по Jivo webhook/idempotency/tests завершён;
  - следующий блок: усиление XML importer под реальный production-like импорт.

## 2026-05-11 00:05-00:12 +05:00 - Итерация 5

- Усилен блок XML-импорта в `products/xml_importer.py`:
  - результат импорта расширен полями `status`, `skipped`, `errors`, `error_text`;
  - добавлены проверки входного пути (`missing file`, `not a file`);
  - добавлена fail-safe обработка `ElementTree.ParseError` с фиксацией `failed`-статуса в `product_imports`;
  - добавлена защита по записям: если отдельная запись некорректна, увеличивается `errors`, но импорт продолжается.
- Обновлён CLI-скрипт `scripts/import_xml.py`:
  - добавлен bootstrap `sys.path` для корректного запуска как файла `python scripts/import_xml.py ...`;
  - расширен вывод статистики импорта (`status`, `skipped`, `errors`, `error_text`);
  - при ошибке пути или `failed`-импорте возвращается `exit code 1`.
- Добавлены тесты `tests/test_xml_importer.py`:
  - успешный импорт + повторный импорт с обновлением существующей позиции;
  - parse-error сценарий с фиксацией failed-импорта в БД;
  - сценарий skipped-записи при ненормализуемом артикуле.
- Выполненные команды:
  - `python -m pytest`
  - `python scripts\import_xml.py --path data\incoming_xml\missing.xml`
- Результаты:
  - все тесты прошли: `16 passed`;
  - CLI корректно отрабатывает ошибочный путь и печатает понятное сообщение;
  - трассировки `ModuleNotFoundError` при запуске `scripts/import_xml.py` больше нет.
- Состояние этапа:
  - третий рабочий блок (XML importer hardening) завершён;
  - следующий блок: усиление OpenAI routing и guardrails для handoff-решений.

## 2026-05-15 - Итерация 6

- Выполнено SSH-подключение к VPS для подготовки демонстрационной версии.
- По серверу зафиксировано:
  - рабочий пользователь `root`;
  - каталог проекта `/root/amix` существует, но пустой;
  - установлен `python3`;
  - установлен `git`;
  - доступен `systemd`;
  - `pip` и `docker` на сервере отсутствуют.
- Для демонстрации в Telegram реализован transport-independent assistant layer:
  - добавлен `core/assistant_service.py`;
  - вынесены общие сценарии: exact article lookup, similar products, safe fallback, handoff decision.
- `core/message_processor.py` переведён на reuse общего assistant layer, чтобы Jivo и Telegram не расходились по логике.
- Добавлен Telegram demo runtime:
  - `notifications/telegram_demo_bot.py` — long polling через Telegram Bot API;
  - `scripts/run_telegram_demo.py` — серверный runner;
  - `deploy/amix-telegram-demo.service` — systemd unit-шаблон.
- Telegram demo особенности:
  - та же SQLite-база и история сообщений;
  - дедупликация входящих `update_id` через `external_event_id`;
  - команды `/start`, `/help`, `/reset`;
  - для manager-only кейсов бот честно сообщает, что в рабочем режиме передал бы диалог оператору.
- Добавлены тесты:
  - `tests/test_assistant_service.py`
- Обновлены конфигурация и документация:
  - `.env.example` расширен `TELEGRAM_DEMO_POLL_TIMEOUT_SECONDS`;
  - `README.md` дополнен инструкцией по Telegram demo.
- Запущенные команды:
  - `python -m pytest`
  - проверка импорта `notifications.telegram_demo_bot`
  - SSH-обследование VPS через `paramiko`
- Результаты:
  - локальные тесты проходят: `19 passed`;
  - импорт Telegram demo runtime успешен;
  - сервер обследован и готов к дальнейшей установке окружения.
- Состояние этапа:
  - Telegram demo код готов к commit/push;
  - следующий шаг: push в GitHub и серверный деплой в `/root/amix`.

## 2026-05-15 - Итерация 7

- Telegram demo блок отправлен в GitHub:
  - commit: `20f6746`
  - message: `Add Telegram demo bot runtime`
  - push: `origin/master`
- На VPS выполнена подготовка окружения для демонстрационной версии:
  - `apt-get update`
  - установка `python3-pip`, `python3-venv`
  - clone репозитория `https://github.com/NNFall/amix-jivo-ai-bot.git` в `/root/amix`
  - создание virtualenv `/root/amix/.venv`
  - установка Python-зависимостей из `requirements.txt`
  - создание `/root/amix/.env` из `.env.example`
  - установка systemd unit `/etc/systemd/system/amix-telegram-demo.service`
  - `systemctl daemon-reload`
- Проверено состояние VPS после деплоя:
  - в `/root/amix` находится актуальный код с commit `20f6746`;
  - зависимости установлены успешно;
  - unit `amix-telegram-demo.service` загружен в systemd;
  - сервис пока не запущен и не включён в autostart, так как в `.env` отсутствуют реальные секреты.
- Зафиксированные блокеры live demo:
  - `TELEGRAM_BOT_TOKEN` пустой;
  - `OPENAI_API_KEY` пустой;
  - товарная база пока не наполнена реальным XML AMIX.
- Текущее состояние:
  - сервер приведён в состояние ready-to-run;
  - для финального запуска нужен только рабочий `.env` и импорт XML.

## 2026-05-16 - Итерация 8

- Получен новый внешний LLM-провайдер для проекта:
  - документация: `https://docs.kie.ai/market/chat/gpt-5-2`
  - цель: использовать KIE `gpt-5-2` вместо текущего прямого OpenAI-провайдера.
- По документации KIE зафиксировано:
  - endpoint модели: `POST https://api.kie.ai/gpt-5-2/v1/chat/completions`
  - авторизация: `Authorization: Bearer <API_KEY>`
  - поддерживается параметр `reasoning_effort`
  - формат ответа совместим с `choices[0].message.content`
- Локально расширен LLM-клиент:
  - `settings.py` и `.env.example` дополнены провайдер-независимыми и KIE-specific переменными;
  - `llm/openai_client.py` теперь поддерживает `LLM_PROVIDER=openai|kie`;
  - для KIE реализован raw `httpx` вызов `chat/completions`;
  - сохранена обратная совместимость с текущим OpenAI flow.
- Добавлены тесты:
  - `tests/test_llm_client.py` покрывает KIE request payload и разбор ответа;
  - обновлён `tests/conftest.py` для очистки KIE env в изолированных тестах.
- Локальные проверки:
  - `python -m pytest` -> `20 passed`
  - live-вызов через проектный LLM-слой прошёл успешно и вернул осмысленный ответ от KIE
  - raw HTTP-проверка по документации вернула `HTTP 200` и ответ `OK`
- На VPS сделана предварительная настройка `.env` под KIE:
  - `LLM_PROVIDER=kie`
  - настроены `KIE_API_BASE_URL`, `KIE_CHAT_MODEL_PATH`, `KIE_REASONING_EFFORT`, `KIE_ENABLE_WEB_SEARCH`
  - секретный `KIE_API_KEY` записан только в серверный `.env`, без попадания в репозиторий
- Выявлен серверный follow-up:
  - текущий код в `/root/amix` на VPS ещё не содержит локальный commit с новой KIE-интеграцией;
  - после push нужен `git pull` на сервере и повторная серверная проверка LLM-вызова.

## 2026-05-16 - Итерация 9

- KIE-интеграция зафиксирована в Git:
  - commit: `a832fa5`
  - message: `Integrate KIE GPT-5.2 provider`
  - push: `origin/master`
- VPS синхронизирован с последним commit:
  - `/root/amix` обновлен через `git pull --ff-only`
  - актуальный commit на сервере: `a832fa5`
- На VPS выполнены проверки KIE-интеграции:
  - `cd /root/amix && .venv/bin/python -m pytest tests/test_llm_client.py` -> `1 passed`
  - живой вызов через серверный `OpenAIService` при `LLM_PROVIDER=kie` отработал успешно
- Итоговое состояние по KIE:
  - документация изучена;
  - клиент в коде поддерживает KIE;
  - локальный live test успешен;
  - raw HTTP test успешен;
  - server-side live test успешен.
- Текущее состояние:
  - KIE провайдер полностью подключен и проверен end-to-end;
  - главный незакрытый блок для заказческого демо — Telegram token + реальный XML AMIX + запуск самого demo service.

## 2026-05-16 - Итерация 10

- Получены входные данные для live demo:
  - рабочий `TELEGRAM_BOT_TOKEN` для демонстрационного бота;
  - реальная XML-выгрузка AMIX по локальному пути `C:\Users\User\Downloads\prices.xml`.
- XML-выгрузка скопирована в проект:
  - источник: `C:\Users\User\Downloads\prices.xml`
  - рабочая копия: `data/incoming_xml/prices.xml`
  - файл не попадает в Git благодаря `.gitignore`.
- Выполнено изучение реальной структуры XML:
  - корневой тег `КоммерческаяИнформация`;
  - товарные записи в узлах `record`;
  - фактические теги: `Код`, `Артикул`, `ЦенаКорпоративная`, `ЦенаРозничная`, `ЕдиницаИзмерения`, `Вес`, `Объем`, `СвободныйОстаток`;
  - всего найдено `6904` записей.
- Во время локального импорта найден и исправлен production-баг:
  - в `products/xml_importer.py` алиасы цен ожидали русские теги в обратном порядке;
  - добавлены реальные алиасы `ценакорпоративная` и `ценарозничная`;
  - из-за этого до исправления цены не заполнялись в SQLite.
- Усилен `scripts/import_xml.py`:
  - перед импортом теперь вызывается `create_db_and_tables()`;
  - standalone-запуск больше не падает на пустой локальной БД с `sqlite3.OperationalError: no such table: product_imports`.
- Усилен assistant/LLM слой под реальные ограничения AMIX:
  - `llm/prompts.py` уточнён под фактические поля XML и жёсткое требование не выдумывать товарные факты;
  - `core/assistant_service.py` теперь отдельно обрабатывает вопросы про цену/наличие без артикула;
  - если точный артикул не найден, бот сообщает об этом явно, вместо ухода в общий LLM/fallback.
- Локальные проверки на реальном XML:
  - первый импорт: `python scripts/import_xml.py --path data/incoming_xml/prices.xml`
  - результат: `status=completed processed=6904 created=5440 updated=1464 skipped=0 errors=0`
  - после исправления алиасов цен повторный импорт дал: `status=completed processed=6904 created=0 updated=6904 skipped=0 errors=0`
  - итог по локальной базе: `5440` товаров, `5353` розничных цен, `5337` корпоративных цен.
- Добавлены тесты:
  - `tests/test_assistant_service.py` — сценарий вопроса без артикула и сценарий отсутствующего артикула;
  - `tests/test_xml_importer.py` — импорт реальных русских тегов цен;
  - `tests/test_article_utils.py` — артикулы с кириллическими суффиксами.
- Запущенные команды:
  - `python scripts/import_xml.py --path data/incoming_xml/prices.xml`
  - `python -m pytest`
  - локальные диагностические Python-команды по структуре XML и заполнению SQLite.
- Результаты:
  - все тесты проходят: `24 passed`;
  - импорт реальной AMIX-выгрузки успешен;
  - точный поиск по реальным артикулам и ответы по цене/остатку локально подтверждены.
- Следующий шаг:
  - зафиксировать локальные изменения в GitHub;
  - затем синхронизировать VPS, импортировать XML и запустить Telegram demo service.

## 2026-05-16 - Итерация 11

- Локальный блок по реальному XML и guardrails зафиксирован в Git:
  - commit: `c50b719`
  - message: `Refine AMIX XML import and assistant guardrails`
  - push: `origin/master`
- Выполнена серверная синхронизация `/root/amix`:
  - `git pull --ff-only`
  - актуальный commit на VPS: `c50b719`
- Telegram bot token проверен через `getMe`:
  - token валиден;
  - bot username: `testdemoNN_bot`
  - Telegram API вернул `ok=true`.
- На VPS обновлён `/root/amix/.env`:
  - записан рабочий `TELEGRAM_BOT_TOKEN`;
  - подтверждён `LLM_PROVIDER=kie`;
  - секреты остались только в серверном `.env`, без попадания в Git.
- Реальный XML AMIX загружен на VPS:
  - локальный источник: `data/incoming_xml/prices.xml`
  - серверный путь: `/root/amix/data/incoming_xml/prices.xml`
- На VPS выполнен импорт XML:
  - команда: `cd /root/amix && .venv/bin/python scripts/import_xml.py --path data/incoming_xml/prices.xml`
  - результат: `status=completed processed=6904 created=5440 updated=1464 skipped=0 errors=0`
- На VPS включён и запущен Telegram demo service:
  - `systemctl daemon-reload`
  - `systemctl enable amix-telegram-demo.service`
  - `systemctl restart amix-telegram-demo.service`
  - проверка `systemctl show` дала:
    - `ActiveState=active`
    - `SubState=running`
    - `UnitFileState=enabled`
- Проверка серверной базы после импорта:
  - `total=5440`
  - `retail=5353`
- Проверка логов сервиса:
  - `journalctl -u amix-telegram-demo.service -n 20 -o cat --no-pager`
  - зафиксирован успешный старт: `Started amix-telegram-demo.service - AMIX Telegram Demo Bot.`
- Дополнительное замечание по инструментарию:
  - первичный серверный скрипт успешно выполнил импорт и запуск сервиса, но локально упал на выводе `systemctl status` из-за символа `●` и кодировки `cp1251`;
  - проблема была только в отображении вывода на Windows-консоли, не в самом серверном деплое;
  - статус был повторно считан через `systemctl show` и подтверждён как `active/running`.
- Текущее состояние:
  - Telegram demo поднят на VPS и готов к тестовому прогону;
  - реальные товары AMIX уже в серверной SQLite;
  - следующий рабочий блок — живой прогон через Telegram и затем возврат к боевой Jivo-интеграции.

## 2026-05-16 - Итерация 12

- По скриншоту тестового Telegram-чата выявлены ошибки извлечения артикула из пользовательского текста:
  - `ОЗ/700` распознавался как `700`;
  - `МП 28ск` распознавался как `28...` и уходил в "похожие";
  - причина: некорректная unicode-нормализация в `products/article_utils.py` и отсутствие variant-search по раскладке.
- Реализованы правки:
  - `products/article_utils.py` переписан в корректной UTF-8 версии;
  - добавлен `build_normalized_article_variants()` для двунаправленных вариантов кириллица/латиница;
  - улучшен `extract_article_candidates()` для склейки короткого префикса с цифровым токеном (пример: `МП` + `28ск`);
  - `database/repositories.py` обновлён:
    - `get_product_by_article()` ищет по `IN` всех нормализованных вариантов;
    - `get_similar_products()` учитывает токены всех вариантных нормализаций.
- Добавлены/обновлены тесты:
  - `tests/test_article_utils.py`:
    - кейс `ОЗ/700`;
    - кейс `МП 28ск`;
    - variant-normalization;
  - `tests/test_product_search.py`:
    - lookup по раскладочному варианту (`ОЗ/700` -> `OZ/700`);
  - `tests/test_assistant_service.py`:
    - end-to-end кейс split-prefix запроса (`МП 28ск`).
- Выполненные проверки:
  - `python -m pytest` -> `29 passed`;
  - ручной прогон через `AssistantService` на реальной локальной базе:
    - `ОЗ/700` -> точный ответ с ценой/остатком;
    - `МП 28ск` -> точный ответ с ценой/остатком;
    - `1108035` продолжает корректно работать.
- Следующий шаг:
  - commit/push изменений;
  - синхронизация VPS и перезапуск `amix-telegram-demo.service` для применения фикса в живом демо-чате.

## 2026-05-16 - Итерация 13

- Изменения по matching-логике отправлены в GitHub:
  - commit: `ce33417`
  - message: `Fix article matching for mixed-script customer input`
  - push: `origin/master`
- VPS синхронизирован:
  - `cd /root/amix && git pull --ff-only`
  - head на сервере: `ce33417`
- На VPS запущены целевые тесты:
  - `.venv/bin/python -m pytest tests/test_article_utils.py tests/test_product_search.py tests/test_assistant_service.py -q`
  - результат: `17 passed`
- `amix-telegram-demo.service` перезапущен и проверен:
  - `ActiveState=active`
  - `SubState=running`
  - `UnitFileState=enabled`
- Выполнен серверный probe AssistantService по проблемным сообщениям:
  - `какая цена у ОЗ/700` -> теперь точный артикул найден с ценой и остатком;
  - `МП 28ск` -> теперь точный артикул найден с ценой и остатком.
- Примечание по проверке:
  - первая probe-команда дала старое поведение из-за кодировки запроса на стороне Windows-консоли;
  - повторная probe с unicode-escape строками подтвердила корректную работу фикса на VPS.

## 2026-05-16 - Итерация 14

- По запросу на смену архитектуры чата начат переход на LLM-first поток:
  - LLM-планировщик возвращает JSON-решение (`lookup` / `clarify` / `handoff`);
  - backend вызывает lookup-функцию к БД (артикул/код);
  - отдельный LLM-шаг формирует финальный ответ строго по фактам lookup.
- Обновлены prompt-файлы:
  - `llm/prompts.py`:
    - `LOOKUP_PLANNER_SYSTEM_PROMPT`;
    - `FACTS_RESPONSE_SYSTEM_PROMPT`;
    - `build_lookup_planner_prompt(...)`;
    - `build_facts_response_prompt(...)`.
- Обновлен LLM-клиент:
  - `llm/openai_client.py`:
    - `generate_text(system_prompt, user_prompt)`;
    - `generate_lookup_plan(customer_text, transcript)` с JSON parse.
- Добавлена lookup-функция репозитория:
  - `database/repositories.py` -> `lookup_products(session, query, exact_limit, similar_limit)`;
  - поддерживает exact по `code`, exact по `normalized_article` и similar-выдачу.
- Переписан `core/assistant_service.py`:
  - новый путь `_handle_via_llm(...)` как основной при доступной LLM;
  - legacy-механика сохранена в `_handle_via_legacy_fallback(...)` только как аварийный режим;
  - добавлена сериализация товарных фактов в LLM-подсказку.
- Тесты:
  - обновлен `tests/test_product_search.py`, добавлен сценарий multi-exact и code lookup;
  - общий прогон: `python -m pytest` -> `30 passed`.
- Текущее состояние:
  - локальный код готов для деплоя LLM-first логики;
  - следующий шаг: commit/push и синхронизация VPS с перезапуском `amix-telegram-demo.service`.

## 2026-05-16 - Итерация 15

- Изучено предложение по диалоговой регрессии и принято как базовая матрица проверки AMIX-бота.
- Создан `tests/dialog_eval_cases.json` с 25 сценариями:
  - приветствие и справочные вопросы компании;
  - точный поиск по артикулу;
  - точный поиск по коду;
  - несколько товаров на один артикул;
  - похожие позиции только при отсутствии точного совпадения;
  - грязный ввод артикула;
  - несколько артикулов в одном сообщении;
  - отсутствие цены;
  - технический вопрос, подбор, оформление заказа и handoff.
- Создан `scripts/run_dialog_regression_eval.py`:
  - запускает сценарии на изолированной SQLite-базе;
  - добавляет стабильные тестовые товары;
  - классифицирует фактическое действие backend/assistant;
  - пишет Markdown-отчёт в `DIALOG_EVALS.md`;
  - поддерживает запуск против текущей базы через `--use-current-db`.
- Создан `tests/test_dialog_regression.py` с автоматическими проверками product lookup и handoff/company-сценариев.
- Обновлён `core/assistant_service.py`:
  - убран старый ответ через одиночный `get_product_by_article`;
  - основной товарный путь использует `search_products_structured`;
  - backend заранее ищет артикулы/коды, если они есть в сообщении;
  - для заказа с артикулом сначала проверяется остаток, затем создаётся handoff;
  - при недостаточном остатке добавляется причина передачи менеджеру;
  - fallback-ответы формируются из структурированного результата поиска.
- Обновлён `core/handoff_service.py`:
  - добавлены слова для сценариев подбора/рекомендации, чтобы не выдумывать технический совет без данных.
- Выполнены проверки:
  - `python -m pytest -q` -> `41 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=25 PARTIAL=0 FAIL=0`.
- Результаты сценарного прогона добавлены в `DIALOG_EVALS.md`.
- Изменения отправлены в GitHub:
  - commit: `4a17eaa`
  - message: `Add dialog regression suite for AMIX bot behavior`
  - push: `origin/master`
- VPS синхронизирован с GitHub:
  - `cd /root/amix && git pull --ff-only`;
  - head на сервере: `4a17eaa`.
- На VPS выполнены проверки:
  - `.venv/bin/python -m pytest tests/test_dialog_regression.py tests/test_assistant_service.py -q` -> `13 passed`;
  - `.venv/bin/python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=25 PARTIAL=0 FAIL=0`.
- `amix-telegram-demo.service` перезапущен и проверен:
  - `ActiveState=active`;
  - `SubState=running`;
  - `UnitFileState=enabled`.
- После финальной синхронизации на VPS убран временный локальный diff `DIALOG_EVALS.md`, созданный серверным проверочным прогоном; рабочее дерево на VPS оставлено чистым.

## 2026-05-16 - Итерация 16

- По замечанию о нечитаемом формате `DIALOG_EVALS.md` переделан отчёт автопроверки в простой человекочитаемый вид:
  - вопрос клиента;
  - что ожидали проверить;
  - что сделал backend;
  - какие функции были вызваны;
  - итоговый ответ бота;
  - статус сценария.
- Обновлён `scripts/run_dialog_regression_eval.py`:
  - по умолчанию перезаписывает `DIALOG_EVALS.md` свежим понятным отчётом;
  - для истории добавлен флаг `--append`;
  - убраны внутренние нормализованные кандидаты из человекочитаемой строки функции.
- Перегенерирован `DIALOG_EVALS.md`.
- Проверки:
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=25 PARTIAL=0 FAIL=0`;
  - `python -m pytest -q` -> `41 passed`.
- Изменения отправлены в GitHub:
  - commit: `802654c`
  - message: `Make dialog eval report human-readable`
- VPS синхронизирован до `802654c`, рабочее дерево чистое, `amix-telegram-demo.service` остался `active/running`; перезапуск не требовался, так как runtime-логика не менялась.

## 2026-05-16 - Итерация 17

- Разобраны замечания по завышенному статусу `OK` в `DIALOG_EVALS.md`.
- Исправлена логика отчёта и проверки multi-query:
  - T-014 теперь показывает 2 проверенных запроса и 2 точных товара;
  - результат `search_products` в отчёте берёт суммарные значения из `summary`, а не только лучший single-query результат;
  - автопроверка проверяет, что несколько артикулов реально дали несколько exact-результатов.
- Исправлен сценарий сравнения товаров:
  - T-017 теперь сначала ищет оба артикула `14.023л.` и `14.023пр.`;
  - ответ показывает оба товара и сравнивает только доступные поля из базы;
  - после этого создаётся handoff по причине `complex_technical_question`.
- Исправлен compact-поиск:
  - `p am02 b s` теперь нормализуется в `PAM02BS`;
  - `P-AM02/B-S` и `p am02 b s` считаются exact compact match.
- Обновлены пользовательские ответы:
  - приветствие больше не выглядит как описание базы;
  - handoff-ответы больше не содержат фразы `в демо-режиме`, `в рабочем режиме я бы`, `этот вопрос требует менеджера`;
  - клиент видит нормальную формулировку: `Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам.`
- Ужесточены критерии `scripts/run_dialog_regression_eval.py`:
  - запрещены демо-фразы в клиентском ответе;
  - exact match не может сопровождаться текстом `точного совпадения не нашёл`;
  - для multi-query проверяется количество успешных query и суммарных exact-товаров;
  - handoff должен содержать понятную клиенту формулировку передачи менеджеру.
- Обновлены тесты:
  - `tests/test_article_utils.py`;
  - `tests/test_product_search.py`;
  - `tests/test_dialog_regression.py`;
  - `tests/test_jivo_webhook.py`.
- Проверки:
  - `python -m pytest -q` -> `44 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=25 PARTIAL=0 FAIL=0`.
- Изменения отправлены в GitHub:
  - commit: `731cccd`
  - message: `Tighten dialog regression and multi-query lookup`
- VPS синхронизирован до `731cccd`.
- На VPS выполнены проверки:
  - `.venv/bin/python -m pytest tests/test_article_utils.py tests/test_product_search.py tests/test_dialog_regression.py tests/test_assistant_service.py tests/test_jivo_webhook.py -q` -> `36 passed`;
  - `.venv/bin/python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=25 PARTIAL=0 FAIL=0`.
- `amix-telegram-demo.service` перезапущен и проверен:
  - `ActiveState=active`;
  - `SubState=running`;
  - `UnitFileState=enabled`.
- После серверного проверочного прогона временный diff `DIALOG_EVALS.md` на VPS очищен; рабочее дерево VPS чистое.
## 2026-05-17 - Итерация 18

- Доработаны промпты под новую grouped-структуру результата поиска:
  - `product_lookup_result.queries`;
  - `product_lookup_result.results` / `per_query_results`;
  - `product_lookup_result.summary`.
- В `build_product_facts_messages` добавлен параметр `backend_actions`.
- В product facts context теперь передаётся:
  - `search_products_called`;
  - `handoff_to_manager_called`;
  - `handoff_reason`.
- В prompt добавлены запреты на служебные клиентские формулировки:
  - `в демо-режиме`;
  - `в рабочем режиме`;
  - `backend`;
  - `product_lookup_result`;
  - `exact_matches`;
  - `similar_matches`;
  - `handoff_to_manager`;
  - `tool call` / `function call`.
- `AssistantService` обновлён:
  - если в сообщении есть артикулы/коды и одновременно нужен менеджер, backend сначала выполняет поиск товаров, затем создаёт handoff;
  - в ответах с handoff используется пользовательская формулировка `Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам.`;
  - результат multi-query поиска отдаёт alias `results`, чтобы LLM и автопроверка работали с одной grouped-структурой.
- Улучшена обработка compact-кандидатов:
  - успешное exact-совпадение не дублируется похожими alias-запросами;
  - добавлены стоп-слова для извлечения артикулов из фраз вроде `Проверьте код 1364`, `Сколько стоят ...`, `Сравните ...`.
- Добавлены новые сценарии автопроверки T-026..T-031:
  - смешанный результат exact + not_found;
  - два exact-query в одном сообщении;
  - несколько точных товаров по одному query плюс один точный товар по другому;
  - заказ количества больше остатка;
  - сравнение двух артикулов с явной просьбой менеджера;
  - два товара, где у одного нет цены.
- Обновлены тесты:
  - проверка передачи `backend_actions` в product facts prompt;
  - проверка grouped-result payload в LLM messages.
- Перегенерирован `DIALOG_EVALS.md`.
- Проверки:
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`;
  - `python -m pytest -q` -> `46 passed`.
- GitHub:
  - commit: `06c3840`
  - message: `Add grouped product facts backend actions`
  - push: `origin/master`
- VPS синхронизирован с GitHub:
  - `/root/amix` обновлён до `06c3840`;
  - `.venv/bin/python -m pytest tests/test_assistant_service.py tests/test_dialog_regression.py tests/test_llm_client.py -q` -> `17 passed`;
  - `.venv/bin/python scripts/run_dialog_regression_eval.py --output /tmp/amix_dialog_eval.md` -> `OK=31 PARTIAL=0 FAIL=0`;
  - `amix-telegram-demo.service` перезапущен и проверен: `ActiveState=active`, `SubState=running`, `UnitFileState=enabled`;
  - рабочее дерево на VPS чистое.

## 2026-05-17 - Итерация 19

- По замечанию в IDE проверена кодировка `llm/prompts.py`.
- Найдена реальная проблема:
  - сам файл был валидным UTF-8;
  - `PRODUCT_FACTS_RESPONSE_PROMPT` был повреждён в виде `????`;
  - часть строк в `build_product_facts_messages` была записана literal escape-последовательностями `\u0418...`, что работало в Python, но делало файл нечитаемым.
- Исправлено:
  - `PRODUCT_FACTS_RESPONSE_PROMPT` восстановлен нормальным русским UTF-8 текстом;
  - escaped-строки заменены на обычную кириллицу;
  - проверено отсутствие `????` и literal `\u04xx` в Python/JSON runtime-файлах проекта.
- Проверки:
  - `python -m pytest tests/test_llm_client.py tests/test_assistant_service.py tests/test_dialog_regression.py -q` -> `17 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`;
  - `python -m pytest -q` -> `46 passed`.
- GitHub:
  - commit: `4256d2c`
  - message: `Restore readable product facts prompt`
  - push: `origin/master`
- VPS синхронизирован с GitHub:
  - `/root/amix` обновлён до `4256d2c`;
  - focused pytest -> `17 passed`;
  - dialog regression -> `OK=31 PARTIAL=0 FAIL=0`;
  - проверка `llm/prompts.py` на `????` и literal `\u04xx` -> `False`;
  - `amix-telegram-demo.service` перезапущен и проверен: `active/running`.

## 2026-05-17 - Итерация 20

- По замечанию о слишком "ботовом" стиле ответов переработан диалоговый слой.
- `llm/prompts.py` обновлён:
  - ассистент теперь описан как менеджер первой линии AMIX, а не как "AI-бот";
  - добавлены правила живого чата без канцелярита и без одинаковых приветствий;
  - запрещены markdown, жирный текст, backticks, таблицы и сухие карточки вида `Код: ... Остаток: ... Цена: ...`;
  - для нескольких одинаковых артикулов задано новое правило: сначала просить уточнить код товара с сайта или цену, не показывая сразу все строки базы.
- `core/assistant_service.py` обновлён:
  - fallback-ответы переписаны в более человеческом стиле;
  - единичный товар отвечает фразой вида `Да, нашёл ... Сейчас в наличии ...`;
  - несколько одинаковых артикулов теперь дают уточняющий вопрос по коду/цене;
  - добавлена очистка клиентского ответа от markdown-маркеров `**`, `__`, backticks и строковых bullet-prefix.
- `scripts/run_dialog_regression_eval.py` усилен:
  - теперь регрессия падает, если в ответ клиенту просочились markdown-маркеры.
- Обновлены тесты под новый стиль ответов.
- Перегенерирован `DIALOG_EVALS.md`; проверены ключевые сценарии:
  - T-001 приветствие стало коротким и живым;
  - T-008 duplicate article теперь просит уточнить код/цену;
  - T-011 single exact отвечает без карточки полей;
  - T-014 multi-query отвечает без markdown.
- Проверки:
  - `python -m pytest -q` -> `46 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - commit: `4434d9b`
  - message: `Make assistant replies more conversational`
  - push: `origin/master`
- VPS синхронизирован с GitHub:
  - `/root/amix` обновлён до `4434d9b`;
  - focused pytest -> `20 passed`;
  - dialog regression -> `OK=31 PARTIAL=0 FAIL=0`;
  - `amix-telegram-demo.service` перезапущен и проверен: `active/running`;
  - рабочее дерево на VPS чистое.

## 2026-05-17 - Итерация 21

- Проведён отдельный сравнительный прогон стиля без удаления текущего `DIALOG_EVALS.md`.
- Для честного сравнения создан временный git worktree на commit `a5e7ad8`, то есть на состояние до правок "живого менеджера".
- Прогнаны одинаковые 31 сценарий:
  - старое состояние `a5e7ad8` -> `OK=31 PARTIAL=0 FAIL=0`;
  - текущее состояние -> `OK=31 PARTIAL=0 FAIL=0`.
- Сравнение сохранено в отдельный файл `DIALOG_STYLE_COMPARISON.md`.
- Основные выводы:
  - функциональность поиска/handoff не сломалась;
  - сухие подписи полей в ответах снизились с `37` до `0`;
  - markdown-маркеры не просачиваются;
  - duplicate-article сценарий теперь уточняет код/цену вместо выдачи всех строк базы.

## 2026-05-17 - Итерация 22

- По требованию проверять именно реальные ответы нейросети добавлен live-eval контур.
- Создан `scripts/run_live_dialog_eval.py`:
  - использует реальный `AssistantService`;
  - не подменяет LLM fake-ответами;
  - вызывает фактически настроенный provider из `.env` (`kie`);
  - сохраняет prelookup, backend payload, handoff reason, style flags и финальный ответ модели.
- В сценарии live-прогона добавлены 22 проверки:
  - общие вопросы AMIX;
  - точные товары;
  - поиск по коду;
  - дубли артикула;
  - грязный ввод;
  - товар не найден;
  - сравнение;
  - подбор;
  - заказ;
  - недостаточный остаток;
  - передача менеджеру.
- Первый live-прогон выявил методическую проблему:
  - все сценарии шли в одном `chat_id`;
  - история могла загрязнять независимые тест-кейсы.
- Исправлено:
  - каждый live-сценарий теперь запускается в отдельном `chat_id`;
  - label модели для KIE в отчёте теперь показывает реальный endpoint `/gpt-5-2/v1/chat/completions`.
- Live-прогон выявил runtime-проблему:
  - при exact lookup в контекст модели могли попадать дополнительные similar alias-кандидаты;
  - пример: `МП 28ск` давал лишний фрагмент про `28СК`, а `p am02 b s` дополнительно показывал похожие `AM02`.
- Исправлено:
  - `AssistantService._search_products_by_queries` теперь скрывает `similar_found` alias-результаты, если по сообщению уже есть exact match;
  - добавлен тест `test_assistant_service_hides_similar_aliases_when_exact_found`.
- Проверки:
  - локально `python -m pytest -q` -> `47 passed`;
  - локально dialog regression -> `OK=31 PARTIAL=0 FAIL=0`;
  - VPS focused pytest -> `16 passed`;
  - VPS live eval -> `22` сценария, `22` без style flags, `0` на ручную style-проверку.
- Итоговый live-отчёт сохранён в `LIVE_DIALOG_EVALS.md`.
- На VPS после runtime-фикса перезапущен `amix-telegram-demo.service`; статус `active/running`.

## 2026-05-17 - Итерация 23

- По результатам анализа live-ответов проведена микро-доводка тона и поведения.
- `llm/prompts.py`:
  - добавлен общий блок `HUMAN_MANAGER_STYLE_RULES`;
  - закреплено правило не начинать каждый товарный ответ с `Добрый день`;
  - усилены примеры для exact lookup, duplicate article, mixed lookup, похожих товаров, технического сравнения, подбора и заказа;
  - добавлено правило для уточнения дубля по цене/коду: если клиент после уточняющего вопроса пишет цену или код, выбрать подходящую позицию из `exact_matches`;
  - закреплено Jivo-правило: писать `менеджер подключится к диалогу`, а не `свяжется с вами`.
- `core/assistant_service.py`:
  - добавлена очистка фраз `свяжется с вами` -> `подключится к диалогу`;
  - прямой handoff по сложному подбору теперь отвечает полезнее: сначала говорит, какие параметры нужны, затем передаёт менеджеру;
  - добавлен history-aware lookup для уточнений вида `цена 132` после обсуждения дублей артикула;
  - сложный вопрос без явных артикулов может использовать артикулы из истории диалога.
- `scripts/run_live_dialog_eval.py`:
  - добавлена поддержка `history` у сценариев;
  - добавлены live-сценарии L-023..L-027:
    - дубль без таблицы;
    - уточнение дубля по цене;
    - артикул со ссылкой;
    - сравнение из истории;
    - менеджер после уточнения.
- Проверки:
  - локально `python -m pytest -q` -> `47 passed`;
  - локально dialog regression -> `OK=31 PARTIAL=0 FAIL=0`;
  - VPS focused pytest -> `16 passed`;
  - VPS live eval -> `27` сценариев, `27` без style flags, `0` на ручную style-проверку.
- Обновлён `LIVE_DIALOG_EVALS.md`.
- На VPS выполнен deploy commit `ac1320e`, `amix-telegram-demo.service` перезапущен и проверен: `active/running`.

## 2026-05-17 - Итерация 24

- Приняты замечания по последнему отчёту:
  - убрать клиентское слово `выгрузка`;
  - не писать `поможет оформить`, если запрошенного количества больше свободного остатка;
  - явно отвечать `по коду ...`, если клиент спрашивает код;
  - показывать клиенту исходный запрос `14.023`, а не normalized `14023`;
  - заложить флаг показа корпоративной цены.
- `settings.py` и `.env.example`:
  - добавлен `SHOW_CORPORATE_PRICE=true`.
- `core/assistant_service.py`:
  - добавлен `display_query` для результатов поиска;
  - добавлена политика скрытия `corporate_price`, если `SHOW_CORPORATE_PRICE=false`;
  - `requested_quantity_exceeds_stock` теперь имеет приоритет над обычным `order_request`;
  - в `backend_actions` добавлены `response_mode`, `requested_quantity`, `show_corporate_price`, `corporate_price_request`, `queried_by_code`;
  - fallback по коду теперь отвечает `По коду 1364 нашёл артикул ...`;
  - sanitizer заменяет `выгрузка`/`выгрузке` на `текущие данные`;
  - handoff при нехватке остатка формулируется как уточнение возможности заказа/замены, а не оформление.
- `llm/prompts.py`:
  - добавлены правила про `display_query`, запрет слова `выгрузка`, флаг корпоративной цены и shortage-handoff.
- `scripts/run_dialog_regression_eval.py`:
  - усилены критерии: запрещено `выгрузк`, кодовый запрос должен явно упоминать `по коду`, shortage не должен звучать как оформление заказа.
- `scripts/run_live_dialog_eval.py`:
  - live-сценарии расширены до 31;
  - добавлены style flags для `выгрузк` и `свяжется с вами`.
- Добавлены unit-тесты:
  - явный ответ по коду;
  - raw query display для похожего артикула;
  - приоритет shortage над order handoff;
  - скрытие корпоративной цены по `SHOW_CORPORATE_PRICE=false`.
- Проверки:
  - `python -m pytest -q` -> `51 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Локальный live-прогон через модель не выполнен: локально не настроен `KIE_API_KEY`/`OPENAI_API_KEY`; live-проверка будет выполнена на VPS после push.
- GitHub:
  - commit: `b731159`
  - message: `Tighten assistant order and pricing rules`
  - push: `origin/master`
- VPS первично синхронизирован с commit `b731159`:
  - `git pull --ff-only` выполнен в `/root/amix`;
  - в серверный `.env` добавлен `SHOW_CORPORATE_PRICE=true`, если его не было;
  - серверный `python -m pytest -q` -> `51 passed`;
  - серверный live eval -> `31` сценарий;
  - `amix-telegram-demo.service` перезапущен и проверен: `active`.
- Live-прогон на реальной базе выявил edge-case:
  - запрос `14.023` был интерпретирован как exact code `14023`, потому что backend искал по normalized candidate;
  - это противоречит правилу показывать и искать по исходному клиентскому фрагменту, если он восстановлен.
- Исправлено локально:
  - `_search_products_by_queries` теперь выполняет поиск по `display_query`/исходному фрагменту клиента, если он есть;
  - normalized candidate сохраняется в `raw_backend_query`;
  - live prelookup-отчёт переведён на тот же backend search, чтобы отчёт совпадал с реальной логикой ответа;
  - добавлен тест, защищающий от ложного code-match для пунктуированного артикула.
- Повторные локальные проверки:
  - `python -m pytest -q` -> `52 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - commit: `1c6410f`
  - message: `Use raw customer query for product lookup`
  - push: `origin/master`
- VPS повторно синхронизирован с commit `1c6410f`:
  - перед pull восстановлен tracked `LIVE_DIALOG_EVALS.md` из HEAD, чтобы убрать локальное изменение от старого live-прогона;
  - `git pull --ff-only` выполнен успешно;
  - серверный `python -m pytest -q` -> `52 passed`;
  - серверный live eval через KIE -> `31` сценарий;
  - `amix-telegram-demo.service` перезапущен и проверен: `active`.
- Свежий `LIVE_DIALOG_EVALS.md` скачан с VPS и проверен:
  - итог: `31` сценарий, `31` без style flags, `0` на ручную style-проверку;
  - `14.023` теперь идёт как `similar_found`, `query/display_query=14.023`, `raw_backend_query=14023`;
  - shortage-сценарии не обещают оформление заказа и передают менеджеру для уточнения заказа/замены;
  - в ответах модели нет слова `выгрузка`, markdown и фраз `свяжется с вами`.
- При ручной проверке live-ответов замечена пограничная фраза в shortage-сценарии: `поможет с оформлением`.
- Доработано локально:
  - sanitizer shortage-handoff заменяет `поможет с оформлением` на безопасную формулировку про уточнение возможности заказа/замены;
  - prompt запрещает `поможет с оформлением` при `stock_shortage_handoff`;
  - регрессия считает такую фразу ошибкой для shortage;
  - добавлен unit-тест на rewrite этой формулировки.
- Повторные локальные проверки:
  - `python -m pytest -q` -> `53 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - commit: `5f94135`
  - message: `Tighten stock shortage handoff wording`
  - push: `origin/master`
- VPS синхронизирован с commit `5f94135`:
  - `git pull --ff-only` выполнен успешно;
  - серверный `python -m pytest -q` -> `53 passed`;
  - серверный live eval через KIE -> `31` сценарий;
  - `amix-telegram-demo.service` перезапущен и проверен: `active`.
- Свежий `LIVE_DIALOG_EVALS.md` скачан с VPS:
  - итог: `31` сценарий, `31` без style flags, `0` на ручную style-проверку;
  - shortage-сценарии больше не содержат `поможет оформить` или `поможет с оформлением`;
  - `14.023` остаётся `similar_found` с исходным `display_query=14.023`.

## 2026-05-17 - Итерация 25

- По просьбе уточнить именно live-тесты выполнен новый полный live-прогон через реальную KIE-модель.
- Важно: это не `DIALOG_EVALS.md`; нужный для проверки другой нейросетью файл — `LIVE_DIALOG_EVALS.md`.
- Прогон выполнен на VPS командой:
  - `.venv/bin/python scripts/run_live_dialog_eval.py --output LIVE_DIALOG_EVALS.md --append`
- Старый live-отчёт не удалялся: новый полный блок добавлен в конец файла.
- В `LIVE_DIALOG_EVALS.md` теперь есть два полных live-блока:
  - `2026-05-17T15:38:47.674191+00:00` — 31 сценарий;
  - `2026-05-17T16:06:47.947084+00:00` — 31 сценарий.
- Новый прогон:
  - сценариев: `31`;
  - ответов без style flags: `31`;
  - ответов на ручную проверку: `0`.
- Проверены ключевые новые правила:
  - `14.023` остаётся raw/display query и не превращается в точный код `14023`;
  - shortage-сценарии не обещают оформление заказа;
  - ответы без слова `выгрузка`;
  - handoff-формулировки без `свяжется с вами`.

## 2026-05-17 - Итерация 26

- Приняты замечания по ручной проверке последнего live-прогона:
  - L-003 контакты не должен засчитываться, если модель ответила общим приветствием;
  - нужно ловить `коду26168`;
  - нужно не допускать округления корпоративной цены `335,24` до `335`;
  - доставка не должна звучать так, будто бот сам посчитает стоимость;
  - live-отчёт должен разделять style-проверку и смысловую content-проверку.
- `llm/prompts.py`:
  - добавлены конкретные правила для общих вопросов: контакты, адрес, режим работы, доставка;
  - добавлено правило не отвечать приветствием на конкретный вопрос;
  - добавлены правила price display: использовать `retail_price_display`/`corporate_price_display`, не округлять цены, не склеивать коды.
- `database/repositories.py`:
  - в serialized product добавлены `retail_price_display` и `corporate_price_display`.
- `core/assistant_service.py`:
  - fallback использует display-цены;
  - sanitizer исправляет склейку `код/коду/кодом + цифры`.
- `scripts/run_live_dialog_eval.py`:
  - добавлены `content_flags` отдельно от `style_flags`;
  - L-003 требует телефон/email;
  - L-004 проверяет доставку и стоимость через менеджера;
  - L-009 ловит склейку кода;
  - L-020/L-030 ловят округление корпоративной цены;
  - L-031 ловит слово `выгрузка`;
  - shortage-сценарии ловят формулировки, звучащие как оформление при нехватке остатка.
- Тесты:
  - добавлены проверки price display в `search_products_structured`;
  - добавлены unit-тесты live content assertions.
- Проверки:
  - `python -m pytest -q` -> `57 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - commit: `f0f3f23`
  - message: `Add semantic live eval checks`
  - push: `origin/master`
- VPS синхронизирован с commit `f0f3f23`:
  - `git pull --ff-only` выполнен успешно;
  - серверный `python -m pytest -q` -> `57 passed`;
  - серверный live eval через KIE с `--append` -> `31` сценарий;
  - `amix-telegram-demo.service` перезапущен и проверен: `active`.
- Свежий `LIVE_DIALOG_EVALS.md` скачан с VPS:
  - новый блок: `2026-05-17T17:01:31.132715+00:00`;
  - сценариев: `31`;
  - ответов без style flags: `31`;
  - ответов без content flags: `31`;
  - ответов на ручную проверку: `0`.
- Проверены исправленные кейсы в новом live-блоке:
  - L-003 контакты: ответ содержит `+7 (812) 372-66-07` и `market@amix.spb.ru`;
  - L-009: `По коду 26168...`, без склейки;
  - L-020: корпоративная цена сохранена как `335,24 руб.`;
  - L-030: корпоративная цена сохранена как `165,98 руб.`;
  - L-004: стоимость доставки отдаётся на уточнение менеджеру.
- Финальный отчётный commit:
  - commit: `44bfc43`
  - message: `Record semantic live eval rerun`
  - push: `origin/master`
- VPS синхронизирован с commit `44bfc43`:
  - локально изменённый серверный `LIVE_DIALOG_EVALS.md` приведён к tracked-состоянию перед pull;
  - `git pull --ff-only` выполнен успешно;
  - `git status --short` на VPS пустой;
  - `amix-telegram-demo.service` проверен: `active`.

## Итерация 27 - уточнение дублей по цене и stock-only ответы

- Получена внешняя проверка live-отчёта:
  - L-024 `цена 132` после `есть мп 28ск` не должен быть новым поиском по `132`;
  - модель должна использовать предыдущий `multiple_exact` и выбрать позицию по цене/коду;
  - если клиент спрашивает только наличие, не нужно сразу показывать цену.
- Сначала внесены prompt-only правки:
  - добавлены правила уточнения предыдущего выбора;
  - добавлены правила ответа по намерению клиента.
- Локальные проверки после prompt-only правок:
  - `python -m pytest -q` -> `62 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Локальный live-прогон не запустился из-за отсутствия LLM-ключа в локальном `.env`; live выполнялся на VPS.
- Commit prompt-only правок:
  - commit: `acea220`
  - message: `Improve product refinement dialog rules`
  - push: `origin/master`
- VPS prompt-only live-прогон:
  - `git pull --ff-only` выполнен успешно;
  - серверный `python -m pytest -q` -> `62 passed`;
  - серверный live eval через KIE -> `31` сценарий;
  - результат: `31` без style flags, `29` без content flags, `2` на ручную проверку;
  - проблемные кейсы: L-010 показал цену на вопрос только о наличии, L-024 снова попросил уточнить цену/код.
- После этого добавлена backend-упаковка контекста:
  - `followup_refinement` теперь содержит значения уточнения и найденные совпадения;
  - если по уточнению цены/кода найдено ровно одно exact-совпадение, LLM получает `resolved_followup_refinement` и одну exact-позицию;
  - если клиент спрашивает только наличие по одному товару, price-поля убираются из LLM-контекста.
- Добавлены unit-тесты:
  - распознавание `132` и `цена 132` как follow-up уточнения;
  - сужение `multiple_exact` до одной позиции по цене;
  - скрытие цен для single stock-only запроса.
- Проверки после backend-упаковки:
  - локально `python -m pytest -q` -> `64 passed`;
  - локально `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Commit backend-упаковки:
  - commit: `b4af8a8`
  - message: `Stabilize product follow-up context`
  - push: `origin/master`
- VPS финальный live-прогон:
  - `git pull --ff-only` выполнен успешно;
  - серверный `python -m pytest -q` -> `64 passed`;
  - серверный live eval через KIE с `--append` -> `31` сценарий;
  - `amix-telegram-demo.service` перезапущен и проверен: `active`;
  - новый блок `LIVE_DIALOG_EVALS.md`: `2026-05-17T18:59:49.625767+00:00`;
  - результат: `31` без style flags, `31` без content flags, `0` на ручную проверку.
- Проверены ключевые исправления в финальном live-блоке:
  - L-010: `1108035 есть в наличии?` -> ответ только про остаток `2 комплекта`, без цены, с вопросом `По цене подсказать тоже?`;
  - L-024: `цена 132` -> выбрана позиция `код 26168`, остаток `292 шт.`, повторной просьбы уточнить нет.

## Итерация 28 - Telegram `/newchat` для сброса контекста

- Добавлена одна команда сброса контекста для Telegram demo: `/newchat`.
- Решение:
  - не добавлять несколько алиасов (`/clear`, `/clearchat`, `/reset`), чтобы не перегружать меню;
  - оставить только `/newchat` как команду "начать новый тестовый диалог".
- `notifications/telegram_demo_bot.py`:
  - при старте вызывает Telegram `setMyCommands`;
  - меню команд: `/start`, `/help`, `/newchat`;
  - `/newchat` вызывает очистку контекста текущего Telegram-чата.
- `database/repositories.py`:
  - добавлен `reset_chat_context`;
  - удаляет сообщения текущего чата;
  - удаляет handoff-записи текущего чата;
  - переводит чат в статус `active`.
- `README.md` дополнен описанием `/newchat`.
- Тесты:
  - добавлен `tests/test_telegram_demo_bot.py`;
  - проверяется, что команда сброса одна;
  - проверяется фактическая очистка сообщений и handoff.
- Проверка:
  - `python -m pytest -q` -> `66 passed`.
- GitHub:
  - commit: `6347af5`
  - message: `Add Telegram newchat reset command`
  - push: `origin/master`
- VPS:
  - `git pull --ff-only` выполнен успешно;
  - серверный `python -m pytest -q` -> `66 passed`;
  - `amix-telegram-demo.service` перезапущен и проверен: `active`;
  - Telegram `getMyCommands` вернул только команды `/start`, `/help`, `/newchat`.

## Итерация 29 - debug-логи LLM-контекста и уточнение `198 которая стоит`

- По живому Telegram-скриншоту выявлено:
  - модель помнит общий контекст диалога, но уточнение `198 которая стоит` после `МП 28ск` ушло как новый поиск по числу `198`;
  - нужно видеть полный payload, который передаётся в LLM: роли messages, transcript, lookup result, backend actions и ответ модели.
- `settings.py`:
  - добавлен `ASSISTANT_DEBUG_LLM_PAYLOADS`;
  - добавлен `ASSISTANT_DEBUG_LLM_PAYLOADS_PATH`, по умолчанию `data/logs/llm_debug.jsonl`.
- `core/assistant_service.py`:
  - добавлен JSONL debug logger `_log_llm_debug_event`;
  - логируются `llm_direct_request`, `llm_direct_response`, `product_facts_request`, `product_facts_response`, `llm_tool_call_result`;
  - в `product_facts_request` сохраняется полный список `messages` с ролями, `transcript`, `product_lookup_result`, `backend_actions`;
  - расширено распознавание follow-up уточнений: `стоит`, `стоимость`, `которая`, `который`, `за`.
- `llm/prompts.py`:
  - в примеры уточнений добавлена фраза `198 которая стоит`.
- `.env.example` и `README.md`:
  - добавлены настройки и описание `data/logs/llm_debug.jsonl`.
- Тесты:
  - добавлены проверки follow-up для `198 которая стоит`;
  - добавлена проверка записи LLM debug JSONL.
- Проверки:
  - `python -m pytest -q` -> `68 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Локальная ручная проверка без LLM:
  - `есть мп 28ск` -> найдено несколько позиций;
  - `198 которая стоит` -> выбрана позиция `МП 28ск` с розничной ценой `198 руб.` и остатком `237 шт.`.
- GitHub:
  - создан и отправлен commit `1727cfb` (`Add LLM debug payload logging`).
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` до `1727cfb`;
  - серверный `.venv/bin/python -m pytest -q` -> `68 passed`;
  - `amix-telegram-demo.service` перезапущен и проверен: `active`.

## Итерация 30 - role-based история для LLM и INTERNAL_CONTEXT_JSON

- По пользовательскому логу Kie подтверждено:
  - история уходила в модель одним текстовым блоком `История диалога`;
  - последнее сообщение клиента дублировалось отдельным user-блоком;
  - в запросе не было структурного active product context;
  - system prompt содержал повторяющиеся блоки.
- `llm/prompts.py`:
  - пересобран `SYSTEM_PROMPT` в структуру V3: роль, задача, источники данных, намерения, товары, скидки, дубли, handoff, стиль, справка AMIX;
  - добавлены правила для `всм`, `в смысле`, `я спросил же`, active product и скидок;
  - builders теперь принимают `dialog_messages` и `runtime_context`, а не упаковывают историю в один user-текст.
- `core/dialog_service.py`:
  - добавлена сборка LLM-истории как role-сообщений `user`, `assistant`, `tool`.
- `core/assistant_service.py`:
  - прямой LLM-вызов теперь отправляет role-based history;
  - добавлен `INTERNAL_CONTEXT_JSON` с `active_product`, `last_product_lookup`, `pending_clarification`, настройками и каналом;
  - product lookup сохраняется в payload bot-сообщения для последующих вопросов клиента;
  - tool call и tool result сохраняются в историю как служебные сообщения;
  - debug-лог теперь показывает role-based payload без дублирования последнего user-сообщения.
- `llm/openai_client.py`:
  - Kie payload теперь сохраняет `tool_calls`, `tool_call_id`, `name` и role `tool`.
- `llm/tool_schemas.py`:
  - уточнены схемы `search_products` и `handoff_to_manager`.
- Тесты:
  - добавлена проверка, что вопрос `скидки есть?` после обсуждения товара получает active product context;
  - добавлена проверка сохранения tool flow как role messages;
  - добавлена проверка Kie payload для `role=tool`.
- Проверки:
  - `python -m pytest -q` -> `71 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- Live-прогон локально не запущен, потому что в локальном окружении нет `.env` с LLM API key; live-прогон будет выполнен на VPS после деплоя.

## Итерация 31 - правки после live-прогона role-based контекста

- На VPS после деплоя `16ee4e5` запущен `scripts/run_live_dialog_eval.py --output LIVE_DIALOG_EVALS.md`.
- Live-прогон показал:
  - `31` сценарий;
  - без style flags: `30`;
  - без content flags: `29`;
  - проблемные места: доставка ответила общим приветствием, ответ по коду был слишком похож на поля с двоеточиями, уточнение `цена 132` выбрало товар, но не назвало код.
- `core/assistant_service.py`:
  - добавлен backend FAQ для общих вопросов по доставке, контактам, адресу, режиму и возврату в субботу;
  - добавлена нормализация сухих полей вида `Розничная цена:`;
  - если позиция выбрана через уточнение цены/кода, в ответ принудительно добавляется `Код товара ...`, если модель его не назвала.
- Тесты:
  - добавлена проверка backend FAQ по доставке без LLM;
  - добавлена проверка backend FAQ по контактам без LLM;
  - добавлена проверка добавления кода после уточнения цены;
  - добавлена проверка удаления сухих price-label двоеточий.
- Проверки:
  - `python -m pytest -q` -> `74 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Итерация 57 - деплой cookie-login админки на VPS

- Локально реализована отдельная страница `/admin/login` вместо браузерного Basic Auth:
  - `/admin` без cookie возвращает `303` на `/admin/login`;
  - после успешного ввода пароля выставляется `HttpOnly` cookie `amix_admin_session` на 30 дней;
  - неверный пароль показывает ошибку на странице без заголовка `WWW-Authenticate`.
- В админке обновлён блок загрузки XML:
  - нативный системный input скрыт;
  - добавлена зона выбора/перетаскивания файла с текстом `Выберите файл или перенесите сюда`;
  - выбранное имя файла отображается под зоной.
- Проверки локально:
  - `python -m pytest -q` -> `119 passed`;
  - выполнен браузерный screenshot live-страницы через Playwright CLI, визуально проверена мобильная версия `/admin`.
- VPS:
  - `/root/amix` обновлён до commit `c6b9eae`;
  - `systemctl restart amix-api.service`;
  - `systemctl status amix-api.service` -> `active (running)`, Uvicorn слушает `0.0.0.0:8010`;
  - `.venv/bin/python -m pytest tests/test_admin_panel.py -q` -> `6 passed`.
- HTTP smoke на VPS:
  - `GET /admin` без cookie -> `303 /admin/login`, `WWW-Authenticate` отсутствует;
  - `GET /admin/login` -> `200`, форма пароля присутствует;
  - `POST /admin/login` с неверным паролем -> `200`, cookie не выставляется;
  - `POST /admin/login` с корректным паролем -> `303 /admin`, cookie выставляется;
  - `GET /admin` с cookie -> `200`, есть кнопка скачивания XML и форма импорта XML.

## Итерация 58 - автообновление товарной базы по URL 1С

- Получена постоянная ссылка на актуальный XML: `https://amix-tk.ru/files/1C/prices.xml`.
- Проверка ссылки:
  - HTTP `200`;
  - `content-type=application/xml`;
  - размер ответа `3251586` байт;
  - файл начинается как UTF-8 XML из 1С.
- Реализовано:
  - `products/remote_xml_importer.py`: скачивание XML по URL, сохранение в `data/incoming_xml/`, запуск существующего `ProductXmlImporter`;
  - `products/remote_xml_scheduler.py`: фоновый asyncio runner для периодического импорта;
  - настройки `PRODUCTS_XML_REMOTE_URL`, `PRODUCTS_XML_AUTO_IMPORT_ENABLED`, `PRODUCTS_XML_AUTO_IMPORT_INTERVAL_SECONDS`, `PRODUCTS_XML_AUTO_IMPORT_RUN_ON_STARTUP`, `PRODUCTS_XML_DOWNLOAD_TIMEOUT_SECONDS`;
  - FastAPI lifespan запускает автоимпорт, если включён флаг;
  - `/admin/products/import-remote` запускает ручное обновление по ссылке;
  - админка показывает источник XML, статус автообновления и кнопку `Обновить по ссылке`.
- Важное исправление:
  - первый remote import на VPS показал `processed=6931`, но `product_count=7146`;
  - причина: старый importer делал только upsert и не удалял товары, отсутствующие в свежем XML;
  - добавлен full-sync режим `ProductXmlImporter(delete_missing=True)` только для remote-импорта;
  - ручная загрузка XML осталась в старом upsert-режиме.
- Локальные проверки:
  - `python -m pytest tests/test_remote_xml_importer.py tests/test_admin_panel.py tests/test_app_lifespan.py -q` -> `11 passed`;
  - `python -m pytest tests/test_remote_xml_importer.py tests/test_xml_importer.py -q` -> `10 passed`;
  - `python -m pytest -q` -> `125 passed`;
  - smoke с реальной ссылкой на временной SQLite: `processed=6931`, `deleted=1`, `product_count=6931`, `errors=0`, `code=770` -> `14.023пр.`, `219.000`.
- VPS:
  - `/root/amix/.env` дополнен remote XML настройками без секретов;
  - `PRODUCTS_XML_AUTO_IMPORT_ENABLED=true`;
  - `PRODUCTS_XML_AUTO_IMPORT_INTERVAL_SECONDS=1800`;
  - `/root/amix` обновлён до commit `990150d`;
  - `.venv/bin/python -m pytest -q` -> `125 passed`;
  - ручной remote import: `processed=6931`, `updated=6931`, `deleted=215`, `product_count=6931`, `errors=0`;
  - `amix-api.service` перезапущен и активен на `0.0.0.0:8010`;
  - journal после рестарта: `GET https://amix-tk.ru/files/1C/prices.xml "HTTP/1.1 200 OK"` и `Remote products XML auto-import completed`.
- Внешний smoke `/admin`:
  - login по cookie работает;
  - страница содержит кнопку `Обновить по ссылке`;
  - страница содержит источник `https://amix-tk.ru/files/1C/prices.xml`;
  - форма `/admin/products/import-remote` присутствует.

## Итерация 54 - минимальная админ-страница для XML базы товаров

- По пользовательскому решению выбран светлый минимальный вариант интерфейса:
  - без отдельного дашборда, логов, таблиц, вкладок и бокового меню;
  - ограниченная ширина контента, чтобы страница не растягивалась на весь экран при малом количестве информации;
  - основные действия: скачать текущую базу и загрузить новый XML.
- Перед реализацией добавлены тесты `tests/test_admin_panel.py`:
  - `/admin` требует Basic Auth;
  - `/admin` показывает краткий статус, количество товаров и кнопки XML;
  - `/admin/products.xml` экспортирует текущие товары как XML;
  - `/admin/products/import` принимает XML и запускает существующий импорт.
- Красная стадия:
  - `python -m pytest tests/test_admin_panel.py -q` -> 4 failures на `404`, потому что admin endpoints ещё не были подключены.
- Реализация:
  - добавлен `api/admin.py`;
  - `main.py` подключает `admin_router`;
  - `settings.py` и `.env.example` получили `ADMIN_USERNAME` и `ADMIN_PASSWORD`;
  - `requirements.txt` получил `python-multipart` для загрузки файлов через FastAPI;
  - XML-загрузка сохраняет файл в `data/incoming_xml/` и вызывает `ProductXmlImporter`;
  - XML-скачивание отдаёт экспорт из текущей таблицы `products`.
- Проверки:
  - `python -m pytest tests/test_admin_panel.py -q` -> `4 passed`;
  - `python -m pytest -q` -> `117 passed`.
- Замечание:
  - перед деплоем на VPS нужно задать сильный `ADMIN_PASSWORD` в серверном `.env`;
  - сгенерированные XML-файлы и загруженные файлы остаются в `data/`, эта папка уже исключена из Git.

## Итерация 55 - деплой админ-страницы на VPS

- На VPS в `/root/amix/.env` задан `ADMIN_USERNAME=admin` и пользовательский `ADMIN_PASSWORD` без записи секрета в Git.
- `/root/amix` обновлён до commit `3eb1b8d`.
- Установлена новая зависимость `python-multipart`.
- Проверки на VPS:
  - `.venv/bin/python -m pytest tests/test_admin_panel.py -q` -> `4 passed`;
  - `.venv/bin/python -m pytest -q` -> `117 passed`.
- Обнаружено:
  - существующий порт `8000` занят чужим Docker-контейнером `crystalstone`;
  - `amix-telegram-demo.service` запускает Telegram polling script, а не FastAPI HTTP app.
- Решение:
  - создан отдельный systemd-сервис `amix-api.service`;
  - `amix-api.service` запускает `uvicorn main:app --host 0.0.0.0 --port 8010`;
  - сервис включён в автозапуск и перезапущен.
- Проверки HTTP:
  - `http://127.0.0.1:8010/admin` без авторизации -> `401 Basic`;
  - `http://127.0.0.1:8010/admin` с Basic Auth -> `200 text/html`;
  - `http://186.246.18.100:8010/admin` без авторизации -> `401 Basic`;
  - `http://186.246.18.100:8010/admin` с Basic Auth -> `200 text/html`;
  - HTML содержит `AMIX`, ссылку `/admin/products.xml` и форму `/admin/products/import`.

## Итерация 56 - отдельная login-страница и cookie для админки

- Причина:
  - встроенный браузерный prompt Basic Auth неудобен и выглядит системно;
  - пользователь хочет отдельную страницу ввода пароля и сохранение входа на устройстве через cookie;
  - нативная кнопка выбора файла в upload форме выглядит слишком системно.
- Красная стадия:
  - обновлены тесты `tests/test_admin_panel.py`;
  - `python -m pytest tests/test_admin_panel.py -q` -> 6 failures:
    - `/admin` возвращал `401`, а не редирект на `/admin/login`;
    - `/admin/login` отсутствовал;
    - после POST login cookie не устанавливалась;
    - download/upload всё ещё требовали Basic Auth.
- Реализация:
  - `api/admin.py` больше не использует `HTTPBasic`;
  - добавлен `/admin/login` GET/POST;
  - добавлен signed HttpOnly cookie `amix_admin_session` на 30 дней;
  - добавлен `/admin/logout`;
  - `/admin`, `/admin/products.xml`, `/admin/products/import` защищены cookie-сессией;
  - upload input спрятан внутри кастомной dropzone с текстом "Выберите файл или перенесите сюда";
  - добавлен небольшой JS только для отображения выбранного имени файла.
- Проверки:
  - `python -m pytest tests/test_admin_panel.py -q` -> `6 passed`;
  - `python -m pytest -q` -> `119 passed`;
  - локально запущен `uvicorn main:app --host 127.0.0.1 --port 8020`;
  - через Playwright сняты скриншоты `/admin/login` и `/admin` с cookie storage;
  - визуально проверено, что login-форма отдельная, а upload-зона не показывает нативную системную кнопку.

## Итерация 47 - исправление `МП/ОЗ` и вопросов по весу

- Изучены live-логи Telegram и SQLite на VPS по диалогу 2026-05-20:
  - ответы были реальными вызовами `gemini-3.1-flash-lite`, а не чистыми системными шаблонами;
  - audit latency: наличие около 1.8 сек, адрес около 6.0 сек, mixed lookup около 2.1 сек, цена `26141` около 1.65 сек, `МП/ОЗ` около 3.1 сек;
  - на `МП/ОЗ у него какая масса?` backend отправил в поиск `1108035`, а не `МП/ОЗ`;
  - причина: extractor не считал артикулом значение без цифр, даже если это явный слэш-формат.
- Внесено локально:
  - `products/article_utils.py`: добавлен безопасный разбор коротких digitless slash-артикулов;
  - `core/assistant_service.py`: compact memory теперь сохраняет `weight`/`volume`;
  - `core/assistant_service.py`: fallback на вопросы по весу выводит вес по одной или нескольким точным позициям;
  - `core/assistant_service.py`: sanitizer убирает внутреннюю фразу "воспользоваться поиском" и заменяет "база данных" на "текущие данные";
  - добавлены регрессионные тесты на `МП/ОЗ`, неправильную привязку к предыдущему `1108035` и sanitizer.
- Проверки:
  - `PYTHONPATH=. python -m pytest tests/test_article_utils.py tests/test_assistant_service.py -q` -> `60 passed`;
  - `PYTHONPATH=. python -m pytest -q` -> `101 passed`.
- GitHub:
  - commit: `c008d45`;
  - message: `Fix digitless slash article weight lookups`;
  - push: `origin/master`.
- VPS:
  - `/root/amix` был чистым перед деплоем;
  - `git pull --ff-only origin master` -> fast-forward до `c008d45`;
  - `.venv/bin/python -m pytest -q` -> `101 passed`;
  - `systemctl restart amix-telegram-demo.service`;
  - `systemctl is-active amix-telegram-demo.service` -> `active`;
  - `systemctl is-enabled amix-telegram-demo.service` -> `enabled`;
  - проверка на серверной базе: `extract_article_candidates("МП/ОЗ у него какая масса?")` -> `["МПОЗ"]`;
  - проверка на серверной базе: `search_products_structured("МП/ОЗ")` -> `multiple_exact`, 20 точных позиций;
  - fallback по вопросу веса теперь выводит найденные веса по `МП/ОЗ`, а не отвечает про `1108035`.

## Итерация 48 - разбор плохих live-ответов по `МП/ОЗ` и `МП ЦК белая`

- Изучены последние Telegram-сообщения `telegram:7476208806` и LLM audit:
  - `МП/ОЗ у него какая масса?` после предыдущего фикса уже искался правильно: lookup `МП/ОЗ`, `multiple_exact`, 20 точных позиций;
  - `который 194р стоит` ушёл как новый lookup `194р`, поэтому бот потерял связь с предыдущим списком;
  - `МП ЦК белая она сколько весит` backend ошибочно искал как предыдущий `МП/ОЗ`;
  - LLM затем придумала коды `27790-27793` для `МП ЦК белая`, хотя текущий tool-result содержал только `МП/ОЗ`;
  - код `28834` реально существует и даёт `МП ЦК белая`, цена `314`, вес `0.538`, остаток `39`.
- Внесено локально:
  - `194р`, `194 руб`, `194₽` теперь считаются price-refinement по предыдущему lookup;
  - добавлен named product extractor для безцифровых товарных фраз типа `МП ЦК белая`;
  - добавлен guard на LLM-ответы: если модель пишет `код N`, которого нет в текущем lookup-result, ответ заменяется programmatic fallback;
  - добавлены тесты на `МП ЦК белая`, `194р` как уточнение, и unknown-code guard.
- Проверки:
  - `PYTHONPATH=. python -m pytest tests/test_assistant_service.py tests/test_article_utils.py -q` -> `65 passed`;
  - `PYTHONPATH=. python -m pytest -q` -> `106 passed`.
- GitHub:
  - commit: `bb5495a`;
  - message: `Guard follow-up product lookups`;
  - push: `origin/master`.
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only origin master` до `bb5495a`;
  - `.venv/bin/python -m pytest -q` -> `106 passed`;
  - серверная база: `search_products_structured("МП ЦК белая")` -> `exact_found`, код `28834`, вес `0.538`, цена `314`, остаток `39`;
  - серверная проверка: `_extract_named_product_query("МП ЦК белая она сколько весит")` -> `МП ЦК белая`;
  - серверная проверка: `_looks_like_price_refinement("который 194р стоит", ["194Р"])` -> `True`;
  - `amix-telegram-demo.service` перезапущен, статус `active/enabled`.

## Итерация 43 - LLM-first FAQ и порядок товарных уточнений

- По Telegram-проверке обнаружено:
  - быстрые ответы на адрес/контакты шли через backend company FAQ без LLM;
  - multi-token артикул `p am02 b s` извлекался раньше более раннего по тексту `14.023пр`, из-за чего ломалась логика `по второму`;
  - follow-up `am02 который я написал` мог уходить в новый широкий поиск вместо использования предыдущего результата;
  - общий ответ о компании мог добавлять факты не из справки.
- Внесено:
  - добавлена настройка `ASSISTANT_DETERMINISTIC_COMPANY_FAQ_ENABLED=false`;
  - при включенной LLM компания/адрес/доставка теперь идут в LLM direct-flow, deterministic FAQ оставлен только как fallback/offline mode;
  - article candidates сортируются по реальной позиции в сообщении клиента после извлечения;
  - добавлен resolver для `первый/второй` и фрагментов вроде `am02` по последнему product lookup;
  - compact tool result получил `порядок_запросов_клиента`;
  - prompts усилены правилом отвечать в порядке `результаты_по_запросам` и не выдумывать факты о компании за пределами справки AMIX.
  - для company FAQ добавлен отдельный LLM rewrite-flow: backend передаёт безопасный `safe_answer`, модель только переформулирует;
  - добавлен guard: если LLM пишет про AI-бота, характеристики/размеры/аналоги или чужие бренды, ответ откатывается к безопасному AMIX-тексту.
  - для `google_ai_studio` synthetic tool history конвертируется в `system TOOL_RESULTS_JSON`, чтобы Gemini не отклонял payload из-за отсутствующего `thought_signature`.
- Тесты:
  - `python -m pytest -q` -> `95 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Итерация 44 - Google free-tier throttling

- По серверному `data/logs/llm_audit_recent.json` проверены последние LLM-вызовы:
  - всего в audit было 30 entries;
  - HTTP 200: 12;
  - HTTP 503: 7;
  - HTTP 429/rate limit: 6;
  - HTTP 400: 5 старых ошибок до фикса Google tool-history.
- Вывод:
  - retry уже был, но для Free tier он слишком короткий: повторы через несколько секунд попадали в то же минутное окно и снова получали 429;
  - нужен throttle до запроса, а не только retry после ошибки.
- Внесено:
  - `GOOGLE_AI_MIN_REQUEST_INTERVAL_SECONDS=13` по умолчанию;
  - `GOOGLE_AI_RATE_LIMIT_RETRY_DELAY_SECONDS=65` по умолчанию;
  - Google provider теперь выдерживает минимальную паузу между запросами в рамках процесса;
  - после `rate_limit_or_quota` retry ждёт длинную паузу, а не стандартные 2/4/8 секунд;
  - KIE поведение не изменялось.
- Тесты:
  - `python -m pytest tests\test_llm_client.py -q` -> `9 passed`;
  - `python -m pytest tests\test_assistant_service.py -q` -> `46 passed`;
  - `python -m pytest -q` -> `97 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - commit: `66f03ca`;
  - message: `Throttle Google AI Studio requests`;
  - push: `origin/master`.
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` до `66f03ca`;
  - серверный `.env` дополнен `GOOGLE_AI_MIN_REQUEST_INTERVAL_SECONDS=13` и `GOOGLE_AI_RATE_LIMIT_RETRY_DELAY_SECONDS=65`;
  - серверный `.venv/bin/python -m pytest -q` -> `97 passed`;
  - `amix-telegram-demo.service` перезапущен и проверен: `active/running/enabled`.

## Итерация 45 - Google model comparison

- По запросу пользователя подготовлен repeatable-прогон одного AMIX-диалога на нескольких Google Gemini моделях.
- Внесено:
  - добавлен `scripts/compare_google_models_dialog.py`;
  - добавлены pricing entries для `gemini-2.5-pro`, `gemini-3.1-flash-lite`, `gemini-3.1-flash-lite-preview`.
- GitHub:
  - commit: `e8937fe`;
  - message: `Add Google model dialog comparison script`;
  - push: `origin/master`.
- VPS:
  - `/root/amix` обновлён до `e8937fe`;
  - серверный `.venv/bin/python -m pytest -q` -> `97 passed`;
  - через Gemini API models endpoint подтверждены доступные model ids:
    `gemini-3-flash-preview`, `gemini-2.5-pro`, `gemini-3.1-flash-lite`;
  - выполнен прогон:
    `.venv/bin/python scripts/compare_google_models_dialog.py --models gemini-3-flash-preview,gemini-2.5-pro,gemini-3.1-flash-lite --output data/logs/model_compare_2026-05-19.md --json-output data/logs/model_compare_2026-05-19.json --min-interval 0.5 --rate-limit-delay 20 --retry-attempts 2`.
- Сводка результата:
  - `gemini-3-flash-preview`: 12 provider attempts, 2x HTTP 503, 169.0s total, 7,394 tokens, ~0.8799 RUB;
  - `gemini-2.5-pro`: 10 provider attempts, no HTTP errors, 77.1s total, 12,247 tokens, ~8.1371 RUB;
  - `gemini-3.1-flash-lite`: 10 provider attempts, no HTTP errors, 20.0s total, 7,185 tokens, ~0.1343 RUB.
- Важный найденный риск:
  - все три модели на вопрос `чем л отличается от пр?` начали выводить технический смысл `левый/правый`, хотя в структурированных товарных данных таких характеристик нет;
  - нужен backend/prompt guard, который для технических отличий без характеристик запрещает модели делать такой вывод и сразу ведёт к безопасному ответу + handoff.

## Итерация 46 - Google 3.1 Pro comparison append

- По запросу пользователя отдельно прогнана `gemini-3.1-pro-preview` до фикса technical guard.
- Команда на VPS:
  - `.venv/bin/python scripts/compare_google_models_dialog.py --models gemini-3.1-pro-preview --output data/logs/model_compare_2026-05-19-pro.md --json-output data/logs/model_compare_2026-05-19-pro.json --min-interval 0.5 --rate-limit-delay 20 --retry-attempts 2`.
- Результат:
  - 10 provider attempts;
  - один read timeout на последнем техническом вопросе, после чего сработал fallback;
  - total time 272.2s;
  - 8,040 токенов;
  - ~5.1830 RUB.
- Важное наблюдение:
  - `gemini-3.1-pro-preview` в ходе `а 14.023 без пр есть?` тоже сделала вывод про правый/левый вариант, хотя в структурированных данных этого нет;
  - на финальном ходе `чем л отличается от пр?` нормального модельного ответа не было из-за read timeout, поэтому нельзя считать, что Pro надёжно решает эту проблему.
- Объединённый отчёт:
  - `/root/amix/data/logs/model_compare_2026-05-19-combined.md`;
  - `/root/amix/data/logs/model_compare_2026-05-19-combined.json`.

## Итерация 47 - switch default model and safer consulting prompt

- По запросу пользователя выбрана модель `gemini-3.1-flash-lite` как практический default.
- Внесено:
  - `settings.py`: default `google_ai_model = "gemini-3.1-flash-lite"`;
  - `.env.example` и README обновлены под новую модель;
  - prompt дополнен общими правилами консультанта первой линии:
    не дожимать к покупке, не предлагать оформление без явного запроса, не давать технические рекомендации без данных;
  - prompt не содержит частного запрета под один кейс, вместо этого добавлено общее правило:
    не выводить назначение, совместимость, сторону установки, материал, размеры, монтаж или смысл обозначений из артикула/названия/общих знаний;
  - backend guard для `complex_technical_question` теперь заменяет модельные технические догадки безопасным текстом, но сохраняет проверенные артикулы.
- Проверки:
  - `python -m pytest tests\test_assistant_service.py tests\test_dialog_regression.py -q` -> `50 passed`;
  - `python -m pytest -q` -> `98 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - commit: `2a31de6`;
  - message: `Use Gemini Flash Lite and tighten consulting prompt`;
  - push: `origin/master`.
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` до `2a31de6`;
  - серверный `.env` обновлён: `GOOGLE_AI_MODEL=gemini-3.1-flash-lite`;
  - серверный `.venv/bin/python -m pytest -q` -> `98 passed`;
  - `amix-telegram-demo.service` перезапущен и проверен: `active/running/enabled`.

## Итерация 39 - real handoff action guard

- По Telegram/Kie live payload обнаружено, что текст `Передаю вопрос менеджеру` мог быть обычным `assistant.content`, без реального `handoff_to_manager`.
- В `core/assistant_service.py` добавлена серверная защита:
  - `_handoff_reply()` теперь сохраняет synthetic `assistant_tool_call` + `role=tool` для `handoff_to_manager`;
  - demo-mode handoff логируется с `real_jivo_invite_sent=false`;
  - если модель текстом обещает передачу менеджеру без tool-call, backend создаёт handoff action с причиной `bot_uncertain`;
  - если chat status уже `handoff_requested`, новые сообщения не идут в товарный/LLM сценарий и получают короткий ответ `Менеджер уже вызван, он подключится к диалогу.`
- В `llm/prompts.py` добавлен запрет обещать передачу менеджеру без реального `handoff_to_manager` или `backend_actions.handoff_to_manager_called=true`.
- Обновлены тесты:
  - direct manager request должен создавать `assistant_tool_call` + `tool`;
  - текстовый handoff от модели конвертируется в реальный handoff action;
  - после handoff обычные ответы блокируются;
  - Jivo webhook handoff сохраняет tool-слой в истории.
- Проверки:
  - focused handoff/Jivo pytest -> `4 passed`;
  - `python -m pytest tests\test_assistant_service.py tests\test_jivo_webhook.py -q` -> `45 passed`;
  - `python -m pytest -q` -> `87 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - создан и отправлен commit `72f0795` (`Enforce real handoff actions`).
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` с `907aa81` до `72f0795`;
  - серверный `.venv/bin/python -m pytest -q` -> `87 passed`;
  - `amix-telegram-demo.service` перезапущен;
  - `systemctl show amix-telegram-demo.service -p ActiveState -p SubState -p UnitFileState` -> `active/running/enabled`.

## Итерация 40 - turn coalescing для быстрых сообщений подряд

- Проверена текущая архитектура:
  - Telegram demo обрабатывал updates синхронно и блокировал polling на время LLM;
  - Jivo webhook запускал каждый CLIENT_MESSAGE как отдельную обработку без supersede/coalescing;
  - общей логики отмены устаревшего ответа не было.
- Добавлен `core/turn_coordinator.py`:
  - in-process generation per chat;
  - debounce перед обработкой;
  - устаревший worker пропускает обработку или не отправляет ответ после LLM.
- `AssistantService` расширен:
  - `record_client_message()` сохраняет user message без генерации ответа;
  - `handle_pending_client_messages()` собирает все client messages после последнего bot message и отвечает по ним одним актуальным turn;
  - `AssistantReply.superseded` позволяет transport-слою не отправлять устаревший ответ;
  - direct LLM и product-facts LLM проверяют `is_turn_current` после provider call перед сохранением bot reply.
- `notifications/telegram_demo_bot.py`:
  - normal messages теперь сохраняются сразу и планируют worker через coordinator;
  - polling не ждёт LLM и может принять следующее сообщение клиента.
- `core/message_processor.py`:
  - Jivo CLIENT_MESSAGE сохраняет user message и планирует общий pending-turn worker;
  - send/invite выполняются только если turn всё ещё актуален.
- Настройка:
  - добавлен `TURN_DEBOUNCE_SECONDS=1.2` в `settings.py` и `.env.example`.
- Тесты:
  - добавлена проверка двух подряд user messages до ответа;
  - добавлена проверка, что stale LLM reply не сохраняется как bot message;
  - Jivo webhook tests адаптированы к async worker ожиданию.
- Проверки:
  - focused pending/superseded/Jivo tests -> `7 passed`;
  - `python -m pytest -q` -> `89 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - создан и отправлен commit `b0c62d6` (`Coalesce consecutive chat turns`).
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` с `bdf3cdb` до `b0c62d6`;
  - серверный `.venv/bin/python -m pytest -q` -> `89 passed`;
  - `amix-telegram-demo.service` перезапущен;
  - `systemctl show amix-telegram-demo.service -p ActiveState -p SubState -p UnitFileState` -> `active/running/enabled`.

## Итерация 33 - деплой cleanup payload на VPS

- Локально изменён Kie generation payload по просьбе пользователя:
  - `temperature` изменён на `0.6`;
  - `max_completion_tokens` удалён из настроек и payload;
  - обновлены `.env.example`, `settings.py`, `llm/openai_client.py`, `tests/test_llm_client.py`.
- Локальные проверки:
  - `python -m pytest tests\test_llm_client.py -q` -> `3 passed`;
  - `python -m pytest -q` -> `74 passed`.
- GitHub:
  - создан и отправлен commit `d5514fe` (`Adjust Kie generation settings`).
- VPS:
  - подключение выполнено к серверу пользователя;
  - перед деплоем `/root/amix` был на `4e0e2e8`;
  - выполнено `cd /root/amix && git pull --ff-only`;
  - `/root/amix` обновлён до `d5514fe`;
  - серверный `.venv/bin/python -m pytest -q` -> `74 passed`;
  - `amix-telegram-demo.service` перезапущен;
  - проверка systemd: `ActiveState=active`, `SubState=running`, `UnitFileState=enabled`;
  - проверка settings на VPS: `kie_temperature 0.6`, `has_kie_max_completion_tokens False`.

## Итерация 34 - synthetic prelookup tool history и безопасные provider fallback

- По новому ТЗ внесены архитектурные правки LLM pipeline:
  - backend-prelookup сохраняется как synthetic `assistant_tool_call` + `role=tool`;
  - последующие LLM-запросы видят search result на своём месте в role-history;
  - в final-answer вызов больше не добавляется временный `system TOOL_RESULTS_JSON`, если tool result уже сохранён в истории.
- `INTERNAL_CONTEXT_JSON`:
  - удалён `current_user_message`;
  - полный текущий lookup не дублируется в context;
  - добавлен компактный `dialog_state.product_memory`;
  - `pending_clarification` больше не предлагает `link/photo`, только `code` и `retail_price`.
- Товарные правила:
  - stock-only вопросы удаляют розничную и корпоративную цену из payload перед LLM;
  - `backend_actions.response_mode="stock_only"` выставляется для вопросов только по наличию;
  - corporate price скрывается по умолчанию и показывается только при прямом запросе корпоративной/оптовой цены;
  - ответы, где модель просит `ссылку или фото`, санитайзятся в `код товара с сайта или цену в карточке`.
- Kie provider:
  - `temperature` изменён на `0.35`;
  - добавлены `KIE_HTTP_CONNECT_TIMEOUT_SECONDS`, `KIE_HTTP_READ_TIMEOUT_SECONDS`, `KIE_RETRY_MAX_ATTEMPTS`, `KIE_RETRY_TOTAL_TIMEOUT_SECONDS`;
  - добавлен retry/backoff для 429/5xx/network/timeout;
  - текст `You've hit your limit. Please try again later.` распознаётся как `rate_limit_or_quota`, не как ответ клиенту;
  - при provider error прямой LLM-flow не отдаёт стандартное приветствие.
- Live eval:
  - добавлены сценарии `L-032`-`L-035` на память первого товара, `не понял`, цену без корпоративной и запрет ссылки/фото.
- Тесты:
  - добавлены проверки synthetic prelookup tool history;
  - добавлены проверки provider timeout/rate-limit fallback;
  - добавлены проверки stock-only/corporate-price правил;
  - добавлены проверки Kie payload/error parsing.
- Проверки:
  - `python -m pytest -q` -> `80 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Итерация 35 - деплой turn handling и targeted live eval

- GitHub:
  - создан и отправлен commit `bae0736` (`Harden LLM turn handling`);
  - создан и отправлен commit `63b15d3` (`Allow targeted live eval cases`).
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` до `63b15d3`;
  - серверный `.venv/bin/python -m pytest -q` -> `80 passed`;
  - `amix-telegram-demo.service` перезапущен и проверен: `active/running`;
  - подтверждены runtime settings: `kie_temperature=0.35`, `kie_stream=False`, `kie_read_timeout=180`, `kie_retry_max_attempts=4`, `kie_max_completion_tokens` отсутствует.
- Live eval:
  - полный `scripts/run_live_dialog_eval.py --output LIVE_DIALOG_EVALS.md` был запущен на VPS, но не завершился за 20 минут из-за долгого Kie running/provider состояния; процесс остановлен, старый `LIVE_DIALOG_EVALS.md` не перезаписывался;
  - добавлен фильтр `--case` для targeted live-прогонов отдельных сценариев;
  - запущен targeted live eval `L-032`-`L-035` с ограниченным test retry-budget, отчёт сохранён в `LIVE_DIALOG_EVALS_TARGETED.md`;
  - результат targeted run: `4` сценария, `4` без style flags, `3` без content flags, `1` на ручную проверку;
  - `L-032` не прошёл content-check из-за `rate_limit_or_quota` от Kie и безопасного provider fallback вместо ответа по памяти;
  - `L-033`, `L-034`, `L-035` прошли без content flags.

## Итерация 36 - fix transcript tool pollution и Kie failure retry

- По свежему Kie payload и Telegram-скрину обнаружено:
  - `stream_options.include_usage` виден в Kie UI, хотя проектный `llm/openai_client.py` не добавляет `stream_options`;
  - `role=tool` JSON попадал в legacy transcript как `Бот: {...}`;
  - из этого transcript backend извлекал мусорные article candidates вроде `МП28СКINTENTPRODUCTINFO` и `EXACTMATCHESCOUNT3`;
  - Kie provider-side `status=failure/error_code=500` мог вернуться как пустой ответ без `error_type`, из-за чего direct LLM-flow уходил в обычный fallback `Подскажите, что нужно посмотреть?`.
- Исправлено:
  - `DialogService.get_transcript()` теперь включает только реальные `client` и финальные `bot` сообщения, без `assistant_tool_call` и `tool`;
  - Kie response parser теперь распознаёт `status=failure/failed/error`, `error_code/code/status_code >= 500`, `server exception` и пустой body как retryable provider error;
  - `llm_response_received` логирует `error_type` и `retryable`;
  - follow-up вопросы вроде `а есть мп дешевле?` используют историю товара и идут в backend prelookup, а не в generic LLM fallback.
  - deterministic fallback для `дешевле` по нескольким позициям теперь показывает варианты с кодами, ценами и остатком.
- Проверки:
  - focused tests -> `42 passed`;
  - `python -m pytest -q` -> `83 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Итерация 37 - switch KIE model endpoint to Gemini

- По запросу пользователя KIE endpoint переключён с `gpt-5-2` на Gemini:
  - `KIE_CHAT_MODEL_PATH=/gemini-3-pro/v1/chat/completions`;
  - обновлены `settings.py`, `.env.example`, `README.md`.
- `stream=True` и `include_thoughts=True` из примера KIE не включались:
  - текущий runtime читает non-stream JSON;
  - reasoning/thoughts не должны попадать в клиентские ответы или debug payload.
- Проверки:
  - `python -m pytest -q` -> `83 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Итерация 38 - cleanup follow-up prelookup и compact tool result

- По свежему Kie payload обнаружено, что backend всё ещё строил search queries из истории/product_memory:
  - на `198 которая` в поиск попадали старые `1108035`, `50820`, `МП28СК`;
  - при точном `1108035` в LLM-visible result уходили похожие `1108036`, `1108038`, `1108039`;
  - `pending_clarification` работал как повод для широкого backend поиска, а не как мягкая подсказка.
- Исправлено:
  - `_handle_message()` больше не берёт article candidates из полного transcript для short numeric refinement;
  - для `198 которая` используется последний pending multiple-exact lookup, а если цены были скрыты stock-only политикой, backend переищет только pending артикул;
  - `_search_products_by_queries()` вычищает `similar_matches`, если есть exact match;
  - `role=tool` content стал компактным русским result для модели, raw lookup хранится отдельно в message payload;
  - `product_memory` восстанавливается из raw payload, а не из компактного текста tool-result;
  - формат цен теперь группирует тысячи.
- Добавлены тесты:
  - уточнение `198 которая` после старого товара не содержит stale queries `1108035`/`50820`;
  - exact `1108035` не отдаёт `similar_matches` в tool content;
  - compact tool result сохраняет raw lookup в payload.
- Проверки:
  - `python -m pytest -q` -> `85 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - создан и отправлен commit `c3d5679` (`Clean up product follow-up lookups`).
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` до `c3d5679`;
  - серверный `.venv/bin/python -m pytest -q` -> `85 passed`;
  - `amix-telegram-demo.service` перезапущен;
  - `systemctl show amix-telegram-demo.service -p ActiveState -p SubState` -> `active/running`.

## Итерация 41 - direct Google AI Studio provider

- По официальной документации Google проверен OpenAI-compatible endpoint Gemini API:
  - base URL: `https://generativelanguage.googleapis.com/v1beta/openai/`;
  - chat endpoint: `/chat/completions`;
  - авторизация: `Authorization: Bearer GEMINI_API_KEY`.
- Проверено ограничение по моделям:
  - `gemini-3-pro-preview` выключен;
  - актуальная Pro-ветка настраивается через `GOOGLE_AI_MODEL`;
  - для Free tier Pro-модель по pricing-докам недоступна, поэтому runtime-модель должна оставаться конфигурируемой.
- Внесены локальные изменения:
  - добавлен provider `google_ai_studio` в `llm/openai_client.py`;
  - Kie-ветка не удалена, осталась переключаемой через `LLM_PROVIDER=kie`;
  - добавлены `GOOGLE_AI_*` настройки в `settings.py` и `.env.example`;
  - обновлены README и тесты provider payload.
- Проверки:
  - `python -m pytest tests\test_llm_client.py -q` -> `6 passed`;
  - `python -m pytest -q` -> `90 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- GitHub:
  - commit: `a434d96`;
  - message: `Add Google AI Studio LLM provider`;
  - push: `origin/master`.
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` до `a434d96`;
  - серверный `.env` переключён на `LLM_PROVIDER=google_ai_studio`;
  - `GOOGLE_AI_API_KEY` добавлен только в серверный `.env`, в репозиторий не записывался;
  - Kie-настройки оставлены в `.env`, быстрый возврат возможен через `LLM_PROVIDER=kie`;
  - `GOOGLE_AI_MODEL=gemini-3-flash-preview`;
  - серверный `.venv/bin/python -m pytest -q` -> `90 passed`;
  - smoke direct Google chat completion -> `error_type=None`, ответ получен;
  - smoke direct Google tool-call -> `search_products` tool call получен и распарсен;
  - `amix-telegram-demo.service` перезапущен и проверен: `active/running/enabled`.

## Итерация 42 - LLM audit log

- По запросу пользователя добавлен ротационный audit-файл LLM provider-вызовов.
- Внесено:
  - новый модуль `llm/audit_log.py`;
  - настройки `LLM_AUDIT_LOG_ENABLED`, `LLM_AUDIT_LOG_PATH`, `LLM_AUDIT_LOG_MAX_ENTRIES`, `LLM_COST_USD_TO_RUB`;
  - запись audit entry из HTTP-compatible provider flow;
  - в audit entry сохраняются provider, model, endpoint, attempt, HTTP status, duration, полный JSON request, raw JSON response, usage tokens, cost estimate, error и tool-call summary;
  - `Authorization` в audit-файле заменяется на `<redacted>`;
  - скрипт просмотра `scripts/show_llm_audit.py`.
- Цены:
  - добавлена встроенная таблица Google paid-tier estimate для `gemini-3-flash-preview` и `gemini-3.1-pro-preview`;
  - для Gemini output estimate учитывает inferred thinking tokens: `max(completion_tokens, total_tokens - prompt_tokens)`;
  - расчёт в рублях использует конфиг `LLM_COST_USD_TO_RUB`.
- Проверки:
  - `python -m pytest tests\test_llm_client.py -q` -> `7 passed`;
  - `python -m pytest -q` -> `91 passed`;
  - `python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.
- VPS:
  - `/root/amix` обновлён через `git pull --ff-only` до `93ea79c`;
  - серверный `.env` дополнен `LLM_AUDIT_LOG_ENABLED=true`, `LLM_AUDIT_LOG_PATH=data/logs/llm_audit_recent.json`, `LLM_AUDIT_LOG_MAX_ENTRIES=100`, `LLM_COST_USD_TO_RUB=100`;
  - серверный `.venv/bin/python -m pytest -q` -> `91 passed`;
  - smoke direct Google request записал audit: первый provider attempt получил retryable `503`, следующий attempt завершился успешно с текстом `OK`;
  - исправлен запуск `scripts/show_llm_audit.py` из папки проекта через добавление project root в `sys.path`.

## Итерация 55 - защита от преждевременного handoff при нескольких вариантах товара

- Получен live-кейс от AMIX:
  - клиент спросил цвет/покрытие по артикулу `CWJ102M`;
  - бот нашёл несколько вариантов `CWJ-102`, попросил уточнить код товара или цену, но в том же сообщении добавил передачу менеджеру;
  - backend воспринял фразу `Передаю вопрос менеджеру` как реальный handoff, поэтому следующее сообщение клиента с кодом товара получило ответ `Менеджер уже вызван`.
- Root cause:
  - в `_reply_from_product_result` работала защита от текстового handoff без tool-call;
  - она корректно превращает фразу `Передаю менеджеру` в реальное действие, но не учитывала состояние `pending_clarification`;
  - для нескольких вариантов товара handoff не нужен, пока клиент не уточнил код/цену или сам не попросил человека.
- Изменения:
  - добавлен regression-тест `test_assistant_service_does_not_handoff_when_multiple_variants_need_clarification`;
  - если по товару ожидается уточнение варианта и ответ модели содержит фразу handoff, клиентский текст заменяется безопасным fallback-ответом с просьбой уточнить код товара/цену;
  - handoff в этом сценарии не регистрируется, статус чата остаётся активным;
  - в `llm/prompts.py` добавлено правило: при нескольких вариантах не передавать менеджеру и не обещать подключение менеджера, если клиент сам этого не просил.
- Проверки:
  - `python -m pytest tests/test_assistant_service.py::test_assistant_service_does_not_handoff_when_multiple_variants_need_clarification -q` -> `1 passed`;
  - `python -m pytest tests/test_assistant_service.py -q` -> `65 passed`;
  - `python -m pytest -q` -> `133 passed`.
- Git:
  - создан и отправлен commit `3d167f5 Avoid handoff while product variant is ambiguous`.
- VPS deploy:
  - `/root/amix` обновлён `git pull --ff-only origin master` до `3d167f5`;
  - серверная проверка `.venv/bin/python -m pytest -q` -> `133 passed`;
  - перезапущены `amix-api.service` и `amix-telegram-demo.service`;
  - оба сервиса проверены как `active/running`;
  - внешний healthcheck `https://amix.cifresh.ru/health` вернул `200 {"status":"ok"}`.

## Итерация 54 - защита точных остатков от парсинга

- Получено требование AMIX: при запросах доступного количества не раскрывать точный свободный остаток, а спрашивать требуемое количество и отвечать только да/нет; после 3 попыток по одному коду передавать диалог менеджеру.
- В `core/assistant_service.py` добавлен backend guard для stock-only/product-check ответов:
  - если клиент спрашивает наличие/остаток без количества, бот просит уточнить требуемое количество;
  - если количество указано, бот отвечает только `Да, такое количество есть в наличии.` или `Нет, такого количества сейчас нет в наличии.`;
  - точный остаток не выводится в клиентский текст;
  - попытки считаются по коду товара в payload bot-сообщений `stock_quantity_guard`;
  - на третьей попытке по тому же коду регистрируется handoff с причиной `stock_quantity_attempt_limit`.
- Доработан follow-up: ответ клиента вроде `5 шт` после вопроса о количестве привязывается к последнему найденному товару.
- Парсер требуемого количества ужесточён, чтобы цифры внутри артикула вроде `AB-123` не считались количеством.
- В fallback для нехватки количества убрано раскрытие точного остатка.
- В `llm/prompts.py` правила наличия синхронизированы с новой политикой: не раскрывать точный остаток, просить количество, отвечать да/нет.
- В `tests/test_assistant_service.py` обновлены старые ожидания точного остатка и добавлены regression-тесты для:
  - запроса количества вместо точного остатка;
  - подтверждения достаточного количества без точного остатка;
  - отказа при недостаточном количестве без точного остатка;
  - follow-up `5 шт` по последнему товару;
  - handoff на третьей попытке по одному коду;
  - защиты от распознавания цифр в артикуле как количества.
- Проверки:
  - `python -m pytest tests/test_assistant_service.py -q` -> `63 passed`;
  - `python -m pytest -q` -> `132 passed`.
- Git:
  - создан и отправлен commit `aeec1c2 Protect stock quantities from scraping`.
- VPS deploy:
  - `/root/amix` обновлён `git pull --ff-only origin master` до `aeec1c2`;
  - серверная проверка `.venv/bin/python -m pytest -q` -> `132 passed`;
  - фактические сервисы на VPS: `amix-api.service` и `amix-telegram-demo.service`;
  - перезапущены `amix-api.service` и `amix-telegram-demo.service`;
  - оба сервиса проверены как `active/running`;
  - внешний healthcheck `https://amix.cifresh.ru/health` вернул `200 {"status":"ok"}`.

## Итерация 52 - Google tool history log shape

- По присланным Google Logs разобрана форма отображения:
  - вариант `assistant.tool_calls` + `role=tool` отображается хронологически как `functionCall` и `functionResponse`;
  - вариант с `TOOL_RESULTS_JSON` в `system` отображается только в `systemInstruction`;
  - текущий merged-system стиль также не дает хронологического tool-события в Google UI.
- Серверный audit последнего 400:
  - текущий деплой был на commit `4c1c580`;
  - последняя error-запись имела роли `["system", "user", "assistant", "tool"]`;
  - Google вернул HTTP 400 с причиной: `Function call is missing a thought_signature in functionCall parts`;
  - проблема воспроизводится, когда финальный запрос заканчивается на `role=tool` / `functionResponse`.
- В `llm/openai_client.py` добавлена подготовка Google payload:
  - system-сообщения по-прежнему объединяются в один `systemInstruction`;
  - если финальный Google-запрос заканчивается на `role=tool`, добавляется неперсистентное user-сообщение с просьбой сформулировать ответ по результату функции;
  - это сохраняет tool result в хронологической части payload и не записывает техническую инструкцию в историю диалога.
- В `tests/test_llm_client.py` добавлен regression-тест для payload, который заканчивается tool result.
- Проверка:
  - `PYTHONPATH=. pytest tests/test_llm_client.py::test_google_ai_studio_payload_preserves_tool_role_history tests/test_llm_client.py::test_google_ai_studio_payload_appends_final_instruction_after_tool_result -q` -> `2 passed`.
  - `PYTHONPATH=. pytest -q` -> `113 passed`.
- VPS direct shape check:
  - `assistant(functionCall) -> tool(functionResponse)` как последний turn -> HTTP 400;
  - `assistant(functionCall) -> tool(functionResponse) -> user final instruction` -> HTTP 200.
- VPS deploy:
  - `/root/amix` обновлён `git pull --ff-only origin master` до `b46dd4e`;
  - `.venv/bin/python -m pytest tests/test_llm_client.py::test_google_ai_studio_payload_appends_final_instruction_after_tool_result -q` -> `1 passed`;
  - `.venv/bin/python -m pytest -q` -> `113 passed`;
  - `systemctl restart amix-telegram-demo.service`;
  - `systemctl show amix-telegram-demo.service -p ActiveState -p SubState` -> `active/running`.
- VPS smoke:
  - через `AssistantService` выполнен запрос с marker `AMIX_GOOGLE_CHRONO_SERVICE_TEST_AFTER_FIX_20260520`;
  - первый Google request вернул tool call `search_products`;
  - финальный Google request после `role=tool` ушёл с добавленной user-инструкцией и получил HTTP 200;
  - audit показал роли финального запроса: `system`, `user`, `assistant`, `tool`, `user`.

## Итерация 53 - repair server product row 14.023пр

- По live-логу пользователя модель корректно вызвала `search_products` с query `14.023пр`, но tool result вернул `не_найдено`.
- На VPS проверена строка товара `code=770`:
  - поля `article`, `normalized_article`, `unit` были повреждены как `14.023??.`, `14023??`, `??`;
  - `raw_payload` сохранил исходные XML-значения.
- Причина:
  - повреждение появилось после ручного smoke-скрипта, который обновлял товарную строку на сервере напрямую;
  - это не ошибка LLM и не ошибка Google tool-calling.
- Выполнено на VPS:
  - восстановлены `Product.article`, `Product.normalized_article`, `Product.unit` для кодов `769` и `770` прямыми Unicode-значениями;
  - подтверждены кодпоинты `14.023пр.` (`\u043f\u0440`) и `шт` (`\u0448\u0442`);
  - `_search_products_by_queries(["14.023пр", "xyz-999"])` теперь возвращает:
    - `14.023пр` -> `exact_found`, code `770`, stock `220.000`, price `473 руб.`;
    - `xyz-999` -> `not_found`.
## Итерация 32 - cleanup LLM payload после проверки Kie-логов

- По Kie-логу подтверждено:
  - role-based история уже работает;
  - payload всё ещё дублировал полный поиск в `INTERNAL_CONTEXT_JSON` и `TOOL_RESULTS_JSON`;
  - `TOOL_RESULTS_JSON` шёл до role-history;
  - в запросе не было явных параметров `temperature`, `top_p`, `stream`, `max_completion_tokens`;
  - нужны phase-логи для диагностики 500 после/до отправки ответа.
- `llm/prompts.py`:
  - `build_product_facts_messages` больше не кладёт полный `product_lookup_result` в top-level `INTERNAL_CONTEXT_JSON`;
  - backend-prelookup маркируется как `mode=backend_prelookup`;
  - `TOOL_RESULTS_JSON` добавляется после role-based истории и текущего user-сообщения.
- `core/assistant_service.py`:
  - `dialog_state.last_product_lookup` стал компактнее;
  - добавлены `llm_request_started` и `llm_response_received` в LLM debug JSONL;
  - product/prelookup debug note теперь явно указывает, что это final-answer request без tools.
- `llm/openai_client.py` и `settings.py`:
  - добавлены Kie-параметры `temperature=0.6`, `top_p=1`, `parallel_tool_calls=false`, `stream=false`;
  - обычный текст в Kie payload теперь отправляется строкой `content`, без `type=text` parts;
  - `stream_options` проект не добавляет.
- `core/message_processor.py`:
  - добавлены фазовые логи отправки ответа клиенту;
  - ошибки `invite_agent` после отправки ответа логируются как `phase=error_after_send`.
- Тесты:
  - обновлены проверки Kie payload;
  - добавлена проверка порядка сообщений: `system`, `INTERNAL_CONTEXT_JSON`, role-history/current user, затем `TOOL_RESULTS_JSON`;
  - добавлена проверка отсутствия top-level full `last_product_lookup` в internal context.
- Проверки:
  - `python -m pytest -q` -> `74 passed`;
  - `python scripts/run_dialog_regression_eval.py --output DIALOG_EVALS.md` -> `OK=31 PARTIAL=0 FAIL=0`.

## Итерация 54 - history-driven заказ: количества по товарам

- Обновлён контракт `search_products`: каждый элемент `queries` содержит собственные `query` и необязательное `requested_quantity`.
- Backend нормализует положительные количества, проверяет их независимо и возвращает модели только признак доступности нужного количества.
- Точный свободный остаток удалён из model-visible tool result, `active_product`, `product_memory` и runtime context.
- Сохранён исходный порядок всех запросов, включая повторные; общий список товаров остаётся дедуплицированным.
- Исправлен контекстный follow-up: явный новый товар имеет приоритет над прошлой позицией, а короткое количество без товара относится к текущей позиции.
- Лимит анти-парсинга проверяется по полной истории и отдельно для каждого кода.
- `ASSISTANT_BACKEND_PRELOOKUP_ENABLED` по умолчанию и в `.env.example` установлен в `false`.
- Промпт заказа сокращён и обобщён; модель по-прежнему использует полную хронологическую историю, показывает итог, ждёт подтверждение и только затем вызывает `handoff_to_manager`.
- Проверки:
  - целевые тесты количества и приватности -> пройдены;
  - `python -m pytest -q` -> `163 passed`;
  - `python -m compileall api core database jivo llm products scripts -q` -> успешно;
  - `git diff --check` -> ошибок нет, только предупреждения Git о преобразовании LF/CRLF.

## Итерация 55 - удаление сценарного backend и исправления независимого аудита

- По требованию архитектура сведена к model-driven диалогу:
  - в модель передаётся вся сохранённая история с ролями `user`, `assistant`, вызовами функций и результатами функций;
  - в runtime доступны только `search_products` и `handoff_to_manager`;
  - backend не определяет намерение по словам, не использует локальный заказ, `active_product`, `product_memory`, `pending_clarification`, `backend_actions` или prelookup;
  - решение о поиске, вопросах клиенту, итоговой сверке и handoff принимает Gemini по системному промпту.
- Контракт `search_products` упрощён до списка объектов `query` + необязательного `requested_quantity`; поле `intent` отсутствует.
- Из товарного результата удалены внутренние и пустые поля `search_type`, `query_normalized`, `backend_notes`, `category`, `tags`.
- Удалены неиспользуемые `get_product_by_article`, `get_similar_products` и старый генератор `products/product_search.py`.
- Исправления после независимого критического ревью:
  - при ошибке SQLite сначала выполняется rollback, затем событие помечается failed в рабочей транзакции;
  - устаревшая ветка model/tool-истории удаляется целиком, но статистика LLM сохраняется;
  - недоставленный Jivo/Telegram ответ удаляется из истории;
  - handoff фиксируется только после принятого `INVITE_AGENT`, а терминальный статус оператора не перезаписывается;
  - повтор ранее failed Jivo-события разрешён без дублирования клиентского сообщения;
  - незавершённые события восстанавливаются при старте;
  - shutdown приложения инвалидирует отложенные потоки, поэтому они не работают с новой БД после перезапуска.
- В fake-eval добавлена строгая JSON Schema-проверка аргументов реальных функций. Старые лишние аргументы теперь приводят к падению теста.
- Проверки:
  - `python -m pytest -q` -> `132 passed`;
  - `python scripts/run_dialog_regression_eval.py` -> `PASS=9 FAIL=0`;
  - `python scripts/run_history_order_eval.py --fake --repeat 3 ...` -> `27/27` сценариев, `123/123` ходов, `PASS`;
  - `python -m compileall -q api core database jivo llm products scripts` -> успешно;
  - runtime-скан не нашёл `intent`, prelookup, backend state или keyword-классификацию.
- Fake-eval используется только как проверка проводки. До деплоя обязателен отдельный live-прогон Gemini на VPS и ручная оценка реальных ответов.

## Итерация 56 - настоящий Gemini, полная история и финальная проверка архитектуры

- Повторно проверен runtime на отсутствие сценарного backend:
  - нет словарей намерений, keyword-routing, извлечения артикулов/количеств из текста клиента и скрытого состояния заказа;
  - `AssistantService` передаёт Gemini полную сохранённую историю и исполняет только `search_products` и `handoff_to_manager`;
  - регулярные выражения в проекте используются только для технических границ: каталожного сопоставления уже выбранного моделью запроса, маскирования персональных данных и безопасных имён файлов/идентификаторов.
- При первом live-прогоне обнаружен HTTP 400 после вызова функции Gemini 3. Причина: следующий запрос не возвращал обязательный `thought_signature` исходного function call.
- В `llm/openai_client.py` добавлено сохранение `extra_content.google.thought_signature`; `AssistantService` сохраняет его вместе с хронологическим assistant tool call, а `DialogService` восстанавливает при следующем запросе.
- Системный промпт доработан обобщёнными правилами без нового backend-routing:
  - сведения заказа собираются из полной истории;
  - исправления клиента имеют приоритет;
  - ненайденное свободное описание не блокирует заявку;
  - итог показывается клиенту перед передачей;
  - недостаточное количество не вызывает немедленный handoff;
  - точный остаток клиенту не раскрывается.
- Локальная проверка:
  - `python -m pytest -q` -> `133 passed`;
  - deterministic history-eval с тремя повторами -> `27/27` сценариев, `123/123` ходов, `PASS`;
  - `python -m compileall -q api core database jivo llm products scripts` -> успешно;
  - `git diff --check` -> ошибок нет.
- Изолированная live-проверка на VPS, без изменения production checkout и без остановки сервисов:
  - провайдер/модель: Google AI Studio / `gemini-3.1-flash-lite`;
  - полный прогон -> `9/9` сценариев, `41/41` ходов, `PASS`;
  - сценарий смешанной доступности повторён три раза -> `3/3` сценария, `12/12` ходов, `PASS`;
  - сценарий товара, описанного свободным текстом, повторён три раза -> `3/3` сценария, `15/15` ходов, `PASS`;
  - полный прогон использовал 53 обращения, 170 875 токенов, около 5,59 рубля и 74,6 секунды суммарной provider-latency.
- Live-отчёты загружены с VPS и сохранены локально:
  - `outputs/amix-live-be3db6e.md`;
  - `outputs/amix-live-be3db6e.json`;
  - `outputs/amix-mixed-live-be3db6e.md` / `.json`;
  - `outputs/amix-free-live-5d3851a.md` / `.json`.
- Дополнительный запуск независимых агентов в этой итерации не стартовал из-за исчерпанного лимита agent threads. Ранее выполненный независимый аудит уже выявил и помог исправить гонки handoff, откат транзакций, удаление устаревшей истории, повтор failed-событий и восстановление незавершённых событий.
- Production deploy:
  - перед обновлением `/root/amix` находился на `a0c56bb`, оба сервиса были активны; незакоммиченными оставались только рабочие `data/amix_jivo.db-wal` и `data/amix_jivo.db-shm`;
  - выполнены `git fetch` и `git merge --ff-only` до `060e107`, без `reset`, удаления или перезаписи данных;
  - зависимости синхронизированы из `requirements.txt`;
  - серверный `./.venv/bin/python -m pytest -q` -> `133 passed`;
  - перезапущены `amix-api.service` и `amix-telegram-demo.service`, оба -> `active/running`;
  - `http://127.0.0.1:8010/health` и `https://amix.cifresh.ru/health` -> `{"status":"ok"}`;
  - журнал обоих сервисов после перезапуска не содержит `error`, `exception`, `traceback` или `failed`.
