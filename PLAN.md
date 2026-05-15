# PLAN

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

## Что осталось сделать

- Уточнить реальные payload-структуры Jivo на стенде и скорректировать схемы/обработчик.
- Проверить реальные исходящие вызовы `BOT_MESSAGE` и `INVITE_AGENT` против рабочего endpoint Jivo.
- Довести OpenAI routing: отделить intent detection от генерации ответа и добавить явные guardrails для сложных консультаций.
- Проверить живой Telegram demo на сервере и подготовить ссылку/инструкцию для показа заказчику.
- Подготовить тестовый прогон с заказчиком через `@testdemoNN_bot`.

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
