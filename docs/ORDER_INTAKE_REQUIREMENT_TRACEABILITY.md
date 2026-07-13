# Order Intake Requirement Traceability

## Requirement matrix

| Source requirement | Implemented behavior | Evidence |
|---|---|---|
| Андрей: "Если клиент хочет оформить заказ, бот же может уточнить, что нужно клиенту" | Order intent no longer triggers the backend handoff rule. Gemini calls `update_order_draft` and asks for the next missing field. | `core/handoff_service.py`, `core/assistant_service.py`, `test_order_request_starts_intake_without_immediate_handoff` |
| Артём: "Не важно, знает клиент артикулы/коды или нет" | Each item accepts either an identifier or a free-form description. No product recommendation is inferred from the description. | `core/order_intake_service.py`, `test_order_draft_accepts_free_form_item_and_waits_for_confirmation` |
| Артём: "Далее бот уточняет контакты, когда нужно и реквизиты" | The draft requires desired timing, fulfillment, payment, contact name and phone/email. | `core/order_intake_service.py`, `test_order_draft_requires_desired_timing_without_promising_delivery_date` |
| Пользователь: "для счета ... какие конкретно данные собирать" | Bank transfer requires payer type, organization/IP name, INN, contact phone and invoice email. KPP is optional for IP. Card details are forbidden. | `llm/prompts.py`, `llm/tool_schemas.py`, `test_bank_transfer_draft_requires_invoice_details_but_not_kpp_for_ip`, `test_bank_transfer_requires_phone_even_when_invoice_email_is_present` |
| Пользователь: "чтобы он финально ... summary в диалоге подводил" | A complete draft first becomes `ready_for_confirmation`; only after the backend-built canonical summary is saved as a customer-visible message does it become `awaiting_confirmation`. | `core/order_intake_service.py`, `core/assistant_service.py`, `test_complete_order_is_handed_off_only_after_explicit_confirmation` |
| Пользователь: "клиент отвечает да, и уже тогда он переводит на менеджера" | Order handoff is allowed only when the canonical summary is the immediately preceding visible bot message and the latest user message explicitly confirms it. Alternative model handoff reasons cannot bypass this invariant. | `core/assistant_service.py`, `test_order_handoff_tool_is_blocked_before_confirmation`, `test_order_confirmation_is_blocked_if_canonical_summary_was_not_shown`, `test_active_order_blocks_alternative_llm_handoff_reason` |
| Пользователь: "количество токенов за каждое сообщение ... фиксировать у себя в локальной базе данных" | Every production AssistantService provider call creates a durable `llm_calls` row with usage, latency and estimated cost. No second Google request is made, and later Jivo rollback cannot remove the usage row. | `database/models.py`, `core/assistant_service.py`, `test_assistant_persists_llm_usage_for_each_provider_call`, `test_llm_usage_survives_later_transaction_rollback` |
| Андрей: zero-stock rows are omitted from XML; answer that the product may be unavailable or the code incorrect | All no-candidate not-found responses, including order intake, use the guarded wording and do not claim the product does not exist. | `core/assistant_service.py`, `test_missing_code_wording_is_guarded_when_llm_omits_out_of_stock_explanation`, `test_order_not_found_warning_overrides_unsafe_llm_claim` |
| Пользователь: exact stock should not be exposed | Order product checks return only whether the requested quantity is available. | `core/order_intake_service.py`, `test_identified_product_check_returns_only_yes_or_no_for_requested_quantity` |
| Пользователь: a newer message must cancel the old neural response | A stale second order-intake call rolls back draft/tool/reply changes, stores only both LLM usage rows and returns a superseded reply. | `core/assistant_service.py`, `test_stale_order_intake_turn_keeps_usage_but_discards_hidden_state` |
| AGENTS.md: dissatisfied customers must be handed off | `client_dissatisfied` remains an immediate valid handoff even while an order draft is active. | `core/assistant_service.py`, `test_dissatisfied_customer_can_handoff_during_active_order` |
| Handoff is an action, not a phrase | Jivo `INVITE_AGENT` is attempted before the handoff promise is sent; invite failure sends no false promise. | `core/message_processor.py`, `tests/test_message_processor.py` |
| Product can be named before quantity | The tool schema accepts an item without quantity; the draft keeps it and asks for the missing amount. | `llm/tool_schemas.py`, `test_order_tool_allows_item_before_quantity_is_known` |
| Unknown stock is not a shortage | Missing source stock produces `available=null`, not `false`. | `core/order_intake_service.py`, `test_identified_product_with_unknown_stock_keeps_availability_unknown` |
| Provider diagnostics must not expose order contacts | The rotating audit masks phone, email, INN, KPP and organization/contact fields and restricts file permissions. | `llm/audit_log.py`, `test_provider_audit_redacts_order_contact_and_invoice_data` |
| Пользователь: PDF, Excel and photo parsing was not requested | Attachment parsing was not added. | Scope statement in the design specification; no attachment parser changes in the diff. |

## Handoff invariant

An order handoff is valid only when the stored draft is complete, the immediately preceding visible bot message is the stored canonical summary, the latest client message explicitly confirms it and Gemini calls `handoff_to_manager` with the order reason. Any other model-initiated handoff is blocked while the order draft is active. Direct requests for an operator remain immediate.

## Pricing source

The local estimate for `gemini-3.1-flash-lite` uses the standard paid rate reviewed on 2026-07-13: USD 0.25 per 1M input tokens and USD 1.50 per 1M output tokens including thinking. The RUB value uses `LLM_COST_USD_TO_RUB` and is an estimate, not a Google invoice.
