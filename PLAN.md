# PLAN

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

- Статус: in progress.
- Цель:
  - добавить прямой LLM-провайдер Google AI Studio/Gemini API через OpenAI-compatible `chat/completions`;
  - оставить Kie-интеграцию в коде и конфиге как быстрый fallback через `LLM_PROVIDER=kie`;
  - переключить VPS на новый provider через `.env`, не сохраняя ключи в репозитории;
  - протестировать реальный запрос именно на VPS.
- Важные ограничения:
  - `gemini-3-pro-preview` по официальной документации уже выключен;
  - актуальная Pro-замена должна быть настраиваемой через `GOOGLE_AI_MODEL`;
  - если Free tier не пропускает Pro-модель, переключить runtime на доступную модель и зафиксировать результат проверки.
