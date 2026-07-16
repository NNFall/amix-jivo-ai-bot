from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from time import perf_counter
from typing import Any, Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import core.assistant_service as assistant_module
import database.db as db_module
from core.assistant_service import AssistantService
from database.models import Base, Chat, LLMCall, Message, Product
from llm.openai_client import LLMTurnResult, ToolCall
from llm.prompts import SYSTEM_PROMPT
from llm.tool_schemas import OPENAI_TOOLS
from products.article_utils import normalize_article


DEFAULT_SCENARIOS_PATH = ROOT_DIR / "tests" / "history_order_eval_scenarios.json"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "history_order_eval_evidence.json"
ALLOWED_TOOL_NAMES = ("search_products", "handoff_to_manager")
FAKE_MODEL = "fake-history-order-eval-v1"
SUPPORTED_ASSERTION_TYPES = {
    "tool_called",
    "no_tool_called",
    "no_handoff",
    "handoff_reason",
    "response_contains",
    "response_contains_all",
    "response_contains_any",
    "response_not_contains",
    "tool_result_status",
    "tool_query_quantities",
    "handoff_summary_contains_all",
}

EVAL_CATALOG = [
    {
        "code": "769",
        "article": "14.023л.",
        "retail_price": "473.00",
        "corporate_price": "335.24",
        "free_stock": "37",
        "unit": "шт",
    },
    {
        "code": "770",
        "article": "14.023пр.",
        "retail_price": "473.00",
        "corporate_price": "335.24",
        "free_stock": "23",
        "unit": "шт",
    },
    {
        "code": "5001",
        "article": "Ручка белая 128 мм",
        "retail_price": "198.00",
        "corporate_price": "149.00",
        "free_stock": "61",
        "unit": "шт",
    },
    {
        "code": "10001",
        "article": "ABC-100",
        "retail_price": "120.00",
        "free_stock": "19",
        "unit": "шт",
    },
    {
        "code": "10002",
        "article": "ABC-100",
        "retail_price": "140.00",
        "free_stock": "43",
        "unit": "шт",
    },
    {
        "code": "22608",
        "article": "P-AM02/B-S",
        "retail_price": "350.00",
        "free_stock": "31",
        "unit": "шт",
    },
]


class FakeTurnProvider:
    def __init__(self) -> None:
        self._scenario_id = ""
        self._turn_index = 0
        self._turn: dict[str, Any] = {}
        self._call_index = 0
        self._tool_calls_emitted = False

    def start_turn(self, scenario_id: str, turn_index: int, turn: dict[str, Any]) -> None:
        self._scenario_id = scenario_id
        self._turn_index = turn_index
        self._turn = turn
        self._call_index = 0
        self._tool_calls_emitted = False

    def __call__(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
    ) -> LLMTurnResult:
        del messages, tool_choice
        self._call_index += 1
        fake = self._turn.get("fake") or {}
        configured_calls = fake.get("tool_calls") or []
        calls: list[ToolCall] = []
        if tools and configured_calls and not self._tool_calls_emitted:
            self._tool_calls_emitted = True
            for index, call in enumerate(configured_calls, start=1):
                name = str(call.get("name") or "")
                if name not in ALLOWED_TOOL_NAMES:
                    raise ValueError(f"Fake scenario requested disallowed tool: {name}")
                calls.append(
                    ToolCall(
                        name=name,
                        arguments=deepcopy(call.get("arguments") or {}),
                        call_id=f"fake-{self._scenario_id}-{self._turn_index}-{index}",
                    )
                )

        text = None if calls else fake.get("response")
        prompt_tokens = 100 + self._call_index
        completion_tokens = 20 if text else 5
        thinking_tokens = 4
        total_tokens = prompt_tokens + completion_tokens + thinking_tokens
        return LLMTurnResult(
            text=text,
            tool_calls=calls,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            cost={"estimated_usd": 0.0001, "estimated_rub": 0.01},
            latency_ms=3,
        )


class RecordingProvider:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.records: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
    ) -> LLMTurnResult:
        record = {
            "messages": deepcopy(messages),
            "tools": deepcopy(tools or []),
            "tool_choice": deepcopy(tool_choice),
            "result": {"status": "pending"},
        }
        self.records.append(record)
        try:
            result = self.delegate(messages=messages, tools=tools, tool_choice=tool_choice)
        except Exception as exc:
            record["result"] = {"status": "exception", "error": type(exc).__name__}
            raise
        record["result"] = {
            "status": result.error_type or "ok",
            "text": result.text,
            "tool_calls": [
                {
                    "name": call.name,
                    "arguments": deepcopy(call.arguments),
                    "call_id": call.call_id,
                }
                for call in result.tool_calls
            ],
            "usage": deepcopy(result.usage or {}),
            "cost": deepcopy(result.cost or {}),
            "latency_ms": int(result.latency_ms or 0),
        }
        return result


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _git_dirty_files() -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        return ["unknown"]
    return [line.rstrip() for line in completed.stdout.splitlines() if line.strip()]


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    scenarios = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("Scenarios file must contain a non-empty JSON array")
    seen: set[str] = set()
    for scenario in scenarios:
        scenario_id = str(scenario.get("id") or "").strip()
        if not scenario_id or scenario_id in seen:
            raise ValueError(f"Scenario id must be non-empty and unique: {scenario_id!r}")
        seen.add(scenario_id)
        turns = scenario.get("turns") or []
        if not turns:
            raise ValueError(f"Scenario {scenario_id!r} has no turns")
        for turn_index, turn in enumerate(turns, start=1):
            if not str(turn.get("input") or "").strip():
                raise ValueError(f"Scenario {scenario_id!r} turn {turn_index} has no input")
            assertions = turn.get("assertions") or []
            if not assertions:
                raise ValueError(f"Scenario {scenario_id!r} turn {turn_index} has no assertions")
            for assertion in assertions:
                _validate_assertion(scenario_id, turn_index, assertion)
    return scenarios


def _validate_assertion(scenario_id: str, turn_index: int, assertion: dict[str, Any]) -> None:
    assertion_type = str(assertion.get("type") or "").strip()
    if assertion_type not in SUPPORTED_ASSERTION_TYPES:
        raise ValueError(
            f"Scenario {scenario_id!r} turn {turn_index} has unknown assertion {assertion_type!r}"
        )
    if assertion_type in {"tool_called"} and not str(assertion.get("name") or "").strip():
        raise ValueError(f"Scenario {scenario_id!r} turn {turn_index} assertion requires name")
    if assertion_type in {"response_contains", "tool_result_status", "handoff_reason"}:
        if not str(assertion.get("value") or "").strip():
            raise ValueError(f"Scenario {scenario_id!r} turn {turn_index} assertion requires value")
    if assertion_type in {
        "response_contains_all",
        "response_contains_any",
        "response_not_contains",
        "handoff_summary_contains_all",
    }:
        values = assertion.get("values") or []
        if not values or any(not str(value).strip() for value in values):
            raise ValueError(f"Scenario {scenario_id!r} turn {turn_index} assertion requires values")
    if assertion_type == "tool_query_quantities":
        queries = assertion.get("queries") or []
        if not queries or any(not str(item.get("query") or "").strip() for item in queries):
            raise ValueError(f"Scenario {scenario_id!r} turn {turn_index} assertion requires queries")


def _eval_tools() -> list[dict[str, Any]]:
    by_name = {tool.get("function", {}).get("name"): tool for tool in OPENAI_TOOLS}
    missing = [name for name in ALLOWED_TOOL_NAMES if name not in by_name]
    if missing:
        raise RuntimeError(f"Production tool schema is missing required tools: {missing}")
    return [deepcopy(by_name[name]) for name in ALLOWED_TOOL_NAMES]


@contextmanager
def _patched_eval_tools(tools: list[dict[str, Any]]) -> Iterator[None]:
    original = assistant_module.OPENAI_TOOLS
    assistant_module.OPENAI_TOOLS = tools
    try:
        yield
    finally:
        assistant_module.OPENAI_TOOLS = original


@contextmanager
def _isolated_database() -> Iterator[Path]:
    original_engine = db_module.engine
    original_session_local = db_module.SessionLocal
    with tempfile.TemporaryDirectory(prefix="amix-history-order-eval-") as temp_dir:
        database_path = Path(temp_dir) / "eval.sqlite3"
        engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        db_module.engine = engine
        db_module.SessionLocal = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        Base.metadata.create_all(bind=engine)
        try:
            yield database_path
        finally:
            engine.dispose()
            db_module.engine = original_engine
            db_module.SessionLocal = original_session_local


def _seed_catalog() -> None:
    with db_module.session_scope() as session:
        for item in EVAL_CATALOG:
            session.add(
                Product(
                    code=item["code"],
                    article=item["article"],
                    normalized_article=normalize_article(item["article"]),
                    corporate_price=_decimal_or_none(item.get("corporate_price")),
                    retail_price=_decimal_or_none(item.get("retail_price")),
                    free_stock=_decimal_or_none(item.get("free_stock")),
                    unit=item.get("unit"),
                    raw_payload={"source": "history_order_eval"},
                )
            )


def _decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value not in (None, "") else None


def _configure_assistant(
    *, fake: bool, model: str | None
) -> tuple[AssistantService, FakeTurnProvider | None, RecordingProvider, str, str]:
    assistant = AssistantService()
    assistant.backend_prelookup_enabled = False
    assistant.deterministic_company_faq_enabled = False
    assistant.debug_lookup_logs = False
    assistant.debug_llm_payloads = False
    assistant.recent_history_limit = max(assistant.recent_history_limit, 50)
    assistant.openai_service.audit_logger.enabled = False

    if fake:
        fake_provider = FakeTurnProvider()
        recording_provider = RecordingProvider(fake_provider)
        assistant.openai_service.provider = "fake"
        assistant.openai_service.model = FAKE_MODEL
        assistant.openai_service.enabled = True
        assistant.openai_service.run_messages = recording_provider
        return assistant, fake_provider, recording_provider, "fake", FAKE_MODEL

    if not assistant.openai_service.google_ai_api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY is required for live Gemini mode; use --fake for offline mode")
    assistant.openai_service.provider = "google_ai"
    if model:
        assistant.openai_service.google_ai_model = model
    assistant.openai_service.google_ai_min_request_interval_seconds = min(
        assistant.openai_service.google_ai_min_request_interval_seconds,
        1.0,
    )
    assistant.openai_service.enabled = True
    recording_provider = RecordingProvider(assistant.openai_service.run_messages)
    assistant.openai_service.run_messages = recording_provider
    return assistant, None, recording_provider, "google_ai", assistant.openai_service.google_ai_model


def _max_message_id(session, external_chat_id: str) -> int:
    chat = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if chat is None:
        return 0
    value = session.scalar(
        select(Message.id).where(Message.chat_id == chat.id).order_by(Message.id.desc()).limit(1)
    )
    return int(value or 0)


def _max_llm_call_id(session, external_chat_id: str) -> int:
    chat = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if chat is None:
        return 0
    value = session.scalar(
        select(LLMCall.id).where(LLMCall.chat_id == chat.id).order_by(LLMCall.id.desc()).limit(1)
    )
    return int(value or 0)


def _new_messages(session, external_chat_id: str, after_id: int) -> list[Message]:
    chat = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if chat is None:
        return []
    return list(
        session.scalars(
            select(Message)
            .where(Message.chat_id == chat.id, Message.id > after_id)
            .order_by(Message.id.asc())
        ).all()
    )


def _new_llm_calls(session, external_chat_id: str, after_id: int) -> list[LLMCall]:
    chat = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if chat is None:
        return []
    return list(
        session.scalars(
            select(LLMCall)
            .where(LLMCall.chat_id == chat.id, LLMCall.id > after_id)
            .order_by(LLMCall.id.asc())
        ).all()
    )


def _parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _function_evidence(messages: list[Message]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for message in messages:
        if message.sender_role == "assistant_tool_call":
            for raw_call in (message.payload or {}).get("tool_calls") or []:
                function = raw_call.get("function") or {}
                calls.append(
                    {
                        "name": function.get("name"),
                        "arguments": _parse_json(function.get("arguments") or "{}"),
                        "call_id": raw_call.get("id"),
                    }
                )
        elif message.sender_role == "tool":
            results.append(
                {
                    "name": (message.payload or {}).get("tool_name"),
                    "call_id": (message.payload or {}).get("tool_call_id"),
                    "result": _parse_json(message.text),
                }
            )
    return calls, results


def _serialize_llm_calls(rows: list[LLMCall]) -> list[dict[str, Any]]:
    return [
        {
            "provider": row.provider,
            "model": row.model,
            "purpose": row.purpose,
            "status": row.status,
            "latency_ms": int(row.latency_ms or 0),
            "usage": {
                "prompt_tokens": int(row.prompt_tokens or 0),
                "completion_tokens": int(row.completion_tokens or 0),
                "thinking_tokens": int(row.thinking_tokens or 0),
                "total_tokens": int(row.total_tokens or 0),
            },
            "cost": {
                "estimated_usd": float(row.estimated_usd or 0),
                "estimated_rub": float(row.estimated_rub or 0),
            },
        }
        for row in rows
    ]


def _aggregate_llm_calls(rows: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, float]]:
    usage = {
        key: sum(int(row["usage"].get(key) or 0) for row in rows)
        for key in ("prompt_tokens", "completion_tokens", "thinking_tokens", "total_tokens")
    }
    cost = {
        key: round(sum(float(row["cost"].get(key) or 0) for row in rows), 8)
        for key in ("estimated_usd", "estimated_rub")
    }
    return usage, cost


def _contains(value: str, expected: str) -> bool:
    return expected.casefold().replace("ё", "е") in value.casefold().replace("ё", "е")


def _search_query_quantities(function_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for call in function_calls:
        if call.get("name") != "search_products":
            continue
        for item in (call.get("arguments") or {}).get("queries") or []:
            if isinstance(item, dict):
                query = str(item.get("query") or "").strip()
                quantity = item.get("requested_quantity")
            else:
                query = str(item or "").strip()
                quantity = None
            queries.append({"query": query, "requested_quantity": quantity})
    return queries


def _normalized_query_quantities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "query": str(item.get("query") or "").strip().casefold().replace("ё", "е"),
            "requested_quantity": item.get("requested_quantity"),
        }
        for item in items
    ]


def _assertion_result(spec: dict[str, Any], turn: dict[str, Any], handoff_reason: str | None) -> dict[str, Any]:
    assertion_type = str(spec.get("type") or "")
    response = str(turn.get("response") or "")
    calls = turn.get("function_calls") or []
    results_text = json.dumps(turn.get("function_results") or [], ensure_ascii=False, sort_keys=True)
    names = [str(call.get("name") or "") for call in calls]
    passed = False
    detail = ""

    if assertion_type == "tool_called":
        expected = str(spec.get("name") or "")
        passed = expected in names
        detail = f"called={names}"
    elif assertion_type == "no_tool_called":
        passed = not calls
        detail = f"called={names}"
    elif assertion_type == "no_handoff":
        passed = not handoff_reason
        detail = f"handoff_reason={handoff_reason!r}"
    elif assertion_type == "handoff_reason":
        expected = str(spec.get("value") or "")
        passed = handoff_reason == expected and "handoff_to_manager" in names
        detail = f"handoff_reason={handoff_reason!r}"
    elif assertion_type == "response_contains":
        expected = str(spec.get("value") or "")
        passed = _contains(response, expected)
        detail = f"expected={expected!r}"
    elif assertion_type == "response_contains_all":
        expected = [str(value) for value in spec.get("values") or []]
        passed = bool(expected) and all(_contains(response, value) for value in expected)
        detail = f"expected_all={expected!r}"
    elif assertion_type == "response_contains_any":
        expected = [str(value) for value in spec.get("values") or []]
        passed = bool(expected) and any(_contains(response, value) for value in expected)
        detail = f"expected_any={expected!r}"
    elif assertion_type == "response_not_contains":
        expected = [str(value) for value in spec.get("values") or []]
        passed = all(not _contains(response, value) for value in expected)
        detail = f"forbidden={expected!r}"
    elif assertion_type == "tool_result_status":
        expected = str(spec.get("value") or "")
        passed = _contains(results_text, expected)
        detail = f"expected_status={expected!r}"
    elif assertion_type == "tool_query_quantities":
        expected = _normalized_query_quantities(spec.get("queries") or [])
        actual = _normalized_query_quantities(_search_query_quantities(calls))
        passed = actual == expected
        detail = f"expected={expected!r}, actual={actual!r}"
    elif assertion_type == "handoff_summary_contains_all":
        expected = [str(value) for value in spec.get("values") or []]
        summaries = [
            str((call.get("arguments") or {}).get("summary") or "")
            for call in calls
            if call.get("name") == "handoff_to_manager"
        ]
        summary = summaries[-1] if summaries else ""
        passed = bool(expected) and all(_contains(summary, value) for value in expected)
        detail = f"expected_all={expected!r}, summary={summary!r}"
    else:
        detail = f"unknown assertion type: {assertion_type!r}"

    return {"type": assertion_type, "passed": passed, "detail": detail}


def _privacy_assertion(
    response: str,
    function_calls: list[dict[str, Any]],
    function_results: list[dict[str, Any]],
    provider_requests: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    visible = "\n".join(
        (
            response,
            json.dumps(function_calls, ensure_ascii=False, sort_keys=True),
            json.dumps(function_results, ensure_ascii=False, sort_keys=True),
            json.dumps(provider_requests or [], ensure_ascii=False, sort_keys=True),
        )
    )
    normalized = visible.casefold()
    forbidden_fields = ("free_stock", "raw_product_lookup_result")
    leaks = [field for field in forbidden_fields if field in normalized]
    for product in EVAL_CATALOG:
        stock = str(product["free_stock"])
        patterns = (
            rf"(?<!\d){re.escape(stock)}(?:[.,]0+)?\s*(?:шт|штук|единиц)",
            rf"(?:остат(?:ок|ка)|на складе)\D{{0,16}}{re.escape(stock)}(?:[.,]0+)?(?!\d)",
            rf"(?:доступно|есть в наличии)\D{{0,16}}{re.escape(stock)}(?:[.,]0+)?(?!\d)",
        )
        if any(re.search(pattern, normalized) for pattern in patterns):
            leaks.append(f"exact_stock:{stock}")
    return {
        "type": "stock_privacy",
        "passed": not leaks,
        "detail": "no exact stock in model-visible evidence" if not leaks else f"leaks={sorted(set(leaks))}",
    }


def _provider_health_assertion(
    *,
    mode: str,
    provider_name: str,
    provider_requests: list[dict[str, Any]],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    request_statuses = [str((item.get("result") or {}).get("status") or "") for item in provider_requests]
    call_statuses = [str(item.get("status") or "") for item in llm_calls]
    providers = [str(item.get("provider") or "") for item in llm_calls]
    token_totals = [int((item.get("usage") or {}).get("total_tokens") or 0) for item in llm_calls]
    passed = bool(provider_requests) and bool(llm_calls)
    passed = passed and all(status == "ok" for status in request_statuses + call_statuses)
    passed = passed and all(provider == provider_name for provider in providers)
    passed = passed and all(total > 0 for total in token_totals)
    return {
        "type": "provider_health",
        "passed": passed,
        "detail": (
            f"mode={mode}, requests={request_statuses}, calls={call_statuses}, "
            f"providers={providers}, tokens={token_totals}"
        ),
    }


def _full_history_assertion(
    provider_requests: list[dict[str, Any]], expected_customer_inputs: list[str]
) -> dict[str, Any]:
    first_messages = provider_requests[0].get("messages") if provider_requests else []
    serialized = json.dumps(first_messages or [], ensure_ascii=False)
    missing = [value for value in expected_customer_inputs if value not in serialized]
    return {
        "type": "complete_chronological_history",
        "passed": not missing,
        "detail": "all customer turns present" if not missing else f"missing={missing!r}",
    }


def _allowed_tools_assertion(function_calls: list[dict[str, Any]]) -> dict[str, Any]:
    names = [str(call.get("name") or "") for call in function_calls]
    disallowed = sorted(set(names) - set(ALLOWED_TOOL_NAMES))
    return {
        "type": "allowed_tools_only",
        "passed": not disallowed,
        "detail": f"called={names}" if not disallowed else f"disallowed={disallowed}",
    }


def _run_turn(
    *,
    assistant: AssistantService,
    fake_provider: FakeTurnProvider | None,
    recording_provider: RecordingProvider,
    provider_name: str,
    mode: str,
    session,
    scenario: dict[str, Any],
    repetition: int,
    turn_index: int,
    turn_spec: dict[str, Any],
) -> dict[str, Any]:
    scenario_id = str(scenario["id"])
    external_chat_id = f"history-order-eval:{scenario_id}:run:{repetition}"
    before_message_id = _max_message_id(session, external_chat_id)
    before_llm_call_id = _max_llm_call_id(session, external_chat_id)
    before_provider_request = len(recording_provider.records)
    if fake_provider is not None:
        fake_provider.start_turn(scenario_id, turn_index, turn_spec)

    started = perf_counter()
    reply = assistant.handle_client_message(
        session,
        external_chat_id=external_chat_id,
        external_client_id=f"history-order-eval-client:{scenario_id}",
        customer_name="History Order Eval",
        customer_text=str(turn_spec["input"]),
        inbound_event_id=f"{external_chat_id}:in:{turn_index}",
        outbound_event_id=f"{external_chat_id}:out:{turn_index}",
        payload={"source": "history_order_eval", "scenario_id": scenario_id, "turn": turn_index},
        handoff_mode="demo",
    )
    latency_ms = max(0, round((perf_counter() - started) * 1000))
    session.flush()

    messages = _new_messages(session, external_chat_id, before_message_id)
    function_calls, function_results = _function_evidence(messages)
    llm_calls = _serialize_llm_calls(_new_llm_calls(session, external_chat_id, before_llm_call_id))
    provider_requests = deepcopy(recording_provider.records[before_provider_request:])
    usage, cost = _aggregate_llm_calls(llm_calls)
    turn = {
        "index": turn_index,
        "input": str(turn_spec["input"]),
        "response": reply.text,
        "function_calls": function_calls,
        "function_results": function_results,
        "provider_requests": provider_requests,
        "latency_ms": latency_ms,
        "llm_calls": llm_calls,
        "usage": usage,
        "cost": cost,
        "assertions": [],
        "verdict": "FAIL",
    }
    assertions = [
        _assertion_result(spec, turn, reply.handoff_reason)
        for spec in turn_spec.get("assertions") or []
    ]
    assertions.append(_allowed_tools_assertion(function_calls))
    assertions.append(_privacy_assertion(reply.text, function_calls, function_results, provider_requests))
    assertions.append(
        _provider_health_assertion(
            mode=mode,
            provider_name=provider_name,
            provider_requests=provider_requests,
            llm_calls=llm_calls,
        )
    )
    assertions.append(
        _full_history_assertion(
            provider_requests,
            [str(item["input"]) for item in scenario["turns"][:turn_index]],
        )
    )
    turn["assertions"] = assertions
    turn["verdict"] = "PASS" if all(item["passed"] for item in assertions) else "FAIL"
    session.commit()
    return turn


def run_evaluation(
    *,
    scenarios_path: Path,
    output_path: Path,
    fake: bool,
    model: str | None = None,
    repeat: int = 1,
    markdown_output_path: Path | None = None,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    scenarios_path = scenarios_path.resolve()
    output_path = output_path.resolve()
    scenarios = _load_scenarios(scenarios_path)
    tools = _eval_tools()
    timestamp = _timestamp()
    mode = "deterministic_wiring_only" if fake else "live_model_behavior"

    with _isolated_database(), _patched_eval_tools(tools):
        _seed_catalog()
        assistant, fake_provider, recording_provider, provider_name, model_name = _configure_assistant(
            fake=fake,
            model=model,
        )
        scenario_rows: list[dict[str, Any]] = []
        with db_module.session_scope() as session:
            for repetition in range(1, repeat + 1):
                for scenario in scenarios:
                    turns = [
                        _run_turn(
                            assistant=assistant,
                            fake_provider=fake_provider,
                            recording_provider=recording_provider,
                            provider_name=provider_name,
                            mode=mode,
                            session=session,
                            scenario=scenario,
                            repetition=repetition,
                            turn_index=index,
                            turn_spec=turn,
                        )
                        for index, turn in enumerate(scenario["turns"], start=1)
                    ]
                    scenario_rows.append(
                        {
                            "id": scenario["id"],
                            "title": scenario.get("title") or scenario["id"],
                            "repetition": repetition,
                            "covers": scenario.get("covers") or [],
                            "turns": turns,
                            "verdict": "PASS" if all(turn["verdict"] == "PASS" for turn in turns) else "FAIL",
                        }
                    )

    passed_turns = sum(
        turn["verdict"] == "PASS"
        for scenario in scenario_rows
        for turn in scenario["turns"]
    )
    total_turns = sum(len(scenario["turns"]) for scenario in scenario_rows)
    passed_scenarios = sum(scenario["verdict"] == "PASS" for scenario in scenario_rows)
    evidence = {
        "manifest": {
            "git_sha": _git_sha(),
            "timestamp": timestamp,
            "provider": provider_name,
            "model": model_name,
            "mode": mode,
            "git_dirty_files": _git_dirty_files(),
            "isolated_sqlite": True,
            "state_source": "dialog_history_only",
            "jivo_delivery_enabled": False,
            "repeat": repeat,
            "tool_names": list(ALLOWED_TOOL_NAMES),
            "generation_config": {
                "temperature": assistant.openai_service.google_ai_temperature if not fake else None,
                "top_p": assistant.openai_service.google_ai_top_p if not fake else None,
                "reasoning_effort": assistant.openai_service.google_ai_reasoning_effort if not fake else None,
            },
            "sha256": {
                "prompt": _sha256(SYSTEM_PROMPT.encode("utf-8")),
                "tools": _sha256(_canonical_json(tools)),
                "scenarios": _sha256(scenarios_path.read_bytes()),
                "catalog": _sha256(_canonical_json(EVAL_CATALOG)),
                "runner": _sha256(Path(__file__).read_bytes()),
                "assistant_service": _sha256((ROOT_DIR / "core" / "assistant_service.py").read_bytes()),
                "dialog_service": _sha256((ROOT_DIR / "core" / "dialog_service.py").read_bytes()),
                "openai_client": _sha256((ROOT_DIR / "llm" / "openai_client.py").read_bytes()),
            },
        },
        "summary": {
            "scenarios": len(scenario_rows),
            "passed_scenarios": passed_scenarios,
            "turns": total_turns,
            "passed_turns": passed_turns,
            "verdict": "PASS" if passed_scenarios == len(scenario_rows) else "FAIL",
        },
        "scenarios": scenario_rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown_output_path is not None:
        markdown_output_path = markdown_output_path.resolve()
        markdown_output_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_output_path.write_text(_build_markdown_report(evidence), encoding="utf-8")
    return evidence


def _build_markdown_report(evidence: dict[str, Any]) -> str:
    manifest = evidence["manifest"]
    summary = evidence["summary"]
    lines = [
        "# History-driven order evaluation",
        "",
        f"- Verdict: **{summary['verdict']}**",
        f"- Provider/model: `{manifest['provider']}` / `{manifest['model']}`",
        f"- Repetitions: {manifest['repeat']}",
        f"- Scenarios: {summary['passed_scenarios']}/{summary['scenarios']} passed",
        f"- Turns: {summary['passed_turns']}/{summary['turns']} passed",
        "",
    ]
    for scenario in evidence["scenarios"]:
        lines.extend(
            [
                f"## {scenario['title']} (run {scenario['repetition']})",
                "",
                f"Verdict: **{scenario['verdict']}**",
                "",
            ]
        )
        for turn in scenario["turns"]:
            tool_names = ", ".join(call["name"] for call in turn["function_calls"]) or "none"
            failed = [item["detail"] for item in turn["assertions"] if not item["passed"]]
            lines.extend(
                [
                    f"### Turn {turn['index']}",
                    "",
                    f"**Client:** {turn['input']}",
                    "",
                    f"**Bot:** {turn['response']}",
                    "",
                    f"Functions: `{tool_names}`. Latency: {turn['latency_ms']} ms. "
                    f"Tokens: {turn['usage']['total_tokens']}. Cost: {turn['cost']['estimated_rub']:.4f} RUB.",
                    "",
                    f"Verdict: **{turn['verdict']}**"
                    + (f". Failed: {'; '.join(failed)}" if failed else ""),
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the reproducible AMIX dialog-history order evaluation")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--model", help="Gemini model override for live mode")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--fake", action="store_true", help="Use the deterministic offline provider")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_evaluation(
            scenarios_path=args.scenarios,
            output_path=args.output,
            fake=args.fake,
            model=args.model,
            repeat=args.repeat,
            markdown_output_path=args.markdown_output,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"history order eval failed: {exc}", file=sys.stderr)
        return 2
    print(f"Evidence: {args.output.resolve()}")
    print(f"Verdict: {evidence['summary']['verdict']}")
    return 0 if evidence["summary"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
