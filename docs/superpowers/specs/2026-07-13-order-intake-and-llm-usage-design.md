# Order Intake And LLM Usage Design

## Source requirements

This implementation is based on the following requests from the AMIX discussion:

- Андрей: "Если клиент хочет оформить заказ, бот же может уточнить, что нужно клиенту".
- Артём: "Не важно, знает клиент артикулы/коды или нет".
- Пользователь: "чтобы он финально, чтобы передавать менеджеру всё-таки, summary в диалоге подводил".
- Пользователь: "для счета ... какие конкретно данные собирать".
- Пользователь: "количество токенов за каждое сообщение ... фиксировать у себя в локальной базе данных".
- Пользователь отдельно уточнил, что распознавание PDF, Excel и фото в эту задачу не входит.

## Approved behavior

### Order intake

An order request starts an intake flow instead of an immediate manager handoff. Gemini extracts the customer's meaning and updates a structured order draft through a dedicated tool. The backend does not try to understand arbitrary product descriptions with keyword rules.

If Gemini recognizes an explicit order request but answers with plain text instead of calling the tool, the service retries the model once with `update_order_draft` selected as the required function. This keeps order interpretation in the model while guaranteeing that the multi-turn draft is actually created.

The draft can contain products either as codes/articles or as free-form descriptions. For every item the bot asks for a quantity. It also collects the customer's desired timing without promising a delivery date, delivery or pickup details, payment method and a contact.

AMIX confirmed the final minimum on 2026-07-14. Every order requires the customer's name and phone. Payment by bank transfer additionally requires INN. The bot must not require customer type, company/IP name, KPP or invoice email, but it may preserve these fields when the customer provides them voluntarily.

### Confirmation and handoff

When all required information is present, the backend builds a canonical summary from the stored draft. The bot shows that summary and asks the customer to confirm it.

The order handoff is allowed only when all conditions are true:

1. the draft is waiting for confirmation;
2. the canonical summary is the immediately preceding customer-visible bot message;
3. the latest customer message explicitly confirms the summary;
4. the model requests the order handoff.

After handoff, the stored summary is included in the handoff tool history for the manager. A direct request for a human remains an immediate handoff and does not require order confirmation.

### Product checks during intake

If an item has a code or article, the order-draft tool checks it against the existing product table. It stores only a safe result: found/not found/multiple variants and, when quantity is known, whether the requested quantity is available. Exact stock is never shown.

If stock is missing in the source data, availability remains unknown rather than being treated as a shortage. If a newer customer message supersedes a running order turn, hidden draft/tool/reply changes from that turn are discarded while the provider usage record is retained.

If the customer does not know a code or article, the free-form description is preserved for the manager. The bot does not pretend it selected a product.

### Delivery and payment knowledge

The prompt uses the AMIX delivery and payment pages as the factual source. It may explain available methods, but exact delivery price and order-specific terms remain the manager's responsibility.

Sources reviewed on 2026-07-13:

- https://amix-tk.ru/zakaz/dostavka/
- https://amix-tk.ru/zakaz/oplata/

### Persistent LLM usage

Every LLM call is stored in SQLite and linked to the chat. The record contains provider, model, purpose, request id, token counts, inferred thinking tokens, latency and estimated USD/RUB cost.

Gemini returns token usage in the same API response. The service must not make a second request to Google to retrieve usage.

The existing rotating JSON audit remains for request/response diagnostics and masks contact and invoice identifiers before writing. SQLite becomes the cumulative source for project statistics. Additional debug logs that can contain conversation text are disabled by default and must be enabled explicitly for temporary diagnostics.

The pricing table for Gemini 3.1 Flash-Lite is updated to the current standard paid tariff reviewed on 2026-07-13: USD 0.25 per 1M input tokens and USD 1.50 per 1M output tokens including thinking.

## Out of scope

- Creating an order in 1C or on the AMIX website.
- Parsing PDF, Excel, photos or scanned specifications.
- Requesting bank card data or other payment secrets.
- Product selection or technical recommendations from free-form descriptions.

## Verification scenarios

1. "Мне нужно оформить заказ" asks what products and quantities are needed and does not hand off.
2. A customer can provide items without codes; their description is retained.
3. A coded item is checked without exposing exact stock.
4. Delivery, payment and contact details accumulate across messages.
5. Every order asks for name and phone; bank transfer additionally asks only for INN.
6. A complete draft is summarized and waits for explicit confirmation.
7. "Да" after the summary triggers one real handoff with the order summary.
8. A premature order handoff tool call is blocked.
9. A direct request for a manager still hands off immediately.
10. Every successful Gemini call creates a cumulative SQLite usage record.
11. Usage remains stored if a later outbound Jivo operation fails and its transaction is rolled back.
12. A model cannot bypass the order confirmation guard by using a non-order handoff reason.
13. A dissatisfied customer can still be handed to a manager during an active order.
14. Jivo is invited before the customer receives the handoff promise; an invite failure does not send a false promise.
