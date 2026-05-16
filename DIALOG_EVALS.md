# Dialog Evals

Этот файл хранит историю тестовых прогонов диалогов.

Формат записи:
- сценарий;
- провайдер/модель;
- fingerprint промптов;
- по каждому сообщению: текст клиента, план LLM, lookup-вызов и итоговый ответ бота.

Для добавления новой записи:

```bash
python scripts/run_dialog_eval.py --scenario smoke --output DIALOG_EVALS.md
```

## Run 2026-05-16T09:25:10.576277+00:00

- Scenario: `smoke`
- Provider: `openai`
- Model: `gpt-5-mini`
- Prompt fingerprint: `3a430f8001fc`

### Turn 1
- Client: добрый день
- Planner mode: `disabled`
- Planner raw: `null`
- Lookup call: `not-called`
- Bot: Я могу проверить по базе артикул, код, свободный остаток, цену, единицу измерения, вес и объём. Если пришлёте артикул или код, сразу посмотрю данные. Если нужен подбор, аналог или техническая консультация, лучше передать вопрос менеджеру.

### Turn 2
- Client: я хочу цену примерную хоть узнать у 7843 silk brash
- Planner mode: `disabled`
- Planner raw: `null`
- Lookup call: `not-called`
- Bot: Точный артикул 7843 не найден. Нашёл похожие позиции: 7843 satin, 7843 silk brash, 7843 silk brash. Если нужен точный подбор, лучше передать вопрос менеджеру.

### Turn 3
- Client: а где находится ваш магазин и какой график работы?
- Planner mode: `disabled`
- Planner raw: `null`
- Lookup call: `not-called`
- Bot: Я могу проверить по базе артикул, код, свободный остаток, цену, единицу измерения, вес и объём. Если пришлёте артикул или код, сразу посмотрю данные. Если нужен подбор, аналог или техническая консультация, лучше передать вопрос менеджеру.


## Run 2026-05-16T10:16:22.533042+00:00

- Scenario: `smoke`
- Provider: `openai`
- Model: `gpt-5-mini`
- Prompt fingerprint: `6075917960c1`

### Turn 1
- Client: добрый день
- Planner mode: `disabled`
- Planner raw: `null`
- Lookup call: `not-called`
- Bot: Я могу проверить по базе артикул, код, свободный остаток, цену, единицу измерения, вес и объём. Если пришлёте артикул или код, сразу посмотрю данные. Если нужен подбор, аналог или техническая консультация, лучше передать вопрос менеджеру.

### Turn 2
- Client: я хочу цену примерную хоть узнать у 7843 silk brash
- Planner mode: `disabled`
- Planner raw: `null`
- Lookup call: `not-called`
- Bot: Точный артикул 7843 не найден. Нашёл похожие позиции: 7843 satin, 7843 silk brash, 7843 silk brash. Если нужен точный подбор, лучше передать вопрос менеджеру.

### Turn 3
- Client: а где находится ваш магазин и какой график работы?
- Planner mode: `disabled`
- Planner raw: `null`
- Lookup call: `not-called`
- Bot: Я могу проверить по базе артикул, код, свободный остаток, цену, единицу измерения, вес и объём. Если пришлёте артикул или код, сразу посмотрю данные. Если нужен подбор, аналог или техническая консультация, лучше передать вопрос менеджеру.


## Run 2026-05-16T10:18:00.773761+00:00

- Scenario: `products_only`
- Provider: `openai`
- Model: `gpt-5-mini`
- Prompt fingerprint: `6075917960c1`

### Turn 1
- Client: какая цена у 1108035
- Planner mode: `disabled`
- Planner raw: `null`
- Lookup call: `not-called`
- Bot: Артикул 1108035 найден. Свободный остаток: 2 компл. Розничная цена: 5082 руб. Корпоративная цена: 24283 руб.

### Turn 2
- Client: а наличие у оз/700
- Planner mode: `disabled`
- Planner raw: `null`
- Lookup call: `not-called`
- Bot: Артикул ОЗ/ 700 найден. Свободный остаток: 79 шт. Розничная цена: 305 руб. Корпоративная цена: 224 руб. Вес: 2.160.

### Turn 3
- Client: мп 28ск
- Planner mode: `disabled`
- Planner raw: `null`
- Lookup call: `not-called`
- Bot: Артикул МП 28ск найден. Свободный остаток: 237 шт. Розничная цена: 198 руб. Корпоративная цена: 156.8 руб. Вес: 0.115.

