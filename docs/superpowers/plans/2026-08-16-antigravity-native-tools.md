# Antigravity native tools implementation plan

1. Add Antigravity settings and an isolated provider branch in `OpenAIService`.
2. Convert AMIX messages to the API shape, declare only the two AMIX tools, and disable Antigravity-native tools.
3. Parse native `output_text`, `tool_calls`, usage, latency, and retryable errors into the existing `LLMTurnResult`.
4. Extend provider tests and the history-order evaluation runner.
5. Compare Gemini 3.7 Flash low/medium/high with the current Sol model on identical scenarios.
6. Run the full selected-model evaluation, full pytest, compile check, and diff check.
7. If the gate passes, deploy with rollback-safe environment changes and verify Jivo services and health endpoints.

