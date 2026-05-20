from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from json import JSONDecodeError, dumps, loads
from typing import Any

import httpx
from openai import OpenAI

from llm.audit_log import LLMAuditLogger, cost_to_dict, estimate_cost, extract_usage_stats, usage_to_dict
from llm.prompts import build_llm_messages
from llm.tools import trim_text


logger = logging.getLogger(__name__)

GOOGLE_AI_PROVIDERS = {"google", "google_ai", "google_ai_studio", "gemini"}
GOOGLE_TOOL_RESULT_FINAL_INSTRUCTION = (
    "Сформулируй короткий ответ клиенту по результату функции. "
    "Не вызывай новые функции и не добавляй факты, которых нет в истории или результате функции."
)


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


@dataclass(slots=True)
class LLMTurnResult:
    text: str | None
    tool_calls: list[ToolCall]
    error_type: str | None = None
    retryable: bool = False
    usage: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None
    latency_ms: int | None = None


class OpenAIService:
    _provider_rate_limit_lock = threading.Lock()
    _provider_last_request_at: dict[str, float] = {}

    def __init__(self, settings) -> None:
        self.provider = settings.llm_provider.lower()
        self.model = settings.openai_model
        self.openai_api_key = settings.openai_api_key
        self.kie_api_key = settings.kie_api_key
        self.kie_api_base_url = settings.kie_api_base_url.rstrip("/")
        self.kie_chat_model_path = settings.kie_chat_model_path
        self.kie_reasoning_effort = settings.kie_reasoning_effort
        self.kie_temperature = settings.kie_temperature
        self.kie_top_p = settings.kie_top_p
        self.kie_parallel_tool_calls = settings.kie_parallel_tool_calls
        self.kie_stream = settings.kie_stream
        self.kie_http_connect_timeout_seconds = settings.kie_http_connect_timeout_seconds
        self.kie_http_read_timeout_seconds = settings.kie_http_read_timeout_seconds
        self.kie_retry_max_attempts = settings.kie_retry_max_attempts
        self.kie_retry_total_timeout_seconds = settings.kie_retry_total_timeout_seconds
        self.kie_enable_web_search = settings.kie_enable_web_search
        self.google_ai_api_key = settings.google_ai_api_key
        self.google_ai_base_url = settings.google_ai_base_url.rstrip("/")
        self.google_ai_model = settings.google_ai_model
        self.google_ai_reasoning_effort = settings.google_ai_reasoning_effort
        self.google_ai_temperature = settings.google_ai_temperature
        self.google_ai_top_p = settings.google_ai_top_p
        self.google_ai_stream = settings.google_ai_stream
        self.google_ai_http_connect_timeout_seconds = settings.google_ai_http_connect_timeout_seconds
        self.google_ai_http_read_timeout_seconds = settings.google_ai_http_read_timeout_seconds
        self.google_ai_retry_max_attempts = settings.google_ai_retry_max_attempts
        self.google_ai_retry_total_timeout_seconds = settings.google_ai_retry_total_timeout_seconds
        self.google_ai_min_request_interval_seconds = settings.google_ai_min_request_interval_seconds
        self.google_ai_rate_limit_retry_delay_seconds = settings.google_ai_rate_limit_retry_delay_seconds
        self.audit_logger = LLMAuditLogger(
            enabled=settings.llm_audit_log_enabled,
            path=settings.llm_audit_log_path,
            max_entries=settings.llm_audit_log_max_entries,
            usd_to_rub=settings.llm_cost_usd_to_rub,
        )
        self.llm_cost_usd_to_rub = settings.llm_cost_usd_to_rub

        self.enabled = self._is_enabled()
        self.client = None
        if self.provider == "openai" and self.openai_api_key:
            self.client = OpenAI(api_key=self.openai_api_key)

    def generate_reply(self, customer_text: str, transcript: str) -> str | None:
        if not self.enabled:
            return None
        messages = build_llm_messages(
            transcript=trim_text(transcript),
            customer_text=customer_text,
            product_lookup_result=None,
        )
        turn = self.run_messages(messages=messages)
        return turn.text

    def run_messages(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
    ) -> LLMTurnResult:
        if not self.enabled:
            return LLMTurnResult(text=None, tool_calls=[])

        if self.provider == "kie":
            return self._run_via_kie(messages=messages, tools=tools, tool_choice=tool_choice)
        if self.provider in GOOGLE_AI_PROVIDERS:
            return self._run_via_google_ai_studio(messages=messages, tools=tools, tool_choice=tool_choice)
        return self._run_via_openai(messages=messages, tools=tools, tool_choice=tool_choice)

    def _is_enabled(self) -> bool:
        if self.provider == "kie":
            return bool(self.kie_api_key)
        if self.provider in GOOGLE_AI_PROVIDERS:
            return bool(self.google_ai_api_key)
        return bool(self.openai_api_key)

    def _run_via_openai(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str,
    ) -> LLMTurnResult:
        if self.client is None:
            return LLMTurnResult(text=None, tool_calls=[])

        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception:  # pragma: no cover - external API failure path
            logger.exception("OpenAI request failed")
            return LLMTurnResult(text=None, tool_calls=[])

        try:
            message = response.choices[0].message
        except Exception:  # pragma: no cover - defensive
            return LLMTurnResult(text=None, tool_calls=[])

        tool_calls: list[ToolCall] = []
        for call in getattr(message, "tool_calls", []) or []:
            name = getattr(call.function, "name", "")
            arguments_raw = getattr(call.function, "arguments", "") or ""
            arguments = self._safe_json_loads(arguments_raw)
            call_id = getattr(call, "id", None)
            if name:
                tool_calls.append(ToolCall(name=name, arguments=arguments, call_id=call_id))

        content = getattr(message, "content", None)
        text = content.strip() if isinstance(content, str) and content.strip() else None
        return LLMTurnResult(text=text, tool_calls=tool_calls)

    def _run_via_kie(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str,
    ) -> LLMTurnResult:
        if not self.kie_api_key:
            return LLMTurnResult(text=None, tool_calls=[])

        url = f"{self.kie_api_base_url}{self.kie_chat_model_path}"
        return self._run_via_openai_compatible_http(
            provider_name="KIE",
            url=url,
            api_key=self.kie_api_key,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            model=None,
            reasoning_effort=self.kie_reasoning_effort,
            temperature=self.kie_temperature,
            top_p=self.kie_top_p,
            stream=self.kie_stream,
            parallel_tool_calls=self.kie_parallel_tool_calls,
            connect_timeout_seconds=self.kie_http_connect_timeout_seconds,
            read_timeout_seconds=self.kie_http_read_timeout_seconds,
            retry_max_attempts=self.kie_retry_max_attempts,
            retry_total_timeout_seconds=self.kie_retry_total_timeout_seconds,
            enable_web_search=self.kie_enable_web_search,
            min_request_interval_seconds=0.0,
            rate_limit_retry_delay_seconds=0.0,
        )

    def _run_via_google_ai_studio(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str,
    ) -> LLMTurnResult:
        if not self.google_ai_api_key:
            return LLMTurnResult(text=None, tool_calls=[])

        url = f"{self.google_ai_base_url}/chat/completions"
        return self._run_via_openai_compatible_http(
            provider_name="Google AI Studio",
            url=url,
            api_key=self.google_ai_api_key,
            messages=self._prepare_messages_for_google(messages),
            tools=tools,
            tool_choice=tool_choice,
            model=self.google_ai_model,
            reasoning_effort=self.google_ai_reasoning_effort,
            temperature=self.google_ai_temperature,
            top_p=self.google_ai_top_p,
            stream=self.google_ai_stream,
            parallel_tool_calls=None,
            connect_timeout_seconds=self.google_ai_http_connect_timeout_seconds,
            read_timeout_seconds=self.google_ai_http_read_timeout_seconds,
            retry_max_attempts=self.google_ai_retry_max_attempts,
            retry_total_timeout_seconds=self.google_ai_retry_total_timeout_seconds,
            enable_web_search=False,
            min_request_interval_seconds=self.google_ai_min_request_interval_seconds,
            rate_limit_retry_delay_seconds=self.google_ai_rate_limit_retry_delay_seconds,
        )

    @classmethod
    def _prepare_messages_for_google(cls, messages: list[dict]) -> list[dict]:
        prepared = cls._merge_system_messages_for_google(messages)
        return cls._append_google_final_instruction_after_tool_result(prepared)

    @staticmethod
    def _merge_system_messages_for_google(messages: list[dict]) -> list[dict]:
        """Google's OpenAI-compatible bridge maps only one systemInstruction reliably."""
        system_parts: list[str] = []
        non_system_messages: list[dict] = []
        for message in messages:
            if message.get("role") == "system":
                content = message.get("content")
                if content:
                    system_parts.append(str(content))
                continue
            non_system_messages.append(message)

        if not system_parts:
            return messages

        merged_system = {
            "role": "system",
            "content": "\n\n---\n\n".join(system_parts),
        }
        return [merged_system, *non_system_messages]

    @staticmethod
    def _append_google_final_instruction_after_tool_result(messages: list[dict]) -> list[dict]:
        """Keep tool results chronological and avoid Google's final functionResponse-only 400."""
        if not messages or messages[-1].get("role") != "tool":
            return messages

        return [
            *messages,
            {
                "role": "user",
                "content": GOOGLE_TOOL_RESULT_FINAL_INSTRUCTION,
            },
        ]

    def _run_via_openai_compatible_http(
        self,
        *,
        provider_name: str,
        url: str,
        api_key: str,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str,
        model: str | None,
        reasoning_effort: str,
        temperature: float,
        top_p: float,
        stream: bool,
        parallel_tool_calls: bool | None,
        connect_timeout_seconds: int,
        read_timeout_seconds: int,
        retry_max_attempts: int,
        retry_total_timeout_seconds: int,
        enable_web_search: bool,
        min_request_interval_seconds: float = 0.0,
        rate_limit_retry_delay_seconds: float = 0.0,
    ) -> LLMTurnResult:
        payload_messages = [self._format_kie_message(msg) for msg in messages]
        payload: dict[str, Any] = {
            "messages": payload_messages,
            "reasoning_effort": reasoning_effort,
            "temperature": temperature,
            "top_p": top_p,
            "stream": stream,
        }
        if model:
            payload["model"] = model
        if parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = parallel_tool_calls
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if enable_web_search:
            payload.setdefault("tools", [])
            payload["tools"] = [*payload["tools"], {"type": "web_search"}]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        started_at = time.monotonic()
        last_error_type = "provider_error"
        last_retryable = True
        for attempt in range(1, max(1, retry_max_attempts) + 1):
            self._throttle_provider_request(
                provider_key=f"{provider_name}:{model or url}",
                min_interval_seconds=min_request_interval_seconds,
            )
            attempt_started_at = time.monotonic()
            http_status: int | None = None
            data: dict[str, Any] | None = None
            error_text: str | None = None
            try:
                timeout = httpx.Timeout(
                    connect=connect_timeout_seconds,
                    read=read_timeout_seconds,
                    write=connect_timeout_seconds,
                    pool=connect_timeout_seconds,
                )
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, headers=headers, json=payload)
                    http_status = response.status_code
                    response.raise_for_status()
                    data = response.json()
            except httpx.HTTPStatusError as exc:  # pragma: no cover - external API failure path
                status_code = exc.response.status_code
                http_status = status_code
                error_text = exc.response.text
                last_error_type = "rate_limit_or_quota" if status_code == 429 else f"http_{status_code}"
                last_retryable = status_code in {429, 500, 502, 503, 504}
                self._write_provider_audit(
                    provider_name=provider_name,
                    url=url,
                    payload=payload,
                    model=model,
                    attempt=attempt,
                    started_at=attempt_started_at,
                    http_status=http_status,
                    response_json=None,
                    error_type=last_error_type,
                    retryable=last_retryable,
                    error_text=error_text,
                    text=None,
                    tool_calls=[],
                )
                logger.warning("%s request failed with HTTP %s on attempt %s", provider_name, status_code, attempt)
                if self._should_retry_provider(
                    started_at=started_at,
                    attempt=attempt,
                    retryable=last_retryable,
                    retry_max_attempts=retry_max_attempts,
                    retry_total_timeout_seconds=retry_total_timeout_seconds,
                ):
                    self._sleep_before_provider_retry(
                        attempt=attempt,
                        error_type=last_error_type,
                        rate_limit_retry_delay_seconds=rate_limit_retry_delay_seconds,
                    )
                    continue
                return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=last_retryable)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:  # pragma: no cover - external API failure path
                last_error_type = "timeout" if isinstance(exc, httpx.TimeoutException) else "network_error"
                last_retryable = True
                error_text = str(exc)
                self._write_provider_audit(
                    provider_name=provider_name,
                    url=url,
                    payload=payload,
                    model=model,
                    attempt=attempt,
                    started_at=attempt_started_at,
                    http_status=http_status,
                    response_json=None,
                    error_type=last_error_type,
                    retryable=last_retryable,
                    error_text=error_text,
                    text=None,
                    tool_calls=[],
                )
                logger.warning("%s %s on attempt %s: %s", provider_name, last_error_type, attempt, exc)
                if self._should_retry_provider(
                    started_at=started_at,
                    attempt=attempt,
                    retryable=last_retryable,
                    retry_max_attempts=retry_max_attempts,
                    retry_total_timeout_seconds=retry_total_timeout_seconds,
                ):
                    self._sleep_before_provider_retry(
                        attempt=attempt,
                        error_type=last_error_type,
                        rate_limit_retry_delay_seconds=rate_limit_retry_delay_seconds,
                    )
                    continue
                return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=True)
            except Exception:  # pragma: no cover - external API failure path
                logger.exception("%s request failed", provider_name)
                self._write_provider_audit(
                    provider_name=provider_name,
                    url=url,
                    payload=payload,
                    model=model,
                    attempt=attempt,
                    started_at=attempt_started_at,
                    http_status=http_status,
                    response_json=data,
                    error_type="provider_error",
                    retryable=True,
                    error_text="unexpected provider exception",
                    text=None,
                    tool_calls=[],
                )
                return LLMTurnResult(text=None, tool_calls=[], error_type="provider_error", retryable=True)

            provider_error = self._extract_provider_error(data)
            if provider_error is not None:
                last_error_type, last_retryable = provider_error
                self._write_provider_audit(
                    provider_name=provider_name,
                    url=url,
                    payload=payload,
                    model=model,
                    attempt=attempt,
                    started_at=attempt_started_at,
                    http_status=http_status,
                    response_json=data,
                    error_type=last_error_type,
                    retryable=last_retryable,
                    error_text=None,
                    text=None,
                    tool_calls=[],
                )
                logger.warning("%s provider returned %s on attempt %s", provider_name, last_error_type, attempt)
                if self._should_retry_provider(
                    started_at=started_at,
                    attempt=attempt,
                    retryable=last_retryable,
                    retry_max_attempts=retry_max_attempts,
                    retry_total_timeout_seconds=retry_total_timeout_seconds,
                ):
                    self._sleep_before_provider_retry(
                        attempt=attempt,
                        error_type=last_error_type,
                        rate_limit_retry_delay_seconds=rate_limit_retry_delay_seconds,
                    )
                    continue
                return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=last_retryable)

            text = self._extract_kie_text(data)
            tool_calls = self._extract_kie_tool_calls(data)
            if not text and not tool_calls:
                last_error_type = "empty_response"
                last_retryable = True
                self._write_provider_audit(
                    provider_name=provider_name,
                    url=url,
                    payload=payload,
                    model=model,
                    attempt=attempt,
                    started_at=attempt_started_at,
                    http_status=http_status,
                    response_json=data,
                    error_type=last_error_type,
                    retryable=last_retryable,
                    error_text=None,
                    text=None,
                    tool_calls=[],
                )
                logger.warning("%s provider returned empty response on attempt %s", provider_name, attempt)
                if self._should_retry_provider(
                    started_at=started_at,
                    attempt=attempt,
                    retryable=last_retryable,
                    retry_max_attempts=retry_max_attempts,
                    retry_total_timeout_seconds=retry_total_timeout_seconds,
                ):
                    self._sleep_before_provider_retry(
                        attempt=attempt,
                        error_type=last_error_type,
                        rate_limit_retry_delay_seconds=rate_limit_retry_delay_seconds,
                    )
                    continue
                return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=last_retryable)
            usage = extract_usage_stats(data)
            cost = estimate_cost(
                provider=self.provider,
                model=model,
                usage=usage,
                usd_to_rub=self.llm_cost_usd_to_rub,
            )
            latency_ms = self._latency_ms(attempt_started_at)
            self._write_provider_audit(
                provider_name=provider_name,
                url=url,
                payload=payload,
                model=model,
                attempt=attempt,
                started_at=attempt_started_at,
                http_status=http_status,
                response_json=data,
                error_type=None,
                retryable=False,
                error_text=None,
                text=text,
                tool_calls=tool_calls,
                latency_ms=latency_ms,
                usage=usage_to_dict(usage),
                cost=cost_to_dict(cost),
            )
            return LLMTurnResult(
                text=text,
                tool_calls=tool_calls,
                usage=usage_to_dict(usage),
                cost=cost_to_dict(cost),
                latency_ms=latency_ms,
            )

        return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=last_retryable)

    def _should_retry_kie(self, started_at: float, attempt: int, retryable: bool) -> bool:
        return self._should_retry_provider(
            started_at=started_at,
            attempt=attempt,
            retryable=retryable,
            retry_max_attempts=self.kie_retry_max_attempts,
            retry_total_timeout_seconds=self.kie_retry_total_timeout_seconds,
        )

    @staticmethod
    def _should_retry_provider(
        *,
        started_at: float,
        attempt: int,
        retryable: bool,
        retry_max_attempts: int,
        retry_total_timeout_seconds: int,
    ) -> bool:
        if not retryable:
            return False
        if attempt >= max(1, retry_max_attempts):
            return False
        return (time.monotonic() - started_at) < retry_total_timeout_seconds

    @staticmethod
    def _sleep_before_retry(attempt: int) -> None:
        delay = min(40.0, 2.0 * (2 ** (attempt - 1))) + random.uniform(0, 2)
        time.sleep(delay)

    @classmethod
    def _throttle_provider_request(cls, *, provider_key: str, min_interval_seconds: float) -> None:
        if min_interval_seconds <= 0:
            return

        with cls._provider_rate_limit_lock:
            now = time.monotonic()
            last_request_at = cls._provider_last_request_at.get(provider_key)
            if last_request_at is not None:
                wait_seconds = min_interval_seconds - (now - last_request_at)
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                    now = time.monotonic()
            cls._provider_last_request_at[provider_key] = now

    @staticmethod
    def _sleep_before_provider_retry(
        *,
        attempt: int,
        error_type: str | None,
        rate_limit_retry_delay_seconds: float,
    ) -> None:
        if error_type == "rate_limit_or_quota" and rate_limit_retry_delay_seconds > 0:
            time.sleep(rate_limit_retry_delay_seconds + random.uniform(0, 2))
            return

        OpenAIService._sleep_before_retry(attempt)

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return int((time.monotonic() - started_at) * 1000)

    def _write_provider_audit(
        self,
        *,
        provider_name: str,
        url: str,
        payload: dict[str, Any],
        model: str | None,
        attempt: int,
        started_at: float,
        http_status: int | None,
        response_json: dict[str, Any] | None,
        error_type: str | None,
        retryable: bool,
        error_text: str | None,
        text: str | None,
        tool_calls: list[ToolCall],
        latency_ms: int | None = None,
        usage: dict[str, Any] | None = None,
        cost: dict[str, Any] | None = None,
    ) -> None:
        duration_ms = latency_ms if latency_ms is not None else self._latency_ms(started_at)
        self.audit_logger.write(
            {
                "provider": self.provider,
                "provider_name": provider_name,
                "model": model,
                "endpoint": url,
                "attempt": attempt,
                "status": "error" if error_type else "success",
                "http_status": http_status,
                "duration_ms": duration_ms,
                "usage": usage or usage_to_dict(extract_usage_stats(response_json)),
                "cost": cost
                or cost_to_dict(
                    estimate_cost(
                        provider=self.provider,
                        model=model,
                        usage=extract_usage_stats(response_json),
                        usd_to_rub=self.llm_cost_usd_to_rub,
                    )
                ),
                "error": {
                    "type": error_type,
                    "retryable": retryable,
                    "message": error_text,
                }
                if error_type or error_text
                else None,
                "summary": {
                    "response_text_preview": (text or "")[:500],
                    "tool_calls_count": len(tool_calls),
                    "tool_calls": [
                        {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
                        for call in tool_calls
                    ],
                },
                "request": {
                    "headers": {"Authorization": "<redacted>", "Content-Type": "application/json"},
                    "json": payload,
                },
                "response": response_json,
            }
        )

    def _extract_provider_error(self, data: dict) -> tuple[str, bool] | None:
        provider_status = str(data.get("status") or data.get("state") or "").strip().lower()
        provider_code = self._extract_provider_code(data)
        if provider_code == 429:
            return "rate_limit_or_quota", True
        if provider_code is not None and provider_code >= 500:
            return f"provider_{provider_code}", True
        if provider_status in {"failure", "failed", "error"}:
            return ("provider_error", True)

        for text in self._iter_error_texts(data):
            normalized = text.lower()
            if (
                "you've hit your limit" in normalized
                or "you have hit your limit" in normalized
                or "please try again later" in normalized
                or "rate limit" in normalized
                or "quota" in normalized
            ):
                return "rate_limit_or_quota", True
            if "timeout" in normalized or "timed out" in normalized:
                return "timeout", True
            if "server exception" in normalized or "server error" in normalized:
                return "provider_500", True
        return None

    def _iter_error_texts(self, value: Any):
        if isinstance(value, str):
            if value.strip():
                yield value.strip()
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"message", "error", "error_message", "msg", "content", "detail", "status", "result"}:
                    yield from self._iter_error_texts(item)
                elif isinstance(item, (dict, list)):
                    yield from self._iter_error_texts(item)
            return
        if isinstance(value, list):
            for item in value:
                yield from self._iter_error_texts(item)

    @staticmethod
    def _extract_provider_code(data: dict) -> int | None:
        for key in ("error_code", "code", "status_code"):
            value = data.get(key)
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue

        error = data.get("error")
        if isinstance(error, dict):
            for key in ("code", "status_code"):
                value = error.get(key)
                try:
                    if value is not None:
                        return int(value)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _extract_kie_text(data: dict) -> str | None:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

        if isinstance(content, str):
            stripped = content.strip()
            return stripped or None

        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                text_value = part.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    text_parts.append(text_value.strip())
            if text_parts:
                return "\n".join(text_parts)
        return None

    def _extract_kie_tool_calls(self, data: dict) -> list[ToolCall]:
        try:
            raw_calls = data["choices"][0]["message"].get("tool_calls", [])
        except (KeyError, IndexError, TypeError, AttributeError):
            return []

        parsed: list[ToolCall] = []
        for call in raw_calls or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            arguments_raw = function.get("arguments", "")
            if isinstance(arguments_raw, dict):
                arguments = arguments_raw
            else:
                arguments = self._safe_json_loads(str(arguments_raw or ""))
            parsed.append(ToolCall(name=name, arguments=arguments, call_id=call.get("id")))
        return parsed

    @staticmethod
    def _safe_json_loads(value: str) -> dict[str, Any]:
        if not value:
            return {}
        try:
            payload = loads(value)
        except JSONDecodeError:
            logger.warning("Failed to decode tool call arguments: %s", value)
            return {}
        if isinstance(payload, dict):
            return payload
        return {"value": payload}

    @staticmethod
    def _format_kie_message(message: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message["role"]}
        if "tool_call_id" in message and message["tool_call_id"]:
            payload["tool_call_id"] = message["tool_call_id"]
        if "name" in message and message["name"]:
            payload["name"] = message["name"]
        if "tool_calls" in message and message["tool_calls"]:
            payload["tool_calls"] = message["tool_calls"]

        content = message.get("content")
        if isinstance(content, list):
            payload["content"] = content
        elif isinstance(content, str) and content:
            payload["content"] = content
        else:
            payload["content"] = ""
        return payload

    @staticmethod
    def build_assistant_tool_call_message(tool_calls: list[ToolCall]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in tool_calls
            ],
        }

    @staticmethod
    def build_tool_result_message(
        *,
        tool_call_id: str | None,
        result: dict[str, Any],
        name: str | None = None,
    ) -> dict[str, Any]:
        content = dumps(result, ensure_ascii=False)
        message: dict[str, Any]
        if tool_call_id:
            message = {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        else:
            message = {"role": "tool", "content": content}
        if name:
            message["name"] = name
        return message
