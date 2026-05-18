# Live-отчёт по диалогам AMIX-бота

Дата прогона: `2026-05-18T11:04:43.468642+00:00`

LLM provider: `kie`

Model: `/gpt-5-2/v1/chat/completions`

LLM enabled: `True`

Важно: это live-прогон через реальную модель, поэтому ответы могут немного отличаться между запусками.

## Итог

- Сценариев: `31`.
- Ответов без style flags: `30`.
- Ответов без content flags: `29`.
- Ответов на ручную проверку: `3`.

## L-001 — Приветствие

Клиент: добрый день

Что хотели проверить: Живой короткий ответ менеджера без поиска товара.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Добрый день! Подскажите, что нужно посмотреть?

## L-002 — Адрес

Клиент: Где вы находитесь?

Что хотели проверить: Адрес AMIX без поиска товара.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Добрый день! Подскажите, что нужно посмотреть?

## L-003 — Контакты

Клиент: Как с вами связаться?

Что хотели проверить: Телефон/email AMIX без поиска товара.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `ok`

Ответ модели:
Вы можете позвонить по телефону +7 (812) 372-66-07 или написать на email market@amix.spb.ru.

## L-004 — Доставка

Клиент: Доставляете по России?

Что хотели проверить: Общий ответ про доставку без выдумывания стоимости.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=None`

Style flags: `нет`

Content flags: `delivery_answer_missing`

Оценка стиля: `manager_like`

Ответ модели:
Добрый день! Подскажите, что нужно посмотреть?

## L-005 — Возврат

Клиент: Можно сделать возврат в субботу?

Что хотели проверить: Ответить, что по субботам возврат не осуществляется.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `ok`

Ответ модели:
По субботам возврат товара не осуществляется. Если хотите, могу передать запрос менеджеру, чтобы уточнить другие возможные варианты возврата.

## L-006 — Точный товар

Клиент: сколько стоит 7843 silk brash

Что хотели проверить: Найти товар и ответить по цене/наличию.

Кандидаты поиска: `["7843SILKBRASH", "7843"]`

Prelookup:
```json
[
  {
    "query": "7843 silk brash",
    "display_query": "7843 silk brash",
    "raw_backend_query": "7843SILKBRASH",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "26139",
        "article": "7843 silk brash",
        "stock": "1.000",
        "retail_price": "13493.00"
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `ok`

Ответ модели:
Для 7843 silk brash розничная цена 13493 руб., корпоративная — 10500 руб. В наличии есть 1 штука.

## L-007 — Точный товар по коду

Клиент: проверьте код 26139

Что хотели проверить: Найти товар по коду и ответить по базе.

Кандидаты поиска: `["26139"]`

Prelookup:
```json
[
  {
    "query": "26139",
    "display_query": "26139",
    "raw_backend_query": "26139",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "26139",
        "article": "7843 silk brash",
        "stock": "1.000",
        "retail_price": "13493.00"
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=None`

Style flags: `dry_field_labels`

Content flags: `нет`

Оценка стиля: `needs_review`

Ответ модели:
Код 26139 найден — артикул 7843 silk brash.
В наличии 1 шт.
Розничная цена: 13493 руб., корпоративная цена: 10500 руб.

## L-008 — Дубли артикула

Клиент: а МП 28ск в наличии сколько

Что хотели проверить: При нескольких позициях сначала попросить уточнить код или цену.

Кандидаты поиска: `["28СК", "МП28СК"]`

Prelookup:
```json
[
  {
    "query": "МП 28ск",
    "display_query": "МП 28ск",
    "raw_backend_query": "МП28СК",
    "status": "multiple_exact",
    "exact_matches_count": 3,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "26167",
        "article": "МП 28ск",
        "stock": "124.000",
        "retail_price": "118.00"
      },
      {
        "code": "26168",
        "article": "МП 28ск",
        "stock": "292.000",
        "retail_price": "132.00"
      },
      {
        "code": "26169",
        "article": "МП 28ск",
        "stock": "237.000",
        "retail_price": "198.00"
      }
    ]
  }
]
```

Backend payload: `status=multiple_exact`, `exact=3`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Уточнить нужно: по артикулу МП 28ск у нас несколько вариантов. Можно, чтобы я посмотрел наличие конкретно по коду, цене в карточке, ссылке или фото?

## L-009 — Уточнение дубля

Клиент: код 26168

Что хотели проверить: Найти конкретный код и ответить по нему.

Кандидаты поиска: `["26168"]`

Prelookup:
```json
[
  {
    "query": "26168",
    "display_query": "26168",
    "raw_backend_query": "26168",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "26168",
        "article": "МП 28ск",
        "stock": "292.000",
        "retail_price": "132.00"
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
По коду 26168 нашёл артикул МП 28ск. Сейчас в наличии 292 шт. Розничная цена 132 руб. Корпоративная цена 98 руб.

## L-010 — Точное наличие

Клиент: 1108035 есть в наличии?

Что хотели проверить: Найти товар и ответить по остатку без цены, потому что клиент спросил только наличие.

Кандидаты поиска: `["1108035"]`

Prelookup:
```json
[
  {
    "query": "1108035",
    "display_query": "1108035",
    "raw_backend_query": "1108035",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 4,
    "exact_preview": [
      {
        "code": "26141",
        "article": "1108035",
        "stock": "2.000",
        "retail_price": "50820.00"
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `ok`

Ответ модели:
Да, комплект с артикулом 1108035 в наличии — осталось 2 штуки.

## L-011 — Неточный ввод

Клиент: а p am02 b s есть?

Что хотели проверить: Не выдумывать; найти или попросить уточнение.

Кандидаты поиска: `["PAM02BS", "AM02BS", "AM02"]`

Prelookup:
```json
[
  {
    "query": "p am02 b s",
    "display_query": "p am02 b s",
    "raw_backend_query": "PAM02BS",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "22608",
        "article": "P-AM02/B-S",
        "stock": "1.000",
        "retail_price": null
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Да, нашёл P-AM02/B-S. Сейчас в наличии 1 шт. Цена в текущих данных не указана.
## L-012 — Не найдено

Клиент: Есть XYZ-999?

Что хотели проверить: Не выдумывать товар, попросить проверить артикул/код.

Кандидаты поиска: `["XYZ999"]`

Prelookup:
```json
[
  {
    "query": "XYZ-999",
    "display_query": "XYZ-999",
    "raw_backend_query": "XYZ999",
    "status": "not_found",
    "exact_matches_count": 0,
    "similar_matches_count": 0,
    "exact_preview": []
  }
]
```

Backend payload: `status=not_found`, `exact=0`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Я посмотрел по базе — по коду XYZ-999 ничего не нашёл. Передаю вопрос менеджеру, он подключится к диалогу и уточнит наличие.

## L-013 — Цена без артикула

Клиент: Сколько стоит направляющая?

Что хотели проверить: Попросить артикул или код.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `ok`

Ответ модели:
Чтобы точно назвать цену, нужно уточнить, о какой направляющей идет речь. У нас есть разные типы и длины. Можете прислать артикул, код с сайта или фото товара?

## L-014 — Сравнение

Клиент: Чем 14.023л. отличается от 14.023пр.?

Что хотели проверить: Не выдумывать отличия, при необходимости передать менеджеру.

Кандидаты поиска: `["14023Л", "14023ПР"]`

Prelookup:
```json
[
  {
    "query": "14.023л.",
    "display_query": "14.023л.",
    "raw_backend_query": "14023Л",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "769",
        "article": "14.023л.",
        "stock": "253.000",
        "retail_price": "473.00"
      }
    ]
  },
  {
    "query": "14.023пр.",
    "display_query": "14.023пр.",
    "raw_backend_query": "14023ПР",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "770",
        "article": "14.023пр.",
        "stock": "220.000",
        "retail_price": "473.00"
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=2`, `similar=0`, `handoff=complex_technical_question`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `ok`

Ответ модели:
В нашем каталоге это два отдельных артикула: 14.023л. и 14.023пр. По техническим деталям различие не указано в текущих данных. Чтобы точно понять отличие, лучше передам ваш вопрос менеджеру, он уточнит все нюансы.

## L-015 — Подбор

Клиент: Мне нужны направляющие для шкафа, что посоветуете?

Что хотели проверить: Не советовать без параметров, передать менеджеру.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=complex_technical_question`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Для точного подбора нужны параметры: размеры, нагрузка и тип установки. Передаю вопрос менеджеру. Он подключится к диалогу и поможет подобрать вариант.

## L-016 — Менеджер

Клиент: Позовите менеджера

Что хотели проверить: Передать менеджеру.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=client_requested_manager`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам.

## L-017 — Заказ

Клиент: Хочу заказать 10 штук 7843 silk brash

Что хотели проверить: Проверить наличие и передать менеджеру для оформления.

Кандидаты поиска: `["7843SILKBRASH", "7843"]`

Prelookup:
```json
[
  {
    "query": "7843 silk brash",
    "display_query": "7843 silk brash",
    "raw_backend_query": "7843SILKBRASH",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "26139",
        "article": "7843 silk brash",
        "stock": "1.000",
        "retail_price": "13493.00"
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=requested_quantity_exceeds_stock`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Да, нашёл 7843 silk brash. Сейчас в наличии 1 шт. Розничная цена 13493 руб. Корпоративная цена 10500 руб. Передаю вопрос менеджеру. Он подключится к диалогу и уточнит возможность заказа или замены.

## L-018 — Недостаточный остаток

Клиент: Нужно 5 штук P-AM02/B-S

Что хотели проверить: Если остатка не хватает, сказать и передать менеджеру.

Кандидаты поиска: `["PAM02BS"]`

Prelookup:
```json
[
  {
    "query": "P-AM02/B-S",
    "display_query": "P-AM02/B-S",
    "raw_backend_query": "PAM02BS",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "22608",
        "article": "P-AM02/B-S",
        "stock": "1.000",
        "retail_price": null
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=requested_quantity_exceeds_stock`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Да, нашёл P-AM02/B-S. Сейчас в наличии 1 шт. Цена в текущих данных не указана. Передаю вопрос менеджеру. Он подключится к диалогу и уточнит возможность заказа или замены.

## L-019 — Несколько товаров

Клиент: Проверьте 14.023пр. и 14.025пр.

Что хотели проверить: Ответить по каждому найденному товару.

Кандидаты поиска: `["14023ПР", "14025ПР"]`

Prelookup:
```json
[
  {
    "query": "14.023пр.",
    "display_query": "14.023пр.",
    "raw_backend_query": "14023ПР",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "770",
        "article": "14.023пр.",
        "stock": "220.000",
        "retail_price": "473.00"
      }
    ]
  },
  {
    "query": "14.025пр.",
    "display_query": "14.025пр.",
    "raw_backend_query": "14025ПР",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "1364",
        "article": "14.025пр.",
        "stock": "7.000",
        "retail_price": "238.00"
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=2`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Проверил, оба артикула есть в наличии.
14.023пр. — 220 штук, корпоративная цена 335,24 руб.
14.025пр. — 7 штук, корпоративная цена 165,98 руб.

## L-020 — Смешанный поиск

Клиент: Проверьте 14.023пр. и XYZ-999

Что хотели проверить: Один товар найти, второй не выдумывать.

Кандидаты поиска: `["14023ПР", "XYZ999"]`

Prelookup:
```json
[
  {
    "query": "14.023пр.",
    "display_query": "14.023пр.",
    "raw_backend_query": "14023ПР",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "770",
        "article": "14.023пр.",
        "stock": "220.000",
        "retail_price": "473.00"
      }
    ]
  },
  {
    "query": "XYZ-999",
    "display_query": "XYZ-999",
    "raw_backend_query": "XYZ999",
    "status": "not_found",
    "exact_matches_count": 0,
    "similar_matches_count": 0,
    "exact_preview": []
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `ok`

Ответ модели:
По 14.023пр. товар есть: 220 штук в наличии, розница 473 руб., корпоративная цена 335,24 руб.
А вот XYZ-999 в нашем каталоге не найден. Хотите, чтобы я передал вопрос менеджеру для уточнения?

## L-021 — Цена и отсутствие цены

Клиент: Сколько стоят 14.023пр. и P-AM02/B-S?

Что хотели проверить: Не выдумывать цену, если её нет в базе.

Кандидаты поиска: `["14023ПР", "PAM02BS"]`

Prelookup:
```json
[
  {
    "query": "14.023пр.",
    "display_query": "14.023пр.",
    "raw_backend_query": "14023ПР",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "770",
        "article": "14.023пр.",
        "stock": "220.000",
        "retail_price": "473.00"
      }
    ]
  },
  {
    "query": "P-AM02/B-S",
    "display_query": "P-AM02/B-S",
    "raw_backend_query": "PAM02BS",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "22608",
        "article": "P-AM02/B-S",
        "stock": "1.000",
        "retail_price": null
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=2`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Проверил. По 14.023пр. остаток 220 шт, розничная цена 473 руб. По P-AM02/B-S остаток 1 шт, цена в текущих данных не указана.

## L-022 — Недовольный клиент

Клиент: Вы вообще можете нормально ответить? Дайте человека

Что хотели проверить: Не спорить, передать менеджеру.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=client_requested_manager`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам.

## L-023 — Дубль без лишней таблицы

Клиент: есть мп 28ск

Что хотели проверить: Несколько позиций, не выдавать таблицу, попросить код/цену/ссылку.

Кандидаты поиска: `["28СК", "МП28СК"]`

Prelookup:
```json
[
  {
    "query": "мп 28ск",
    "display_query": "мп 28ск",
    "raw_backend_query": "МП28СК",
    "status": "multiple_exact",
    "exact_matches_count": 3,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "26167",
        "article": "МП 28ск",
        "stock": "124.000",
        "retail_price": "118.00"
      },
      {
        "code": "26168",
        "article": "МП 28ск",
        "stock": "292.000",
        "retail_price": "132.00"
      },
      {
        "code": "26169",
        "article": "МП 28ск",
        "stock": "237.000",
        "retail_price": "198.00"
      }
    ]
  }
]
```

Backend payload: `status=multiple_exact`, `exact=3`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `ok`

Ответ модели:
По артикулу МП 28ск у нас есть несколько вариантов. Чтобы точно сказать, какой вам нужен, пришлите код с сайта, цену из карточки, ссылку или фото товара.

## L-024 — Уточнение дубля по цене

Клиент: цена 132

История перед вопросом: `["есть мп 28ск"]`

Что хотели проверить: После уточнения цены выбрать подходящую позицию МП 28ск и сказать остаток.

Кандидаты поиска: `["132"]`

Prelookup:
```json
[
  {
    "query": "132",
    "display_query": "132",
    "raw_backend_query": "132",
    "status": "similar_found",
    "exact_matches_count": 0,
    "similar_matches_count": 20,
    "exact_preview": []
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `price_refinement_not_resolved`

Оценка стиля: `manager_like`

Ответ модели:
Да, нашёл МП 28ск. Сейчас в наличии 292 шт. Розничная цена 132 руб. Корпоративная цена 98 руб.

## L-025 — Артикул со ссылкой

Клиент: вот ссылка на товар, артикул МП 28ск

Что хотели проверить: Если ссылку не парсим, попросить код или цену с карточки, не выдумывать.

Кандидаты поиска: `["28СК", "МП28СК"]`

Prelookup:
```json
[
  {
    "query": "МП 28ск",
    "display_query": "МП 28ск",
    "raw_backend_query": "МП28СК",
    "status": "multiple_exact",
    "exact_matches_count": 3,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "26167",
        "article": "МП 28ск",
        "stock": "124.000",
        "retail_price": "118.00"
      },
      {
        "code": "26168",
        "article": "МП 28ск",
        "stock": "292.000",
        "retail_price": "132.00"
      },
      {
        "code": "26169",
        "article": "МП 28ск",
        "stock": "237.000",
        "retail_price": "198.00"
      }
    ]
  }
]
```

Backend payload: `status=multiple_exact`, `exact=3`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
По МП 28ск нашёл несколько позиций. Они отличаются кодом и ценой, поэтому чтобы не ошибиться, уточните, пожалуйста, код товара с сайта или цену, которую видите. После этого скажу точный остаток.

## L-026 — Сравнение из истории

Клиент: а чем они отличаются?

История перед вопросом: `["Проверьте 14.023л. и 14.023пр."]`

Что хотели проверить: Использовать историю, не выдумывать отличия, передать менеджеру.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=exact_found`, `exact=2`, `similar=0`, `handoff=complex_technical_question`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Проверил. По 14.023л. остаток 253 шт, розничная цена 473 руб. По 14.023пр. остаток 220 шт, розничная цена 473 руб. По РУБ14023ПР в текущей базе ничего не нашёл. Проверьте, пожалуйста, артикул или код. По текущим данным могу сравнить только данные из базы: код, артикул, цену, остаток, единицу измерения, вес и объём. Технического описания отличий в базе нет. Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам.

## L-027 — Менеджер после уточнения

Клиент: ок, давайте менеджера

История перед вопросом: `["есть мп 28ск"]`

Что хотели проверить: Сразу handoff без повторных уточнений.

Кандидаты поиска: `[]`

Prelookup:
```json
[]
```

Backend payload: `status=None`, `exact=None`, `similar=None`, `handoff=client_requested_manager`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам.

## L-028 — Заказ при нехватке

Клиент: Хочу заказать 5 штук P-AM02/B-S

Что хотели проверить: Не писать, что заказ можно оформить; передать менеджеру для уточнения или замены.

Кандидаты поиска: `["PAM02BS"]`

Prelookup:
```json
[
  {
    "query": "P-AM02/B-S",
    "display_query": "P-AM02/B-S",
    "raw_backend_query": "PAM02BS",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "22608",
        "article": "P-AM02/B-S",
        "stock": "1.000",
        "retail_price": null
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=requested_quantity_exceeds_stock`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
По текущему запасу есть только 1 штука P-AM02/B-S. Передаю ваш заказ менеджеру, он подключится к диалогу для уточнения. Передаю вопрос менеджеру. Он подключится к диалогу и уточнит возможность заказа или замены.

## L-029 — Похожий raw-запрос

Клиент: 14.023

Что хотели проверить: Показать клиенту исходный запрос 14.023, а не normalized 14023.

Кандидаты поиска: `["14023"]`

Prelookup:
```json
[
  {
    "query": "14.023",
    "display_query": "14.023",
    "raw_backend_query": "14023",
    "status": "similar_found",
    "exact_matches_count": 0,
    "similar_matches_count": 2,
    "exact_preview": []
  }
]
```

Backend payload: `status=similar_found`, `exact=0`, `similar=2`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Точного совпадения по 14.023 не нашёл. Есть похожие варианты: 14.023л. — код 769; 14.023пр. — код 770. Если это не то, пришлите, пожалуйста, код товара с сайта.

## L-030 — Корпоративная цена

Клиент: Какая корпоративная цена у 14.025пр.?

Что хотели проверить: Учитывать настройку показа корпоративной цены и не выдумывать условия.

Кандидаты поиска: `["14025ПР"]`

Prelookup:
```json
[
  {
    "query": "14.025пр.",
    "display_query": "14.025пр.",
    "raw_backend_query": "14025ПР",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "1364",
        "article": "14.025пр.",
        "stock": "7.000",
        "retail_price": "238.00"
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Да, нашёл 14.025пр. Сейчас в наличии 7 шт. Розничная цена 238 руб. Корпоративная цена 165,98 руб.

## L-031 — Цена отсутствует без слова выгрузка

Клиент: Сколько стоит P-AM02/B-S?

Что хотели проверить: Если цены нет, сказать живо без внутреннего слова 'выгрузка'.

Кандидаты поиска: `["PAM02BS"]`

Prelookup:
```json
[
  {
    "query": "P-AM02/B-S",
    "display_query": "P-AM02/B-S",
    "raw_backend_query": "PAM02BS",
    "status": "exact_found",
    "exact_matches_count": 1,
    "similar_matches_count": 0,
    "exact_preview": [
      {
        "code": "22608",
        "article": "P-AM02/B-S",
        "stock": "1.000",
        "retail_price": null
      }
    ]
  }
]
```

Backend payload: `status=exact_found`, `exact=1`, `similar=0`, `handoff=None`

Style flags: `нет`

Content flags: `нет`

Оценка стиля: `manager_like`

Ответ модели:
Да, нашёл P-AM02/B-S. Сейчас в наличии 1 шт. Цена в текущих данных не указана.
