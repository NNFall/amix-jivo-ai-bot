# Kaigo Sol Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Переключить AMIX на Kaigo `gpt-5.6-sol` low с безопасным текстовым протоколом двух существующих функций.

**Architecture:** Новый provider-адаптер в `OpenAIService` сериализует полную историю и tool schemas в Kaigo text request, затем преобразует строгий JSON-ответ в текущий `LLMTurnResult`. Вся бизнес-логика функций остаётся в `AssistantService` без новых rule-based сценариев.

**Tech Stack:** Python, httpx, FastAPI, SQLAlchemy, pytest, Kaigo Codex Text API.

---

### Task 1: Конфигурация и протокол

**Files:** `settings.py`, `.env.example`, `llm/openai_client.py`, `tests/test_llm_client.py`

- [ ] Добавить failing-тесты конфигурации, полного payload и assistant/tool envelopes.
- [ ] Убедиться, что тесты падают до реализации.
- [ ] Реализовать Kaigo provider, сериализацию истории, schema appendix, parser и стандартный usage.
- [ ] Добавить тесты неизвестной функции, невалидного формата и retry.
- [ ] Запустить `python -m pytest tests/test_llm_client.py -q`.

### Task 2: Сквозные сценарии

**Files:** `tests/test_model_driven_assistant.py`, `scripts/run_history_order_eval.py`

- [ ] Проверить, что текущий `AssistantService` выполняет преобразованные `ToolCall` без отдельной бизнес-ветки.
- [ ] Прогнать существующие модельные и order-flow тесты.
- [ ] На VPS временно запустить live evaluation через Sol low без изменения production `.env`.
- [ ] Исправлять только обобщённый prompt/protocol, если реальный ответ нарушает сценарий.

### Task 3: Деплой и проверка

**Files:** `PLAN.md`, `OPERATIONS.md`, server `/root/amix/.env`

- [ ] Запустить полный `python -m pytest -q`, compileall, secret scan и `git diff --check`.
- [ ] Закоммитить и отправить изменения в текущую ветку.
- [ ] Обновить `/root/amix`, задать Kaigo secret/config в `.env`, сохранить Gemini-поля для отката.
- [ ] Перезапустить сервисы и проверить public health, journal и smoke-сценарии функций.
- [ ] Обновить `PLAN.md` и `OPERATIONS.md` фактическими результатами.
