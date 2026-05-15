# PLAN

## Текущий статус

LLM-слой расширен под `kie.ai` с моделью `gpt-5-2`, локальные и live-тесты API прошли. На VPS `.env` уже подготовлен под KIE, остаётся только подтянуть свежий код и дождаться Telegram token/XML для живого демо.

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
   Статус: in progress.
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

## Что осталось сделать

- Уточнить реальные payload-структуры Jivo на стенде и скорректировать схемы/обработчик.
- Получить реальный XML AMIX и донастроить алиасы полей и обработку больших файлов.
- Проверить реальные исходящие вызовы `BOT_MESSAGE` и `INVITE_AGENT` против рабочего endpoint Jivo.
- Довести OpenAI routing: отделить intent detection от генерации ответа и добавить явные guardrails для сложных консультаций.
- Проверить XML importer на реальном файле AMIX и уточнить alias-набор под фактические теги.
- Задеплоить Telegram demo на VPS, поднять venv/systemd и проверить живой polling.
- Получить реальные `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY` и XML-файл AMIX для рабочего демо.
- Заполнить `/root/amix/.env` рабочими значениями и импортировать реальный XML в SQLite.
- Запустить и проверить `amix-telegram-demo.service` на живом Telegram-боте.
- Подтянуть на VPS commit с поддержкой KIE и повторно проверить LLM-вызов уже из серверного кода.

## Открытые вопросы

- Нужны реальные примеры payload Jivo, особенно для событий после handoff и недоступности агента.
- Нужен реальный XML AMIX для точной настройки маппинга полей и оценки объёма импорта.
- Нужно подтвердить фактический формат исходящего webhook URL Jivo для конкретного bot channel.
- Нужно понять, достаточно ли `BackgroundTasks` для пилота AMIX или нужен более надёжный local queue/worker уже на MVP-этапе.
- Нужно определить допустимую политику повторных импортов одного и того же файла (по checksum/mtime) для production-режима.
- Нужны реальные секреты для live demo: Telegram bot token и OpenAI API key.
- Нужен реальный XML-файл или источник XML для наполнения демо-базы товарами.
- Нужен сценарий выдачи заказчику доступа к Telegram demo: какой именно бот и какие тестовые чаты использовать.
- Нужен рабочий `TELEGRAM_BOT_TOKEN` для финального запуска демонстрационного бота.

## Технические риски

- Публичная Bot API-документация Jivo не описывает все возможные входящие события одинаково подробно.
- Без реального XML есть риск недомаппить нестандартные теги AMIX.
- `BackgroundTasks` подходит для MVP, но не даёт надёжной очереди при падении процесса.
- Без sandbox-стенда Jivo пока невозможно полноценно подтвердить формат реальных исходящих payload и handoff-ответов.
- Без production-файла AMIX остаётся риск неполного покрытия нестандартных XML-тегов.
- Без реального Telegram bot token сервис нельзя довести до живого публичного демо на VPS.
- Без OpenAI API key демо останется только на product lookup и безопасном fallback без полноценного диалога.
- Если KIE API изменит формат `chat/completions`, потребуется скорректировать адаптер провайдера.

## Ближайший следующий шаг

Закоммитить и запушить KIE-интеграцию, подтянуть её на VPS, затем дождаться Telegram token и XML-файла AMIX для финального запуска `amix-telegram-demo.service`.
