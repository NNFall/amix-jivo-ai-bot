# amix-jivo

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

- `JIVO_WEBHOOK_TOKEN`: токен в URL входящего webhook.
- `JIVO_BOT_API_URL`: исходящий endpoint Jivo Bot API для отправки сообщений и `INVITE_AGENT`.
- `OPENAI_API_KEY`: ключ OpenAI API.
- `DATABASE_URL`: SQLite-путь или другой SQLAlchemy-compatible DSN.

## Полезные команды

```bash
pytest
python scripts\simulate_jivo_event.py --text "Есть артикул AB-123?"
python scripts\import_xml.py --path data\incoming_xml\products.xml
```

## Дальше по плану

- Довести сценарии обработки Jivo до рабочего MVP с реальными payload-образцами.
- Уточнить структуру XML AMIX и довести маппинг полей до production-ready состояния.
- Подключить реальный OpenAI flow и отладить handoff-сценарии на стенде Jivo.
