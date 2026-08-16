from llm.prompts import SYSTEM_PROMPT


def test_invoice_order_requires_inn_before_moving_past_missing_billing_details() -> None:
    assert "ИНН ещё не назван" in SYSTEM_PROMPT
    assert "обязательно запроси ИНН в ближайшем ответе" in SYSTEM_PROMPT

