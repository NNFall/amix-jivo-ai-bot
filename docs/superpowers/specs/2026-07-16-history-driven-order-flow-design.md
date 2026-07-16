# History-Driven Order Flow Design

## Goal

Simplify AMIX order intake so Gemini conducts the conversation from the complete chronological chat history instead of maintaining a second structured order memory in the backend.

The runtime exposes exactly two functions to the model:

- `search_products` for product facts;
- `handoff_to_manager` for a real operator transfer.

There is no order-draft function, summary function, hidden order aggregate or backend order state machine.

## Approved Behavior

Gemini uses the entire persisted conversation as its working memory. The history contains every client message, bot message, assistant function call and function result in chronological order from the beginning of the chat.

The backend does not truncate a normal chat to a fixed number of database rows. If a conversation ever exceeds the provider context window, the service must fail safely instead of silently removing early order details.

When the client explicitly wants to place an order, Gemini:

1. Understands what has already been agreed from the conversation.
2. Collects the products and quantity for each product.
3. Collects the desired timing without promising supply dates.
4. Collects pickup or delivery and the destination city when delivery is requested.
5. Collects the payment method.
6. Collects the client's name and phone number.
7. Collects INN only when payment by invoice is requested.
8. Does not ask again for information already present in the history.
9. Treats later corrections as replacing the corresponding earlier information.
10. Asks one natural next question instead of sending the client a full questionnaire.
11. Produces a concise final summary of the current agreement and asks the client to confirm it.
12. If the client corrects the summary, continues the conversation and presents an updated summary.
13. Calls `handoff_to_manager` with `reason=order_creation` only after an explicit confirmation of the latest summary.

The bot does not claim that the order is already created. It says that the collected request is being transferred to a manager for continued processing.

An explicit request for a person remains an immediate handoff and does not require order confirmation.

## Prompt Design

The order policy is one compact, generalized section in the system prompt. It describes goals, required information, conversational sequencing, corrections, final confirmation and handoff conditions.

The prompt must not contain rules tied to isolated article formats, spelling mistakes, individual test products or one-off customer phrases. It must not turn the conversation into a fixed script.

Examples are not used as the primary control mechanism. Prompt changes are made only for repeated behavioral categories found across several dialogues, and the resulting rule must remain applicable to unseen conversations.

The existing non-sales style remains:

- consult rather than pressure the customer;
- do not offer order creation unless the customer expresses that intent;
- keep replies short and natural;
- do not invent product facts or technical advice;
- use a manager for product selection, compatibility and unsupported technical questions.

## Product Search Contract

`search_products` remains one function, but its request must represent every product independently. Each requested item contains:

- the client's product query;
- the requested quantity when the client supplied it.

This replaces one scalar quantity shared by all queries. It prevents a request for different quantities of several products from being checked against the wrong value.

The tool result preserves the mapping between the client's query, product code and article. Customer replies must retain that identity instead of silently replacing codes with article names.

For protected stock questions, the model receives only the information needed to answer whether the requested quantity is available. It must not reveal the exact free stock.

## History And Persistence

SQLite remains the durable source of conversation history. The provider payload is built from all persisted messages for the current chat, ordered chronologically:

- `client` becomes `user`;
- `bot` becomes `assistant`;
- `assistant_tool_call` remains an assistant function call;
- `tool` remains its matching function result.

The old `OrderDraft` runtime path is removed completely. Existing rows in the deployed `order_drafts` table must not activate order behavior or enter runtime context. The physical table may remain for one deployment as rollback data, then be removed in a later migration after the new flow is accepted.

Historical `update_order_draft` messages already stored in old chats remain part of their real chronology, but the function is no longer declared or callable in new model requests.

## Backend Responsibilities That Remain

Removing the order draft does not remove transport and safety responsibilities:

- persist all inbound and outbound messages;
- process duplicate Jivo events idempotently;
- combine rapid consecutive client messages and suppress stale model responses;
- never answer after an operator has joined or the chat is closed;
- execute a real `INVITE_AGENT` before telling the client that a manager was called;
- if `INVITE_AGENT` fails, do not send a false handoff promise;
- keep product facts database-backed;
- keep exact-stock protection;
- retain LLM usage and cost accounting.

The backend does not parse the conversation into a second order representation and does not independently decide which order fields are missing.

## Removed Runtime Components

- `update_order_draft` tool declaration and execution;
- forced retry requiring the order-draft tool;
- `OrderIntakeService` runtime use;
- draft lookup as an order-mode switch;
- draft data in `INTERNAL_CONTEXT_JSON`;
- draft-based canonical summary generation;
- draft-based order handoff blocking;
- draft-specific regression classifications.

Generic handoff audit records, message history, product lookup, LLM accounting and Jivo lifecycle handling remain.

## Verification Strategy

Implementation follows TDD. Existing tests are first replaced with behavior-level tests that fail without the new design.

Deterministic coverage includes:

- exactly two model tools are exposed;
- all chronological messages are sent without the old 20-row truncation;
- multi-product searches preserve a separate requested quantity for every item;
- legacy draft rows do not affect routing;
- explicit customer confirmation can lead to an order handoff;
- a correction instead of confirmation does not hand off;
- a failed Jivo invite cannot produce a success promise;
- stale and rapid-message turns produce one current response and no stale side effects;
- operator join and closed-chat events stop bot replies.

Real Gemini evaluation runs on the server against an isolated database and current product catalog. It contains diverse multi-turn conversations covering:

- several coded products with different quantities;
- products described without codes;
- corrections to products, quantities, delivery, payment and contacts;
- bank-transfer and non-bank-transfer orders;
- ambiguous and missing products;
- cancellation and later topic changes;
- rapid consecutive user messages;
- final confirmation and manager handoff;
- provider retry and Jivo handoff failure.

Each scenario is run multiple times. Full chronological payloads, function calls, replies, latency, tokens and pass/fail assertions are saved to JSON, with a readable local report generated from that evidence.

Prompt refinement is iterative:

1. Run the frozen scenario set.
2. Group failures by general behavior, not by literal test phrase.
3. Make the smallest generalized prompt change.
4. Re-run the full set, including unchanged and adversarial scenarios.
5. Reject a prompt change if it fixes one dialogue by making other conversations more scripted or less accurate.

Independent reviewers receive separate scopes for code correctness, prompt quality and blinded transcript evaluation. Production deployment is allowed only after deterministic tests pass and the repeated live-dialog report has no safety-critical failures.

## Out Of Scope

- automatic order creation in an external accounting or CRM system;
- PDF, Excel or image specification recognition;
- product recommendation based on unsupported catalog knowledge;
- a replacement hidden order state under another name;
- a separate final-summary function.
