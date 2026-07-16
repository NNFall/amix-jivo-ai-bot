# amix-jivo

## Dialog Eval History

Для фиксации тестовых прогонов диалогов и анализа качества ответов:

```bash
python scripts/run_dialog_eval.py --scenario smoke --output DIALOG_EVALS.md
```

Скрипт записывает в `DIALOG_EVALS.md` план LLM, lookup-вызовы и финальные ответы по каждому ходу.

## LLM/Tools Spec

- Архитектурная спецификация: `docs/LLM_IMPLEMENTATION_SPEC.md`
- Полный snapshot промптов и tool-схем: `docs/PROMPTS_AND_TOOLS_REFERENCE.md`

MVP-каркас Python-сервиса для AI-бота первой линии AMIX с интеграцией в Jivo Bot API, SQLite, XML-импортом товаров из 1С и OpenAI как диалоговым слоем.

## Что уже есть

- FastAPI backend с `health` и webhook для Jivo.
- Быстрый ACK входящего события и фоновая обработка через `BackgroundTasks`.
- SQLite-хранилище для событий, чатов, сообщений, товаров, XML-импортов, черновиков заказов, LLM-статистики и handoff-событий.
- Базовый Jivo client для `BOT_MESSAGE` и `INVITE_AGENT`.
- Базовая логика поиска товара по артикулу и безопасной передачи менеджеру.
- Сбор заказа по этапам с итоговым резюме и обязательным подтверждением клиента перед передачей менеджеру.
- Скрипты для импорта XML и локальной симуляции webhook-события.

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

Сервис поднимется на `http://127.0.0.1:8000`.

## Переменные окружения

- `LLM_PROVIDER`: `openai`, `kie` или `google_ai_studio`.
- `JIVO_WEBHOOK_TOKEN`: токен в URL входящего webhook.
- `JIVO_BOT_API_URL`: исходящий endpoint Jivo Bot API для отправки сообщений и `INVITE_AGENT`.
- `OPENAI_API_KEY`: ключ OpenAI API.
- `KIE_API_KEY`: ключ KIE API для модели через KIE.
- `KIE_CHAT_MODEL_PATH`: путь chat completions endpoint, по умолчанию `/gemini-3-pro/v1/chat/completions`.
- `GOOGLE_AI_API_KEY`: ключ Google AI Studio/Gemini API для прямого подключения без KIE.
- `GOOGLE_AI_MODEL`: модель Gemini для прямого Google API, по умолчанию `gemini-3.1-flash-lite`.
- `LLM_AUDIT_LOG_ENABLED`: включает ротационный аудит реальных provider-запросов.
- `LLM_AUDIT_LOG_PATH`: JSON-файл последних LLM-запросов, по умолчанию `data/logs/llm_audit_recent.json`.
- `LLM_AUDIT_LOG_MAX_ENTRIES`: сколько последних provider-запросов хранить, по умолчанию `100`.
- `LLM_COST_USD_TO_RUB`: курс для пересчёта estimate из USD в RUB, по умолчанию `100`.
- `DATABASE_URL`: SQLite-путь или другой SQLAlchemy-compatible DSN.

## Полезные команды

```bash
pytest
python scripts\simulate_jivo_event.py --text "Есть артикул AB-123?"
python scripts\import_xml.py --path data\incoming_xml\products.xml
python scripts\run_telegram_demo.py
python scripts\show_llm_audit.py --limit 20
```

## Telegram Demo

Для демонстрационной версии без Jivo можно запустить Telegram-бота long polling:

- заполнить `.env` минимум полями `TELEGRAM_BOT_TOKEN`, `DATABASE_URL` и ключом выбранного LLM-провайдера (`OPENAI_API_KEY`, `KIE_API_KEY` или `GOOGLE_AI_API_KEY`);
- при необходимости заранее импортировать XML в базу;
- запустить `python scripts\run_telegram_demo.py`.

Telegram demo использует ту же SQLite-базу, историю диалогов, товарный поиск и guardrails по handoff. Для вопросов, требующих менеджера, бот честно сообщает, что в рабочем Jivo-сценарии передал бы диалог оператору.

Для тестирования в Telegram есть команда `/newchat`: она очищает контекст текущего демо-чата и позволяет начать новый диалог с нуля.

LLM debug-логи по умолчанию отключены, потому что могут содержать переписку и контактные данные. Для временной диагностики их можно явно включить через `ASSISTANT_DEBUG_LLM_PAYLOADS=true`; записи появятся в `data/logs/llm_debug.jsonl`.

Ротационный provider-аудит пишется в `data/logs/llm_audit_recent.json`, если `LLM_AUDIT_LOG_ENABLED=true`. Там хранятся последние `LLM_AUDIT_LOG_MAX_ENTRIES` HTTP-вызовов к LLM: полный JSON запроса, raw JSON ответа, latency, usage tokens и примерная стоимость. API-ключи в файл не пишутся.

Суммарная статистика каждого рабочего вызова LLM хранится без ротации в таблице `llm_calls`: модель, назначение вызова, токены, отдельно вычисленные thinking-токены, время ответа и оценка расходов в долларах и рублях. Общие токены, число запросов и расход видны на `/admin`. Gemini возвращает usage вместе с ответом, поэтому отдельный запрос за токенами не выполняется. Ротируемый provider-аудит сохраняется отдельно и маскирует телефон, email, ИНН, КПП и реквизиты плательщика.

При намерении оформить заказ Gemini ведёт диалог по полной хронологической истории без отдельного backend-черновика. Бот последовательно собирает товары и количество, желаемый срок, получение, оплату, имя и телефон; для оплаты по счёту дополнительно уточняет ИНН. Затем показывает клиенту краткий итог и только после явного подтверждения вызывает `handoff_to_manager` с готовым резюме.

Модели доступны только две функции: `search_products` и `handoff_to_manager`. История диалога передаётся полностью, с первого сообщения, отдельными role-сообщениями `user`, `assistant` и хронологическими вызовами/результатами функций. Точные остатки перед отправкой модели скрываются; для каждой заказанной позиции передаётся только результат проверки запрошенного количества.

Повторяемый стенд длинных заказных диалогов запускается командой `python scripts\run_history_order_eval.py --fake --repeat 2 --output data\logs\history-order.json --markdown-output data\logs\history-order.md`. Без `--fake` стенд использует настроенный Gemini, изолированную временную SQLite-базу и demo-handoff без отправки событий в реальные чаты Jivo.

## Дальше по плану

- Довести сценарии обработки Jivo до рабочего MVP с реальными payload-образцами.
- Уточнить структуру XML AMIX и довести маппинг полей до production-ready состояния.
- Подключить реальный OpenAI flow и отладить handoff-сценарии на стенде Jivo.
