from scripts.run_live_dialog_eval import LiveScenario, _content_flags, _style_flags


def _tool_history(name: str) -> list[dict]:
    return [
        {
            "role": "assistant_tool_call",
            "payload": {
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {"name": name, "arguments": "{}"},
                    }
                ]
            },
        }
    ]


def test_live_eval_flags_handoff_promise_without_function() -> None:
    scenario = LiveScenario("L-1", "Передача", "Позовите менеджера", "Нужен handoff.")

    flags = _content_flags(
        scenario,
        "Передаю вопрос менеджеру. Он подключится к диалогу.",
        {"function_history": []},
    )

    assert "handoff_promise_without_tool" in flags


def test_live_eval_accepts_handoff_promise_with_function() -> None:
    scenario = LiveScenario("L-1", "Передача", "Позовите менеджера", "Нужен handoff.")

    flags = _content_flags(
        scenario,
        "Передаю вопрос менеджеру. Он подключится к диалогу.",
        {"function_history": _tool_history("handoff_to_manager")},
    )

    assert flags == []


def test_live_eval_flags_unknown_function() -> None:
    scenario = LiveScenario("L-2", "Функции", "Проверка", "Только две функции.")

    flags = _content_flags(
        scenario,
        "Проверил.",
        {"function_history": _tool_history("web_search")},
    )

    assert flags == ["unknown_tools:web_search"]


def test_live_eval_style_flags_internal_or_formatted_output() -> None:
    flags = _style_flags("**Ответ:** backend JSON")

    assert "markdown_leak" in flags
    assert "internal_terms" in flags
