# Kaigo Model Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Проверить production Gemini и получить воспроизводимое сравнение текстовых ответов Gemini, Luna low и Sol low.

**Architecture:** Одноразовый синтетический benchmark запускается на VPS поверх production checkout, но не меняет его конфигурацию. Результаты возвращаются как JSON, локально преобразуются в читаемый Markdown и сохраняются в `outputs/`.

**Tech Stack:** Python, httpx, существующие `Settings`/`OpenAIService`, Kaigo Codex Text API, SSH.

---

### Task 1: Production availability

**Files:**
- Modify: `PLAN.md`
- Read: `settings.py`, `llm/openai_client.py`, `data/logs/llm_audit_recent.json`

- [ ] Проверить `amix-api.service`, `amix-telegram-demo.service` и оба `/health`.
- [ ] Выполнить один реальный вызов через production `OpenAIService`.
- [ ] Посчитать недавние HTTP 429 и provider errors без вывода клиентских payload.

### Task 2: Synthetic text benchmark

**Files:**
- Create: `outputs/amix-kaigo-model-comparison-2026-08-15.json`
- Create: `outputs/amix-kaigo-model-comparison-2026-08-15.md`

- [ ] Передать Kaigo-токен временному серверному процессу через stdin.
- [ ] Последовательно выполнить четыре ситуации через Gemini, Luna low и Sol low.
- [ ] Для HTTP 429 Kaigo использовать ограниченный отложенный retry; остальные ошибки классифицировать по `error.code`.
- [ ] Сохранить только синтетические запросы, ответы, usage, latency и request id.

### Task 3: Assessment and audit trail

**Files:**
- Modify: `PLAN.md`
- Modify: `OPERATIONS.md`

- [ ] Проверить обязательные и запрещённые фрагменты каждого ответа.
- [ ] Выполнить ручную оценку естественности и пригодности.
- [ ] Зафиксировать различие между text-only качеством и поддержкой production functions.
- [ ] Проверить, что токен отсутствует в Git diff и сохранённых отчётах.
- [ ] Запустить `git diff --check` и сверить итоговые файлы.
