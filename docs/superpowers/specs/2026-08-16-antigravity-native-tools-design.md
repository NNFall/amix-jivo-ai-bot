# Antigravity native tools for AMIX

## Goal

Compare `gemini-3.7-flash-low`, `gemini-3.7-flash-medium`, and `gemini-3.7-flash-high` through the Antigravity Text API against the current production `gpt-5.6-sol`, then switch production only if the selected Gemini model preserves AMIX tool routing, order history, response quality, and operational reliability.

## Boundaries

- Keep the existing model-driven architecture and exactly two client functions: `search_products` and `handoff_to_manager`.
- Do not add keyword routing, order state, response templates, or product facts outside tool results.
- Send the AMIX system prompt separately and the complete customer/assistant text history as ordered messages.
- Use Antigravity client function calling directly instead of the Sol JSON-envelope emulation.
- Set `native_tools=none` in AMIX production. Antigravity read-only tools are intentionally disabled because product facts must come only from the local XML catalog and the bot does not need filesystem or web access.
- Keep the current Kaigo Sol and Gemini configuration for immediate rollback.

## Provider compatibility

The API returns native `tool_calls` and accepts `role=tool` results. A live compatibility probe found that it currently rejects a historical assistant message containing `tool_calls` with HTTP 400, while the same ordered dialog with the corresponding tool-result message succeeds. The adapter therefore omits only that unsupported transport object from the Antigravity request. AMIX still stores the complete assistant tool call and tool result chronologically in SQLite, and the tool result contains the original request and result facts.

## Evaluation and deploy gate

1. Unit-test payload conversion, native tool parsing, usage, and retry behavior.
2. Run identical representative dialogs against all three Gemini 3.7 Flash reasoning levels and the current Sol provider.
3. Run the full history-driven order suite against the selected model.
4. Reject the switch on invented product facts, wrong tool choice, premature handoff, missing final confirmation, broken history, provider errors, or materially worse customer language.
5. If accepted, update the VPS atomically, preserve rollback settings, restart both services, and verify internal/public health plus fresh journals.

