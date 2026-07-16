# Соответствие сценария заказа требованиям

## Матрица

| Требование | Реализованное поведение | Проверка |
|---|---|---|
| Бот собирает заказ, а не сразу зовёт менеджера | Gemini ведёт сбор по истории диалога и задаёт по одному следующему вопросу. | `llm/prompts.py`, `test_order_prompt_uses_history_instead_of_hidden_order_state` |
| Отдельная функция и скрытая память заказа не нужны | Модели объявлены только `search_products` и `handoff_to_manager`; старый `OrderDraft` не читается и не изменяется runtime-кодом. | `llm/tool_schemas.py`, `test_model_has_only_product_search_and_manager_handoff_tools`, `test_legacy_order_draft_does_not_change_routing_or_force_a_tool_retry` |
| История должна передаваться полностью | В Gemini уходит весь чат с первого сообщения, включая хронологические `assistant` function call и `tool` result. | `core/dialog_service.py`, `test_get_llm_messages_returns_complete_chronological_history`, `test_google_ai_studio_payload_preserves_tool_role_history` |
| Клиент может назвать несколько товаров с разным количеством | `search_products` принимает отдельное количество для каждого запроса, сохраняет порядок и проверяет каждую позицию независимо. | `llm/tool_schemas.py`, `test_tool_search_checks_each_requested_quantity_independently`, `test_query_quantity_metadata_is_preserved_in_source_order` |
| Код или артикул может быть неизвестен | Gemini может начать со свободного описания, уточнить недостающие сведения и искать только когда есть осмысленный запрос. | `llm/prompts.py`, сценарий `free_description_without_code` в `tests/history_order_eval_scenarios.json` |
| Для заказа нужно собрать имя, телефон и ИНН при оплате по счёту | Эти поля заданы как минимальные в обобщённом сценарии; платёжные секреты запрашивать запрещено. | `llm/prompts.py`, длинные сценарии history-order eval |
| Перед передачей нужна финальная сверка | Gemini показывает краткий итог, ждёт явного подтверждения и только затем вызывает `handoff_to_manager` с причиной `order_creation` и резюме. | `llm/prompts.py`, `test_order_creation_handoff_uses_model_summary_without_draft`, history-order eval |
| Точный остаток нельзя раскрывать | В модель и клиентский ответ не попадает свободный остаток; передаётся только да/нет для количества, указанного отдельно по каждой позиции. Старые tool-результаты очищаются при формировании истории. | `core/dialog_service.py`, `core/assistant_service.py`, `test_get_llm_messages_hides_exact_stock_from_legacy_search_results`, `test_quantity_check_tool_result_hides_exact_stock`, `test_direct_model_reply_cannot_reveal_exact_stock` |
| После трёх попыток по одному коду нужен менеджер | Попытки считаются по коду по всей истории; лимит одного товара не влияет на другой. | `test_assistant_service_handoffs_after_third_stock_quantity_attempt_for_same_code`, `test_stock_quantity_attempt_limit_is_counted_per_product_code` |
| Ненайденный товар может просто отсутствовать в XML из-за нулевого остатка | Ответ не утверждает, что товара не существует: предлагает проверить код или название и допускает отсутствие в наличии. | `test_missing_code_wording_is_guarded_when_llm_omits_out_of_stock_explanation` |
| Handoff является действием, а не фразой | Обещание подключения отправляется только после принятого Jivo `INVITE_AGENT`; отказ не маскируется успешным сообщением. | `tests/test_message_processor.py` |
| Новый вход клиента отменяет устаревший ответ | Результат старого LLM-turn не сохраняется и не отправляется, при этом статистика provider-вызова остаётся. | stale-turn тесты `tests/test_assistant_service.py` и webhook/debounce тесты |
| Токены и стоимость нужно учитывать по каждому обращению | Каждый provider-вызов сохраняет usage, latency и оценку USD/RUB в `llm_calls`; отдельный запрос к Google не выполняется. | `test_assistant_persists_llm_usage_for_each_provider_call`, `test_llm_usage_survives_later_transaction_rollback` |

## Инвариант передачи заказа

Gemini может вызвать `handoff_to_manager` для оформления только после того, как в видимой истории есть итог заказа и клиент явно его подтвердил. Резюме строится самой моделью из полной истории; отдельная функция или параллельная структура заказа не используется. Прямая просьба клиента позвать человека остаётся немедленным handoff.

## Воспроизводимая проверка

`scripts/run_history_order_eval.py` прогоняет длинные диалоги через реальный `AssistantService`, настоящий поиск товаров и две production-схемы функций. База временная, Jivo отключён, JSON и Markdown содержат диалог, вызовы функций, результаты, latency, токены, стоимость и машинные проверки. Live-режим использует Gemini; `--repeat N` повторяет каждый сценарий в отдельном чате.
