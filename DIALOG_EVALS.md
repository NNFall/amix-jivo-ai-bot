# History-driven order evaluation

- Verdict: **PASS**
- Provider/model: `fake` / `fake-history-order-eval-v1`
- Repetitions: 1
- Scenarios: 9/9 passed
- Turns: 41/41 passed

## Заказ из истории с исправлениями и подтверждением (run 1)

Verdict: **PASS**

### Turn 1

**Client:** Хочу заказать 2 штуки 14.023л. и 5 штук 14.023пр.

**Bot:** Нашёл обе позиции: 2 штуки 14.023л. и 5 штук 14.023пр. Как вам удобнее получить заказ?

Functions: `search_products`. Latency: 33 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 2

**Client:** Доставкой по Санкт-Петербургу.

**Bot:** Записал доставку по Санкт-Петербургу. Подскажите желаемый срок получения.

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 3

**Client:** Нет, исправьте: правых нужно 7, и лучше самовывоз.

**Bot:** Исправил: 2 штуки 14.023л., 7 штук 14.023пр., получение самовывозом. Как планируете оплатить?

Functions: `search_products`. Latency: 24 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 4

**Client:** Оплата по счёту.

**Bot:** Для выставления счёта укажите, пожалуйста, ИНН организации или ИП.

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 5

**Client:** ИНН 7812345678.

**Bot:** ИНН записал. Подскажите имя и телефон для связи.

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 6

**Client:** Иван, +7 900 123-45-67, заберу в пятницу.

**Bot:** Итог: 2 шт. 14.023л., 7 шт. 14.023пр., самовывоз в пятницу, оплата по счёту, ИНН 7812345678, Иван, +7 900 123-45-67. Всё верно?

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 7

**Client:** Да, всё верно, подтверждаю.

**Bot:** Передаю подтверждённые данные заказа менеджеру.

Functions: `handoff_to_manager`. Latency: 18 ms. Tokens: 110. Cost: 0.0100 RUB.

Verdict: **PASS**

## Поиск товара по свободному описанию (run 1)

Verdict: **PASS**

### Turn 1

**Client:** Нужна белая мебельная ручка 128 мм, две штуки.

**Bot:** Нашёл белую ручку 128 мм. Две штуки доступны. Как вам удобнее получить заказ?

Functions: `search_products`. Latency: 23 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 2

**Client:** Нужна доставка в Тверь на следующей неделе.

**Bot:** Записал доставку в Тверь на следующей неделе. Как планируете оплатить?

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 3

**Client:** Оплачу наличными.

**Bot:** Хорошо. Подскажите имя и телефон для связи.

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 4

**Client:** Анна, +7 911 222-33-44.

**Bot:** Итог: 2 белые ручки 128 мм, доставка в Тверь на следующей неделе, оплата наличными, Анна, +7 911 222-33-44. Всё правильно?

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 5

**Client:** Да, правильно.

**Bot:** Передаю подтверждённые данные заказа менеджеру.

Functions: `handoff_to_manager`. Latency: 15 ms. Tokens: 110. Cost: 0.0100 RUB.

Verdict: **PASS**

## Неоднозначный артикул (run 1)

Verdict: **PASS**

### Turn 1

**Client:** Нужно 3 штуки ABC-100.

**Bot:** По артикулу ABC-100 есть два варианта. Уточните код товара: 10001 или 10002.

Functions: `search_products`. Latency: 23 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 2

**Client:** Код 10002.

**Bot:** Уточнил позицию с кодом 10002. Три штуки доступны. Как будете получать и оплачивать заказ?

Functions: `search_products`. Latency: 23 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 3

**Client:** Самовывоз завтра, оплата наличными. Сергей, +7 912 300-40-50.

**Bot:** Итог: 3 штуки ABC-100, код 10002, самовывоз завтра, оплата наличными, Сергей, +7 912 300-40-50. Всё верно?

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 4

**Client:** Верно.

**Bot:** Передаю подтверждённые данные заказа менеджеру.

Functions: `handoff_to_manager`. Latency: 15 ms. Tokens: 110. Cost: 0.0100 RUB.

Verdict: **PASS**

## Ненайденный товар (run 1)

Verdict: **PASS**

### Turn 1

**Client:** Нужен артикул ZZZ-404, 4 штуки.

**Bot:** Точное совпадение по ZZZ-404 не найдено. Проверьте, пожалуйста, артикул или пришлите название товара.

Functions: `search_products`. Latency: 24 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 2

**Client:** Ошибся, нужен P-AM02/B-S, 4 штуки.

**Bot:** Нашёл P-AM02/B-S. Четыре штуки доступны. Как будете получать заказ?

Functions: `search_products`. Latency: 24 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 3

**Client:** Доставка в Казань до конца месяца, оплата по счёту.

**Bot:** Записал доставку в Казань до конца месяца и оплату по счёту. Укажите, пожалуйста, ИНН.

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 4

**Client:** ИНН 1650123456.

**Bot:** ИНН записал. Подскажите имя и телефон для связи.

Functions: `none`. Latency: 12 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 5

**Client:** Олег, +7 903 700-80-90.

**Bot:** Итог: 4 штуки P-AM02/B-S, доставка в Казань до конца месяца, оплата по счёту, ИНН 1650123456, Олег, +7 903 700-80-90. Всё верно?

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 6

**Client:** Да, подтверждаю.

**Bot:** Передаю подтверждённые данные заказа менеджеру.

Functions: `handoff_to_manager`. Latency: 16 ms. Tokens: 110. Cost: 0.0100 RUB.

Verdict: **PASS**

## Свободное описание не найдено, но заказ продолжается (run 1)

Verdict: **PASS**

### Turn 1

**Client:** Нужно 6 чёрных петель с доводчиком, кода не знаю.

**Bot:** Точного совпадения не нашёл, но учту это описание в разговоре для менеджера. Как вам удобнее получить заказ?

Functions: `search_products`. Latency: 24 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 2

**Client:** Доставка в Псков через две недели.

**Bot:** Записал доставку в Псков через две недели. Как планируете оплатить?

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 3

**Client:** Наличными.

**Bot:** Хорошо. Подскажите имя и телефон для связи.

Functions: `none`. Latency: 13 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 4

**Client:** Мария, +7 921 555-66-77.

**Bot:** Итог: 6 чёрных петель с доводчиком, доставка в Псков через две недели, оплата наличными, Мария, +7 921 555-66-77. Всё верно?

Functions: `none`. Latency: 13 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 5

**Client:** Да, всё верно.

**Bot:** Передаю подтверждённые данные заказа менеджеру.

Functions: `handoff_to_manager`. Latency: 15 ms. Tokens: 110. Cost: 0.0100 RUB.

Verdict: **PASS**

## В заказе один товар доступен, второго количества не хватает (run 1)

Verdict: **PASS**

### Turn 1

**Client:** Закажите 2 штуки 14.023пр. и 50 штук P-AM02/B-S.

**Bot:** По 14.023пр. нужное количество есть, а 50 штук P-AM02/B-S сейчас нет. Как поступим со второй позицией?

Functions: `search_products`. Latency: 24 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 2

**Client:** Вторую позицию уберите, оставьте только 2 штуки 14.023пр.

**Bot:** Оставил только 2 штуки 14.023пр. Как вам удобнее получить заказ?

Functions: `none`. Latency: 12 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 3

**Client:** Самовывоз завтра, наличными. Павел, +7 999 111-22-33.

**Bot:** Итог: 2 штуки 14.023пр., самовывоз завтра, оплата наличными, Павел, +7 999 111-22-33. Всё верно?

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 4

**Client:** Всё верно.

**Bot:** Передаю подтверждённые данные заказа менеджеру.

Functions: `handoff_to_manager`. Latency: 17 ms. Tokens: 110. Cost: 0.0100 RUB.

Verdict: **PASS**

## Исправление после показанного итога (run 1)

Verdict: **PASS**

### Turn 1

**Client:** Нужно заказать 2 штуки P-AM02/B-S.

**Bot:** Такое количество есть. Как вам удобнее получить заказ?

Functions: `search_products`. Latency: 24 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 2

**Client:** Доставка в Самару в понедельник, наличными. Лев, +7 927 100-20-30.

**Bot:** Итог: 2 штуки P-AM02/B-S, доставка в Самару в понедельник, оплата наличными, Лев, +7 927 100-20-30. Всё верно?

Functions: `none`. Latency: 11 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 3

**Client:** Нет, исправьте количество на 4 штуки.

**Bot:** Исправленный итог: 4 штуки P-AM02/B-S, доставка в Самару в понедельник, оплата наличными, Лев, +7 927 100-20-30. Всё верно?

Functions: `search_products`. Latency: 22 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 4

**Client:** Теперь всё верно.

**Bot:** Передаю подтверждённые данные заказа менеджеру.

Functions: `handoff_to_manager`. Latency: 15 ms. Tokens: 110. Cost: 0.0100 RUB.

Verdict: **PASS**

## Преждевременное подтверждение не передаёт заказ (run 1)

Verdict: **PASS**

### Turn 1

**Client:** Хочу заказать одну P-AM02/B-S.

**Bot:** Такое количество есть. Как вам удобнее получить заказ?

Functions: `search_products`. Latency: 22 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 2

**Client:** Да, подтверждаю.

**Bot:** Для продолжения подскажите способ получения и оплаты заказа.

Functions: `none`. Latency: 10 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 3

**Client:** Самовывоз завтра, оплата наличными. Игорь, +7 900 444-55-66.

**Bot:** Итог: одна P-AM02/B-S, самовывоз завтра, оплата наличными, Игорь, +7 900 444-55-66. Всё верно?

Functions: `none`. Latency: 12 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**

### Turn 4

**Client:** Да, этот итог верный.

**Bot:** Передаю подтверждённые данные заказа менеджеру.

Functions: `handoff_to_manager`. Latency: 16 ms. Tokens: 110. Cost: 0.0100 RUB.

Verdict: **PASS**

## Отмена заказа и смена темы (run 1)

Verdict: **PASS**

### Turn 1

**Client:** Хочу заказать одну P-AM02/B-S.

**Bot:** Нашёл P-AM02/B-S. Одна штука доступна. Как вам удобнее получить заказ?

Functions: `search_products`. Latency: 22 ms. Tokens: 236. Cost: 0.0200 RUB.

Verdict: **PASS**

### Turn 2

**Client:** Отмените, заказ не нужен. Лучше скажите режим работы в субботу.

**Bot:** Заказ не продолжаю. В субботу AMIX работает с 10:00 до 17:00.

Functions: `none`. Latency: 10 ms. Tokens: 125. Cost: 0.0100 RUB.

Verdict: **PASS**
