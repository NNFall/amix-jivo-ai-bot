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
- SQLite-хранилище для событий, чатов, сообщений, товаров, XML-импортов и handoff-событий.
- Базовый Jivo client для `BOT_MESSAGE` и `INVITE_AGENT`.
- Базовая логика поиска товара по артикулу и безопасной передачи менеджеру.
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

- `LLM_PROVIDER`: `openai` или `kie`.
- `JIVO_WEBHOOK_TOKEN`: токен в URL входящего webhook.
- `JIVO_BOT_API_URL`: исходящий endpoint Jivo Bot API для отправки сообщений и `INVITE_AGENT`.
- `OPENAI_API_KEY`: ключ OpenAI API.
- `KIE_API_KEY`: ключ KIE API для модели через KIE.
- `KIE_CHAT_MODEL_PATH`: путь chat completions endpoint, по умолчанию `/gemini-3-pro/v1/chat/completions`.
- `DATABASE_URL`: SQLite-путь или другой SQLAlchemy-compatible DSN.

## Полезные команды

```bash
pytest
python scripts\simulate_jivo_event.py --text "Есть артикул AB-123?"
python scripts\import_xml.py --path data\incoming_xml\products.xml
python scripts\run_telegram_demo.py
```

## Telegram Demo

Для демонстрационной версии без Jivo можно запустить Telegram-бота long polling:

- заполнить `.env` минимум полями `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `DATABASE_URL`;
- при необходимости заранее импортировать XML в базу;
- запустить `python scripts\run_telegram_demo.py`.

Telegram demo использует ту же SQLite-базу, историю диалогов, товарный поиск и guardrails по handoff. Для вопросов, требующих менеджера, бот честно сообщает, что в рабочем Jivo-сценарии передал бы диалог оператору.

Для тестирования в Telegram есть команда `/newchat`: она очищает контекст текущего демо-чата и позволяет начать новый диалог с нуля.

LLM debug-логи пишутся в `data/logs/llm_debug.jsonl`, если `ASSISTANT_DEBUG_LLM_PAYLOADS=true`. В каждой строке JSONL видно, какие `messages` с ролями ушли в модель, какой `INTERNAL_CONTEXT_JSON` был передан, какой `product_lookup_result` использовался, какие `backend_actions` рассчитаны и какой текст вернула модель.

История диалога передаётся в LLM не строкой `Клиент/Бот`, а отдельными role-сообщениями `user`, `assistant` и, для tool flow, `tool`. Последнее сообщение клиента не дублируется отдельным блоком.

## Дальше по плану

- Довести сценарии обработки Jivo до рабочего MVP с реальными payload-образцами.
- Уточнить структуру XML AMIX и довести маппинг полей до production-ready состояния.
- Подключить реальный OpenAI flow и отладить handoff-сценарии на стенде Jivo.
