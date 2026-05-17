# PLAN

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
