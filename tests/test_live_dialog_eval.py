from scripts.run_live_dialog_eval import LiveScenario, _content_flags


def test_live_eval_flags_contact_answer_without_contacts() -> None:
    scenario = LiveScenario("L-003", "Контакты", "Как с вами связаться?", "Контакты AMIX.")

    flags = _content_flags(scenario, "Добрый день! Подскажите, что нужно посмотреть?", {})

    assert "contacts_missing" in flags
    assert "generic_greeting_instead_of_contacts" in flags


def test_live_eval_accepts_contact_answer_with_phone_or_email() -> None:
    scenario = LiveScenario("L-003", "Контакты", "Как с вами связаться?", "Контакты AMIX.")

    flags = _content_flags(scenario, "Можно позвонить по телефону +7 (812) 372-66-07 или написать на market@amix.spb.ru.", {})

    assert flags == []


def test_live_eval_flags_code_spacing_and_rounded_corporate_price() -> None:
    code_scenario = LiveScenario("L-009", "Код", "код 26168", "Код товара.")
    price_scenario = LiveScenario("L-020", "Смешанный поиск", "Проверьте 14.023пр. и XYZ-999", "Цены.")

    assert "code_spacing" in _content_flags(code_scenario, "По коду26168 нашёл товар.", {})
    assert "corporate_price_rounded" in _content_flags(
        price_scenario,
        "По 14.023пр. корпоративная 335 руб.",
        {},
    )
