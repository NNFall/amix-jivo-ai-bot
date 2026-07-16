# Реализация заказа по полной истории диалога

> **Для agentic workers:** ОБЯЗАТЕЛЬНЫЙ SUB-SKILL: выполнять задачи через `superpowers:subagent-driven-development` с отдельной проверкой соответствия спецификации и качества кода. Шаги отслеживаются чекбоксами `- [ ]`.

**Цель:** удалить параллельный черновик заказа и оставить Gemini полную хронологическую историю, `search_products` и `handoff_to_manager`.

**Архитектура:** SQLite хранит единственную память разговора. Gemini сама ведёт заказ по всем сообщениям, а backend отвечает только за хронологию, товарные факты, защиту остатков, актуальность turn и реальные действия Jivo.

**Стек:** Python 3.12, FastAPI, SQLAlchemy, SQLite, pytest, Google AI Studio OpenAI-compatible API, Jivo Bot API.

---

### Задача 1: Полная хронологическая история

**Файлы:**
- Изменить: `database/repositories.py`
- Изменить: `core/dialog_service.py`
- Изменить: `core/assistant_service.py`
- Изменить: `settings.py`
- Тест: `tests/test_dialog_service.py`

- [ ] **Шаг 1: написать падающий тест полной истории**

Добавить тест, который сохраняет больше 20 сообщений вместе с вызовом и результатом функции и проверяет, что первое сообщение, последнее сообщение и function history присутствуют в `get_llm_messages()`.

```python
def test_llm_history_contains_entire_chronological_chat(isolated_app_env):
    # Сохранить 24 видимые реплики и пару assistant_tool_call/tool.
    messages = DialogService().get_llm_messages(session, "chat:full-history")
    assert messages[0]["content"] == "сообщение 1"
    assert messages[-1]["content"] == "сообщение 24"
    assert any(message.get("tool_calls") for message in messages)
```

- [ ] **Шаг 2: убедиться в правильном RED**

Выполнить:

```powershell
python -m pytest tests/test_dialog_service.py::test_llm_history_contains_entire_chronological_chat -q
```

Ожидание: FAIL, потому что `list_recent_messages(..., limit=20)` обрезает начало.

- [ ] **Шаг 3: добавить отдельное чтение всей истории**

В `database/repositories.py` добавить функцию без лимита:

```python
def list_messages(session, external_chat_id: str) -> list[Message]:
    chat = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if chat is None:
        return []
    return list(
        session.scalars(
            select(Message)
            .where(Message.chat_id == chat.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        ).all()
    )
```

Перевести `DialogService.get_transcript()` и `get_llm_messages()` на `list_messages`. Удалить зависимость LLM-контекста от `history_limit`; локальные эвристики, которым нужен небольшой хвост, могут продолжить использовать `list_recent_messages` явно.

- [ ] **Шаг 4: проверить GREEN**

```powershell
python -m pytest tests/test_dialog_service.py -q
```

Ожидание: все тесты файла проходят, роли и хронология сохранены.

- [ ] **Шаг 5: commit**

```powershell
git add database/repositories.py core/dialog_service.py core/assistant_service.py settings.py tests/test_dialog_service.py
git commit -m "Send complete dialog history to Gemini"
```

### Задача 2: Удаление runtime-черновика заказа

**Файлы:**
- Удалить: `core/order_intake_service.py`
- Изменить: `core/assistant_service.py`
- Изменить: `database/repositories.py`
- Изменить: `llm/tool_schemas.py`
- Изменить: `llm/prompts.py`
- Изменить: `tests/test_assistant_service.py`
- Изменить: `tests/test_llm_client.py`
- Удалить: `tests/test_order_intake_service.py`

- [ ] **Шаг 1: написать падающие тесты границы инструментов и старых строк**

```python
def test_only_product_search_and_handoff_tools_are_exposed():
    assert [tool["function"]["name"] for tool in OPENAI_TOOLS] == [
        "search_products",
        "handoff_to_manager",
    ]

def test_legacy_order_draft_does_not_force_order_tool(isolated_app_env):
    # Старая строка OrderDraft существует, но обычный вопрос об адресе обрабатывается как FAQ.
    reply = service.handle_message(session, "chat:legacy", "Где вы находитесь?")
    assert reply.handoff_reason is None
    assert "Якорная" in reply.text
```

- [ ] **Шаг 2: проверить RED**

```powershell
python -m pytest tests/test_llm_client.py::test_only_product_search_and_handoff_tools_are_exposed tests/test_assistant_service.py::test_legacy_order_draft_does_not_force_order_tool -q
```

Ожидание: FAIL из-за третьей функции и draft-based маршрутизации.

- [ ] **Шаг 3: удалить draft runtime**

Удалить схему `update_order_draft`, forced `order_tool_retry`, обработчик draft tool, draft context, draft-based handoff guard и все вызовы `OrderIntakeService`. Удалить сервис и его runtime repository-функции. Модель `OrderDraft` оставить на один релиз только для совместимости с существующей физической таблицей, но не читать и не изменять её в рабочем потоке.

- [ ] **Шаг 4: проверить отсутствие runtime-ссылок**

```powershell
rg -n "update_order_draft|OrderIntakeService|get_order_draft|upsert_order_draft" core llm
```

Ожидание: нет совпадений в runtime-коде.

- [ ] **Шаг 5: проверить GREEN**

```powershell
python -m pytest tests/test_llm_client.py tests/test_assistant_service.py -q
```

Ожидание: новая граница функций и обычная маршрутизация проходят.

- [ ] **Шаг 6: commit**

```powershell
git add core database llm tests
git commit -m "Remove order draft runtime flow"
```

### Задача 3: Компактный обобщённый промпт заказа

**Файлы:**
- Изменить: `llm/prompts.py`
- Изменить: `llm/tool_schemas.py`
- Тест: `tests/test_llm_client.py`
- Изменить: `docs/PROMPTS_AND_TOOLS_REFERENCE.md`
- Изменить: `README.md`

- [ ] **Шаг 1: написать тесты смысловых правил промпта**

```python
def test_order_prompt_is_history_driven_and_has_no_draft_contract():
    assert "полную историю" in SYSTEM_PROMPT.lower()
    assert "update_order_draft" not in SYSTEM_PROMPT
    assert "после явного подтверждения" in SYSTEM_PROMPT.lower()
    assert "один" in SYSTEM_PROMPT.lower() and "вопрос" in SYSTEM_PROMPT.lower()
```

- [ ] **Шаг 2: проверить RED**

```powershell
python -m pytest tests/test_llm_client.py::test_order_prompt_is_history_driven_and_has_no_draft_contract -q
```

Ожидание: FAIL на старых draft-инструкциях.

- [ ] **Шаг 3: заменить заказный раздел**

Использовать один общий блок без товарных и языковых частных случаев:

```text
Если клиент явно хочет оформить заказ, веди сбор по полной истории разговора.
Собери позиции и количество, желаемый срок, получение, оплату, имя и телефон; для оплаты по счёту также ИНН.
Учитывай уже сообщённые данные и последующие исправления. Не повторяй вопросы и за один ответ уточняй только следующий естественный пробел.
Когда данных достаточно, кратко перечисли актуальные договорённости и попроси подтверждение.
После исправления покажи новый итог. Передавай менеджеру по причине order_creation только после явного подтверждения последнего итога.
```

Удалить дублирующие draft-правила и узкие примеры из системного промпта. Обновить справочную документацию на две функции.

- [ ] **Шаг 4: проверить GREEN**

```powershell
python -m pytest tests/test_llm_client.py -q
```

- [ ] **Шаг 5: commit**

```powershell
git add llm/prompts.py llm/tool_schemas.py tests/test_llm_client.py docs/PROMPTS_AND_TOOLS_REFERENCE.md README.md
git commit -m "Simplify history-driven order prompt"
```

### Задача 4: Количество отдельно для каждого товара

**Файлы:**
- Изменить: `llm/tool_schemas.py`
- Изменить: `core/assistant_service.py`
- Тест: `tests/test_assistant_service.py`
- Тест: `tests/test_llm_client.py`

- [ ] **Шаг 1: написать граничный падающий тест**

```python
def test_multi_product_tool_uses_quantity_per_query(isolated_app_env):
    call = ToolCall(
        name="search_products",
        arguments={
            "queries": [
                {"query": "770", "requested_quantity": 2},
                {"query": "28834", "requested_quantity": 3},
            ],
            "intent": "order",
            "use_dialog_context": False,
        },
        call_id="search-order-items",
    )
    # Остаток второго товара равен 2.
    result = execute_search(call)
    assert result["results"][0]["requested_quantity_available"] is True
    assert result["results"][1]["requested_quantity_available"] is False
```

- [ ] **Шаг 2: проверить RED**

```powershell
python -m pytest tests/test_assistant_service.py::test_multi_product_tool_uses_quantity_per_query -q
```

Ожидание: FAIL, потому что текущая схема принимает строки и одно общее `requested_quantity`.

- [ ] **Шаг 3: изменить контракт `search_products`**

Сделать `queries` массивом объектов:

```python
"queries": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "requested_quantity": {"type": ["number", "null"]},
        },
        "required": ["query"],
    },
}
```

Нормализовать каждый элемент отдельно, искать исходное значение без перестановки и добавлять в результат `requested_quantity` и безопасное логическое `requested_quantity_available`. Не передавать модели точный остаток для stock-only/order availability.

- [ ] **Шаг 4: сохранить идентичность товара в ответе**

Для нескольких кодов итог функции должен сохранять `query`, `code`, `article` и собственный результат количества. Формирование ответа модели не должно терять исходный код.

- [ ] **Шаг 5: проверить GREEN и соседние stock-тесты**

```powershell
python -m pytest tests/test_assistant_service.py tests/test_llm_client.py -q
```

- [ ] **Шаг 6: commit**

```powershell
git add llm/tool_schemas.py core/assistant_service.py tests/test_assistant_service.py tests/test_llm_client.py
git commit -m "Check requested quantity per product"
```

### Задача 5: Правдивая передача в Jivo

**Файлы:**
- Изменить: `core/message_processor.py`
- Изменить: `jivo/client.py`
- Тест: `tests/test_message_processor.py`

- [ ] **Шаг 1: написать падающий тест ошибки invite**

```python
def test_failed_invite_does_not_send_handoff_promise(isolated_app_env):
    jivo_client.invite_agent.return_value = False
    processor.process(event)
    jivo_client.send_text_message.assert_not_called()
```

- [ ] **Шаг 2: проверить RED**

```powershell
python -m pytest tests/test_message_processor.py::test_failed_invite_does_not_send_handoff_promise -q
```

Ожидание: FAIL, потому что возвращаемое `False` сейчас игнорируется.

- [ ] **Шаг 3: проверить результат `INVITE_AGENT`**

Если `invite_agent()` вернул `False`, записать ошибку обработки и не отправлять текст об успешной передаче. Успешный путь сохраняет порядок `INVITE_AGENT` перед `BOT_MESSAGE`.

- [ ] **Шаг 4: проверить GREEN и lifecycle**

```powershell
python -m pytest tests/test_message_processor.py tests/test_jivo_events.py -q
```

- [ ] **Шаг 5: commit**

```powershell
git add core/message_processor.py jivo/client.py tests/test_message_processor.py
git commit -m "Prevent false Jivo handoff promises"
```

### Задача 6: Версионированный многоходовый live-eval

**Файлы:**
- Создать: `scripts/run_history_order_eval.py`
- Создать: `tests/test_history_order_eval.py`
- Изменить: `tests/dialog_eval_cases.json`

- [ ] **Шаг 1: написать тесты формата evidence и assertions**

```python
def test_history_order_eval_records_manifest_and_turn_assertions(tmp_path):
    report = build_report(fake_scenario_results())
    assert report["manifest"]["git_sha"]
    assert report["manifest"]["prompt_sha256"]
    assert all(turn["assertions"] for turn in report["scenarios"][0]["turns"])
```

- [ ] **Шаг 2: проверить RED**

```powershell
python -m pytest tests/test_history_order_eval.py -q
```

- [ ] **Шаг 3: реализовать runner**

Runner принимает изолированный database URL, модель и output-путь, сохраняет git SHA, hash промпта/схем/сценариев/каталога, полные turn events, функции, latency, usage и автоматические verdicts. Он не отправляет сообщения в реальные Jivo-чаты.

- [ ] **Шаг 4: добавить набор разных диалогов**

Зафиксировать сценарии нескольких товаров, свободного описания, исправлений, разных оплат, неоднозначности, отмены, быстрых сообщений, подтверждения и ошибок. Assertions проверяют две функции, отсутствие точного остатка, правильные количества, отсутствие раннего handoff и итоговую передачу после подтверждения.

- [ ] **Шаг 5: проверить GREEN**

```powershell
python -m pytest tests/test_history_order_eval.py -q
```

- [ ] **Шаг 6: commit**

```powershell
git add scripts/run_history_order_eval.py tests/test_history_order_eval.py tests/dialog_eval_cases.json
git commit -m "Add reproducible history order evaluation"
```

### Задача 7: Полная проверка, реальные диалоги и независимое ревью

**Файлы:**
- Изменить: `PLAN.md`
- Изменить: `OPERATIONS.md`
- Локально создать: `data/logs/history_order_eval_<timestamp>.json`
- Локально создать: `data/logs/history_order_eval_<timestamp>.md`

- [ ] **Шаг 1: выполнить локальную проверку**

```powershell
python -m pytest -q
python -m scripts.run_dialog_regression_eval --output DIALOG_EVALS.md
python -m compileall api core database jivo llm products scripts -q
git diff --check
```

Ожидание: все pytest проходят, regression eval не содержит FAIL, compileall и diff check завершаются с кодом 0.

- [ ] **Шаг 2: развернуть кандидат на сервере для изолированного eval**

Создать копию текущего каталога в отдельной SQLite-базе, не менять статистику production и не отправлять `INVITE_AGENT` реальным клиентам.

- [ ] **Шаг 3: запустить реальные обращения Gemini**

Каждый сценарий запустить не менее трёх раз. После первого полного запуска менять промпт только по повторяющимся категориям ошибок и после каждого изменения повторять весь набор.

- [ ] **Шаг 4: независимые проверки**

Отдельные subagents проверяют:

- соответствие кода этой спецификации;
- обобщённость и естественность промпта;
- обезличенные диалоги без знания версии промпта;
- корректность runner, assertions, токенов и latency.

Все критические и важные замечания исправляются через новый RED/GREEN цикл, затем проверки повторяются.

- [ ] **Шаг 5: обновить документацию и commit**

```powershell
git add PLAN.md OPERATIONS.md DIALOG_EVALS.md
git commit -m "Verify history-driven order flow"
git push
```

- [ ] **Шаг 6: production deployment после успешного evidence**

Обновить VPS только после отсутствия safety-critical failures. На сервере повторить полный pytest, проверить active services, `/health`, Jivo test channel и отсутствие новых warning/error в журнале.
