from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import database.db as db_module
from core.assistant_service import AssistantService
from database.db import create_db_and_tables, session_scope
from database.models import Base, Product
from llm.openai_client import LLMTurnResult
from products.article_utils import extract_article_candidates


TEST_PRODUCTS = [
    {
        "code": "22608",
        "article": "P-AM02/B-S",
        "normalized_article": "PAM02BS",
        "free_stock": Decimal("1"),
        "unit": "шт",
        "weight": Decimal("0.638"),
    },
    {
        "code": "1364",
        "article": "14.025пр.",
        "normalized_article": "14025ПР",
        "retail_price": Decimal("238"),
        "corporate_price": Decimal("165.98"),
        "free_stock": Decimal("7"),
        "unit": "шт",
        "weight": Decimal("0.07"),
    },
    {
        "code": "769",
        "article": "14.023л.",
        "normalized_article": "14023Л",
        "retail_price": Decimal("473"),
        "corporate_price": Decimal("335.24"),
        "free_stock": Decimal("253"),
        "unit": "шт",
        "weight": Decimal("0.07"),
    },
    {
        "code": "770",
        "article": "14.023пр.",
        "normalized_article": "14023ПР",
        "retail_price": Decimal("473"),
        "corporate_price": Decimal("335.24"),
        "free_stock": Decimal("220"),
        "unit": "шт",
        "weight": Decimal("0.07"),
    },
    {
        "code": "10001",
        "article": "ABC-100",
        "normalized_article": "ABC100",
        "retail_price": Decimal("120"),
        "free_stock": Decimal("5"),
        "unit": "шт",
    },
    {
        "code": "10002",
        "article": "ABC-100",
        "normalized_article": "ABC100",
        "retail_price": Decimal("140"),
        "free_stock": Decimal("8"),
        "unit": "шт",
    },
]


def seed_test_products() -> None:
    with session_scope() as session:
        for item in TEST_PRODUCTS:
            if session.query(Product).filter(Product.code == item["code"]).first():
                continue
            session.add(Product(**item, raw_payload={"source": "dialog_regression_eval"}))


def _configure_isolated_database(database_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db_module.engine = engine
    db_module.SessionLocal = session_local
    Base.metadata.create_all(bind=engine)


def _classify_action(case: dict, lookup: dict | None, reply_handoff_reason: str | None) -> str:
    if reply_handoff_reason:
        if lookup is not None:
            return "product_lookup_then_handoff"
        return "handoff"
    if lookup is None:
        text = case["customer_text"].lower()
        if any(word in text for word in ("цена", "стоит", "наличие", "остаток")):
            return "clarify"
        return "company_or_direct_reply"
    successful_queries = [
        item for item in lookup.get("per_query_results", [])
        if item.get("status") in {"exact_found", "multiple_exact"}
    ]
    if len(successful_queries) > 1:
        return "multi_product_lookup"
    status = lookup.get("status")
    if status == "multiple_exact":
        return "multiple_exact_product_lookup"
    if status == "exact_found":
        return "exact_product_lookup"
    if status == "similar_found":
        return "similar_product_lookup"
    if status == "not_found":
        return "not_found_product_lookup"
    return "product_lookup"


def _evaluate_case(case: dict, actual_action: str, lookup: dict | None, reply_text: str, handoff_reason: str | None) -> tuple[str, str]:
    expected_action = case["expected_action"]
    criteria = set(case.get("criteria", []))
    failures: list[str] = []

    action_ok = actual_action == expected_action or (
        expected_action == "product_lookup" and lookup is not None
    ) or (
        expected_action == "company_answer" and lookup is None and not handoff_reason
    ) or (
        expected_action == "company_or_direct_reply" and lookup is None and not handoff_reason
    ) or (
        expected_action == "multi_product_lookup" and lookup is not None
    )
    if not action_ok:
        failures.append(f"expected action {expected_action}, got {actual_action}")

    reply_text_lower = reply_text.lower()
    for phrase in ("в демо-режиме", "в рабочем режиме я бы", "этот вопрос требует менеджера"):
        if phrase in reply_text_lower:
            failures.append(f"banned user-facing phrase: {phrase}")

    if "product_lookup" in criteria and lookup is None:
        failures.append("product lookup was not used")
    if "no_product_lookup" in criteria and lookup is not None:
        failures.append("unexpected product lookup")
    if "handoff" in criteria and not handoff_reason:
        failures.append("handoff was not requested")
    if "no_handoff" in criteria and handoff_reason:
        failures.append("unexpected handoff")
    has_exact = bool((lookup or {}).get("exact_matches"))
    if "точного совпадения" in reply_text_lower and "не наш" in reply_text_lower and has_exact:
        failures.append("reply says exact match was not found despite exact matches")
    if "exact_found" in criteria and not has_exact:
        failures.append("exact_found expected")
    if "multiple_exact" in criteria and (lookup or {}).get("status") != "multiple_exact":
        failures.append("multiple_exact expected")
    if "similar_found" in criteria and (lookup or {}).get("status") != "similar_found":
        failures.append("similar_found expected")
    if "not_found" in criteria and (lookup or {}).get("status") != "not_found":
        failures.append("not_found expected")
    if "not_similar" in criteria and lookup and lookup.get("status") == "similar_found":
        failures.append("exact query was treated as similar")
    if "exact_found" in criteria and lookup and lookup.get("status") == "similar_found":
        failures.append("exact query was treated as similar")
    if "no_fake_price" in criteria and "0 руб" in reply_text:
        failures.append("possible fake zero price")
    if "search_by_code" in criteria and lookup:
        codes = {item.get("code") for item in lookup.get("exact_matches", [])}
        if not codes:
            failures.append("no exact code match")
    if "shows_all_exact" in criteria and lookup and lookup.get("exact_matches_count", 0) < 2:
        failures.append("not all exact variants shown in lookup")
    if "multiple_queries" in criteria and lookup:
        successful_queries = [
            item for item in lookup.get("per_query_results", [])
            if item.get("status") in {"exact_found", "multiple_exact"}
        ]
        summary = lookup.get("summary", {})
        if len(successful_queries) < 2:
            failures.append("multiple queries were not checked")
        if int(summary.get("total_exact_matches") or 0) < 2:
            failures.append("multiple queries did not return two exact products")
    if "stock_less_than_requested" in criteria and lookup:
        exact = lookup.get("exact_matches", [])
        if exact and Decimal(exact[0].get("stock") or "0") >= Decimal("5"):
            failures.append("stock was not less than requested")
    if "offers_help" in criteria and not any(word in reply_text_lower for word in ("подскажите", "помочь", "интересует")):
        failures.append("reply does not offer help naturally")
    if handoff_reason and "переда" not in reply_text_lower:
        failures.append("handoff reply does not tell the customer that the question is being transferred")

    if not failures:
        return "OK", ""
    if action_ok and len(failures) <= 2:
        return "PARTIAL", "; ".join(failures)
    return "FAIL", "; ".join(failures)


def _fake_llm_turn(**kwargs) -> LLMTurnResult:
    messages = kwargs.get("messages", [])
    user_text = "\n".join(str(message.get("content", "")) for message in messages if message.get("role") == "user").lower()

    if kwargs.get("tools"):
        if "где вы" in user_text or "находитесь" in user_text:
            return LLMTurnResult(
                text="Мы находимся в Санкт-Петербурге: ул. Якорная, д. 15, лит. Б.",
                tool_calls=[],
            )
        if "связаться" in user_text or "телефон" in user_text:
            return LLMTurnResult(
                text="Можно позвонить по телефону +7 (812) 372-66-07 или написать на market@amix.spb.ru.",
                tool_calls=[],
            )
        if "достав" in user_text:
            return LLMTurnResult(
                text="Да, возможна доставка по России, в том числе транспортными компаниями и в пункты выдачи.",
                tool_calls=[],
            )
        if "возврат" in user_text and "суббот" in user_text:
            return LLMTurnResult(
                text="По субботам возврат товара не осуществляется.",
                tool_calls=[],
            )
    return LLMTurnResult(text=None, tool_calls=[])


ACTION_LABELS = {
    "company_or_direct_reply": "Обычный ответ без поиска товара",
    "company_answer": "Ответ по справочной информации AMIX",
    "clarify": "Уточняющий вопрос: нужен артикул или код",
    "exact_product_lookup": "Поиск товара: найдено точное совпадение",
    "multiple_exact_product_lookup": "Поиск товара: найдено несколько точных позиций",
    "similar_product_lookup": "Поиск товара: точного нет, показаны похожие",
    "not_found_product_lookup": "Поиск товара: ничего не найдено",
    "multi_product_lookup": "Поиск нескольких товаров",
    "product_lookup": "Поиск товара в базе",
    "product_lookup_then_handoff": "Сначала поиск товара, затем передача менеджеру",
    "handoff": "Передача менеджеру",
}


HANDOFF_LABELS = {
    "explicit_manager_request": "клиент попросил менеджера",
    "complex_technical_question": "сложный технический вопрос",
    "order_request": "оформление заказа",
    "requested_quantity_exceeds_stock": "нужного количества больше, чем свободный остаток",
    "client_dissatisfied": "клиент недоволен и просит человека",
}


def run_eval(*, cases_path: Path, output_path: Path, seed: bool, isolated: bool, append: bool) -> None:
    temp_dir = None
    if isolated:
        temp_dir = tempfile.TemporaryDirectory()
        _configure_isolated_database(Path(temp_dir.name) / "dialog_regression_eval.db")
    else:
        create_db_and_tables()

    if seed:
        seed_test_products()

    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    assistant = AssistantService()
    assistant.openai_service.enabled = True
    assistant.openai_service.run_messages = _fake_llm_turn
    started_at = datetime.now(UTC)
    rows: list[dict[str, Any]] = []

    with session_scope() as session:
        for index, case in enumerate(cases, start=1):
            customer_text = case["customer_text"]
            candidates = extract_article_candidates(customer_text)
            lookup = None
            if candidates:
                lookup = assistant._search_products_by_queries(  # noqa: SLF001
                    session,
                    queries=candidates,
                    reason=assistant._guess_lookup_reason(customer_text),  # noqa: SLF001
                )

            reply = assistant.handle_client_message(
                session,
                external_chat_id=f"dialog-regression:{started_at.timestamp()}:{index}",
                external_client_id="dialog-regression-user",
                customer_name="Dialog Regression",
                customer_text=customer_text,
                inbound_event_id=f"dialog-regression:{started_at.timestamp()}:{index}:in",
                outbound_event_id=f"dialog-regression:{started_at.timestamp()}:{index}:out",
                payload={"source": "dialog_regression_eval", "case_id": case["id"]},
                handoff_mode="demo",
            )
            actual_action = _classify_action(case, lookup, reply.handoff_reason)
            status, comment = _evaluate_case(case, actual_action, lookup, reply.text, reply.handoff_reason)
            rows.append(
                {
                    "id": case["id"],
                    "question": customer_text,
                    "candidates": candidates,
                    "expected_action": case["expected_action"],
                    "actual_action": actual_action,
                    "expected_meaning": case["expected_meaning"],
                    "lookup_status": (lookup or {}).get("status"),
                    "exact_count": ((lookup or {}).get("summary") or {}).get("total_exact_matches", (lookup or {}).get("exact_matches_count")),
                    "similar_count": ((lookup or {}).get("summary") or {}).get("total_similar_matches", (lookup or {}).get("similar_matches_count")),
                    "query_count": len((lookup or {}).get("per_query_results", [])),
                    "handoff_reason": reply.handoff_reason,
                    "answer": reply.text,
                    "status": status,
                    "comment": comment,
                }
            )

    _write_report(output_path=output_path, started_at=started_at, rows=rows, append=append)
    print(f"Dialog regression eval saved to: {output_path}")
    print(f"OK={sum(row['status'] == 'OK' for row in rows)} PARTIAL={sum(row['status'] == 'PARTIAL' for row in rows)} FAIL={sum(row['status'] == 'FAIL' for row in rows)}")
    if temp_dir is not None:
        db_module.engine.dispose()
        temp_dir.cleanup()


def _write_report(*, output_path: Path, started_at: datetime, rows: list[dict[str, Any]], append: bool) -> None:
    mode = "a" if append else "w"
    ok_count = sum(row["status"] == "OK" for row in rows)
    partial_count = sum(row["status"] == "PARTIAL" for row in rows)
    fail_count = sum(row["status"] == "FAIL" for row in rows)

    with output_path.open(mode, encoding="utf-8") as fp:
        if append:
            fp.write("\n---\n\n")
        fp.write("# Отчёт по автопроверке диалогов AMIX-бота\n\n")
        fp.write(f"Дата прогона: `{started_at.isoformat()}`\n\n")
        fp.write("Что проверялось: бот должен отвечать как менеджер первой линии, искать товарные факты только в SQLite, не выдумывать цены/остатки/характеристики и передавать сложные вопросы менеджеру.\n\n")
        fp.write(f"Итог: OK — {ok_count}, частично — {partial_count}, ошибки — {fail_count}.\n\n")
        fp.write("Пояснение по функциям:\n")
        fp.write("- `search_products` — поиск товара в базе по артикулу или коду.\n")
        fp.write("- `handoff_to_manager` — передача диалога менеджеру.\n")
        fp.write("- `нет` — функция не нужна, бот отвечает сам по справке или задаёт уточняющий вопрос.\n\n")

        for row in rows:
            fp.write(f"## {row['id']} — {row['status']}\n\n")
            fp.write(f"Вопрос клиента: {row['question']}\n\n")
            fp.write(f"Что ожидали: {row['expected_meaning']}\n\n")
            fp.write(f"Что сделал backend: {_describe_action(row['actual_action'])}\n\n")
            fp.write("Какие функции были вызваны:\n")
            for call in _describe_function_calls(row):
                fp.write(f"- {call}\n")
            fp.write(f"\nОтвет бота: {row['answer']}\n\n")
            if row["comment"]:
                fp.write(f"Комментарий проверки: {row['comment']}\n\n")


def _describe_action(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def _describe_function_calls(row: dict[str, Any]) -> list[str]:
    calls: list[str] = []
    if row["lookup_status"]:
        calls.append(
            "search_products: проверил запросов {queries}; результат: {status}, всего точных позиций {exact}, похожих {similar}".format(
                queries=row.get("query_count") or 1,
                status=_describe_lookup_status(row["lookup_status"]),
                exact=row["exact_count"],
                similar=row["similar_count"],
            )
        )
    if row["handoff_reason"]:
        reason = HANDOFF_LABELS.get(row["handoff_reason"], row["handoff_reason"])
        calls.append(f"handoff_to_manager: {reason}")
    if not calls:
        calls.append("нет")
    return calls


def _describe_lookup_status(status: str) -> str:
    labels = {
        "exact_found": "найдено точное совпадение",
        "multiple_exact": "найдено несколько точных совпадений",
        "similar_found": "точного совпадения нет, есть похожие",
        "not_found": "ничего не найдено",
        "invalid_query": "нечего искать",
        "error": "ошибка поиска",
    }
    return labels.get(status, status)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AMIX dialog regression cases and append a markdown report.")
    parser.add_argument("--cases", default="tests/dialog_eval_cases.json")
    parser.add_argument("--output", default="DIALOG_EVALS.md")
    parser.add_argument("--no-seed", action="store_true", help="Do not add stable test products before running.")
    parser.add_argument("--use-current-db", action="store_true", help="Run against the configured project database instead of an isolated test DB.")
    parser.add_argument("--append", action="store_true", help="Append the report instead of replacing the output file.")
    args = parser.parse_args()

    run_eval(
        cases_path=Path(args.cases),
        output_path=Path(args.output),
        seed=not args.no_seed,
        isolated=not args.use_current_db,
        append=args.append,
    )


if __name__ == "__main__":
    main()
