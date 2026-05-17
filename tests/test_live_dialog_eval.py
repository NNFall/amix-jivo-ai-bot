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


def test_live_eval_flags_price_on_stock_only_request() -> None:
    scenario = LiveScenario("L-010", "Точное наличие", "1108035 есть в наличии?", "Только наличие.")

    flags = _content_flags(
        scenario,
        "Проверил, сейчас в наличии 2 комплекта. Розничная цена 50 820 руб.",
        {},
    )

    assert "price_given_on_stock_only_request" in flags


def test_live_eval_flags_unresolved_price_refinement() -> None:
    scenario = LiveScenario("L-024", "Уточнение дубля по цене", "цена 132", "Выбрать позицию по цене.")

    flags = _content_flags(
        scenario,
        "По МП 28ск нашёл несколько позиций. Уточните код товара или цену.",
        {},
    )

    assert "price_refinement_not_resolved" in flags
    assert "repeat_clarification_after_price_refinement" in flags


def test_live_eval_accepts_resolved_price_refinement() -> None:
    scenario = LiveScenario("L-024", "Уточнение дубля по цене", "цена 132", "Выбрать позицию по цене.")

    flags = _content_flags(
        scenario,
        "Понял, по цене 132 руб. это код 26168. Сейчас в наличии 292 шт.",
        {},
    )

    assert flags == []
