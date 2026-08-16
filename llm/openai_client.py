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


logger = logging.getLogger(__name__)

GOOGLE_AI_PROVIDERS = {"google", "google_ai", "google_ai_studio", "gemini"}
KAIGO_PROVIDERS = {"kaigo", "kaigo_codex", "codex_text"}

KAIGO_PROTOCOL_TEMPLATE = """
ТЕХНИЧЕСКИЙ ПРОТОКОЛ ОТВЕТА
Для этого канала каждый твой ответ должен быть ровно одним JSON-объектом без markdown, пояснений и текста до или после JSON.

Если клиенту можно ответить без функции:
{{"type":"assistant","text":"готовый естественный ответ клиенту"}}

Если нужна функция:
{{"type":"tool_call","name":"имя функции","arguments":{{...}}}}

За один ответ вызывай не более одной функции. После результата функции ты получишь обновлённую полную историю и снова выберешь: ответить клиенту или вызвать следующую функцию.
Нельзя писать, что функция выполнена, пока её результата нет в истории. Нельзя вызывать функции, которых нет ниже.

ДОСТУПНЫЕ ФУНКЦИИ
{tools_json}
""".strip()

KAIGO_PROTOCOL_CORRECTION = (
    "Предыдущий ответ нарушил обязательный JSON-формат или содержал недопустимый вызов. "
    "Верни только один корректный JSON-объект по техническому протоколу."
)


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None
    thought_signature: str | None = None


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
        self.kaigo_api_key = settings.kaigo_api_key
        self.kaigo_api_url = settings.kaigo_api_url
        self.kaigo_model = settings.kaigo_model
        self.kaigo_reasoning_effort = settings.kaigo_reasoning_effort
        self.kaigo_http_connect_timeout_seconds = settings.kaigo_http_connect_timeout_seconds
        self.kaigo_http_read_timeout_seconds = settings.kaigo_http_read_timeout_seconds
        self.kaigo_retry_max_attempts = settings.kaigo_retry_max_attempts
        self.kaigo_retry_total_timeout_seconds = settings.kaigo_retry_total_timeout_seconds
        self.kaigo_min_request_interval_seconds = settings.kaigo_min_request_interval_seconds
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

    def run_messages(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
    ) -> LLMTurnResult:
        if not self.enabled:
            return LLMTurnResult(text=None, tool_calls=[])

        if self.provider == "kie":
            return self._run_via_kie(messages=messages, tools=tools, tool_choice=tool_choice)
        if self.provider in GOOGLE_AI_PROVIDERS:
            return self._run_via_google_ai_studio(messages=messages, tools=tools, tool_choice=tool_choice)
        if self.provider in KAIGO_PROVIDERS:
            return self._run_via_kaigo(messages=messages, tools=tools)
        return self._run_via_openai(messages=messages, tools=tools, tool_choice=tool_choice)

    def _is_enabled(self) -> bool:
        if self.provider == "kie":
            return bool(self.kie_api_key)
        if self.provider in GOOGLE_AI_PROVIDERS:
            return bool(self.google_ai_api_key)
        if self.provider in KAIGO_PROVIDERS:
            return bool(self.kaigo_api_key)
        return bool(self.openai_api_key)

    def _run_via_kaigo(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> LLMTurnResult:
        if not self.kaigo_api_key:
            return LLMTurnResult(text=None, tool_calls=[])

        system_prompt, prompt = self._prepare_kaigo_prompt(messages=messages, tools=tools)
        allowed_tools = self._kaigo_allowed_tools(tools)
        started_at = time.monotonic()
        protocol_correction_used = False
        last_error_type: str | None = None
        last_retryable = False

        timeout = httpx.Timeout(
            self.kaigo_http_read_timeout_seconds,
            connect=self.kaigo_http_connect_timeout_seconds,
        )
        with httpx.Client(timeout=timeout) as client:
            for attempt in range(1, max(1, self.kaigo_retry_max_attempts) + 1):
                self._throttle_provider_request(
                    provider_key=f"kaigo:{self.kaigo_model}",
                    min_interval_seconds=self.kaigo_min_request_interval_seconds,
                )
                request_prompt = prompt
                if protocol_correction_used:
                    request_prompt = f"{prompt}\n\n{KAIGO_PROTOCOL_CORRECTION}"
                payload = {
                    "model": self.kaigo_model,
                    "reasoning_effort": self.kaigo_reasoning_effort,
                    "system_prompt": system_prompt,
                    "prompt": request_prompt,
                }
                request_started_at = time.monotonic()
                try:
                    response = client.post(
                        self.kaigo_api_url,
                        headers={
                            "Authorization": f"Bearer {self.kaigo_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                except httpx.TimeoutException as exc:
                    last_error_type = "timeout"
                    last_retryable = True
                    self._write_provider_audit(
                        provider_name="Kaigo Codex Text API",
                        url=self.kaigo_api_url,
                        payload=payload,
                        model=self.kaigo_model,
                        attempt=attempt,
                        started_at=request_started_at,
                        http_status=None,
                        response_json=None,
                        error_type=last_error_type,
                        retryable=True,
                        error_text=str(exc),
                        text=None,
                        tool_calls=[],
                    )
                    if not self._should_retry_provider(
                        retryable=True,
                        attempt=attempt,
                        started_at=started_at,
                        retry_max_attempts=self.kaigo_retry_max_attempts,
                        retry_total_timeout_seconds=self.kaigo_retry_total_timeout_seconds,
                    ):
                        break
                    self._sleep_before_retry(attempt)
                    continue
                except httpx.HTTPError as exc:
                    last_error_type = "network_error"
                    last_retryable = True
                    self._write_provider_audit(
                        provider_name="Kaigo Codex Text API",
                        url=self.kaigo_api_url,
                        payload=payload,
                        model=self.kaigo_model,
                        attempt=attempt,
                        started_at=request_started_at,
                        http_status=None,
                        response_json=None,
                        error_type=last_error_type,
                        retryable=True,
                        error_text=str(exc),
                        text=None,
                        tool_calls=[],
                    )
                    if not self._should_retry_provider(
                        retryable=True,
                        attempt=attempt,
                        started_at=started_at,
                        retry_max_attempts=self.kaigo_retry_max_attempts,
                        retry_total_timeout_seconds=self.kaigo_retry_total_timeout_seconds,
                    ):
                        break
                    self._sleep_before_retry(attempt)
                    continue

                data = self._safe_response_json(response)
                http_status = getattr(response, "status_code", None)
                if not 200 <= int(http_status or 0) < 300:
                    last_error_type, last_retryable = self._kaigo_http_error(data, http_status)
                    self._write_provider_audit(
                        provider_name="Kaigo Codex Text API",
                        url=self.kaigo_api_url,
                        payload=payload,
                        model=self.kaigo_model,
                        attempt=attempt,
                        started_at=request_started_at,
                        http_status=http_status,
                        response_json=data,
                        error_type=last_error_type,
                        retryable=last_retryable,
                        error_text=self._kaigo_error_message(data, response),
                        text=None,
                        tool_calls=[],
                    )
                    if not self._should_retry_provider(
                        retryable=last_retryable,
                        attempt=attempt,
                        started_at=started_at,
                        retry_max_attempts=self.kaigo_retry_max_attempts,
                        retry_total_timeout_seconds=self.kaigo_retry_total_timeout_seconds,
                    ):
                        break
                    self._sleep_before_kaigo_retry(response=response, attempt=attempt)
                    continue

                raw_output = data.get("output_text")
                raw_output = raw_output.strip() if isinstance(raw_output, str) else ""
                text, tool_calls, protocol_error = self._parse_kaigo_output(
                    raw_output,
                    allowed_tools=allowed_tools,
                )
                usage = self._kaigo_usage(data)
                latency_ms = self._optional_positive_int(data.get("duration_ms")) or self._latency_ms(
                    request_started_at
                )
                if protocol_error:
                    last_error_type = "invalid_tool_protocol"
                    last_retryable = not protocol_correction_used
                    self._write_provider_audit(
                        provider_name="Kaigo Codex Text API",
                        url=self.kaigo_api_url,
                        payload=payload,
                        model=self.kaigo_model,
                        attempt=attempt,
                        started_at=request_started_at,
                        http_status=http_status,
                        response_json=data,
                        error_type=last_error_type,
                        retryable=last_retryable,
                        error_text=protocol_error,
                        text=None,
                        tool_calls=[],
                        latency_ms=latency_ms,
                        usage=usage,
                    )
                    if protocol_correction_used or attempt >= max(1, self.kaigo_retry_max_attempts):
                        break
                    protocol_correction_used = True
                    continue

                self._write_provider_audit(
                    provider_name="Kaigo Codex Text API",
                    url=self.kaigo_api_url,
                    payload=payload,
                    model=self.kaigo_model,
                    attempt=attempt,
                    started_at=request_started_at,
                    http_status=http_status,
                    response_json=data,
                    error_type=None,
                    retryable=False,
                    error_text=None,
                    text=text,
                    tool_calls=tool_calls,
                    latency_ms=latency_ms,
                    usage=usage,
                )
                return LLMTurnResult(
                    text=text,
                    tool_calls=tool_calls,
                    usage=usage,
                    cost=cost_to_dict(
                        estimate_cost(
                            provider=self.provider,
                            model=self.kaigo_model,
                            usage=extract_usage_stats({"usage": usage}),
                            usd_to_rub=self.llm_cost_usd_to_rub,
                        )
                    ),
                    latency_ms=latency_ms,
                )

        return LLMTurnResult(
            text=None,
            tool_calls=[],
            error_type=last_error_type or "provider_error",
            retryable=last_retryable,
        )

    @staticmethod
    def _prepare_kaigo_prompt(
        *,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> tuple[str, str]:
        system_parts = [
            str(message.get("content") or "").strip()
            for message in messages
            if message.get("role") == "system" and str(message.get("content") or "").strip()
        ]
        dialog_messages = [message for message in messages if message.get("role") != "system"]
        tools_json = dumps(tools or [], ensure_ascii=False, separators=(",", ":"))
        protocol = KAIGO_PROTOCOL_TEMPLATE.format(tools_json=tools_json)
        system_prompt = "\n\n".join([*system_parts, protocol]).strip()
        prompt = (
            "ПОЛНАЯ ХРОНОЛОГИЧЕСКАЯ ИСТОРИЯ ДИАЛОГА В JSON\n"
            + dumps(dialog_messages, ensure_ascii=False, indent=2)
            + "\n\nОтветь на последнее актуальное сообщение клиента по системной инструкции."
        )
        return system_prompt, prompt

    @staticmethod
    def _kaigo_allowed_tools(tools: list[dict] | None) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for tool in tools or []:
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "").strip()
            if name:
                result[name] = function
        return result

    @classmethod
    def _parse_kaigo_output(
        cls,
        raw_output: str,
        *,
        allowed_tools: dict[str, dict[str, Any]],
    ) -> tuple[str | None, list[ToolCall], str | None]:
        try:
            envelope = loads(cls._strip_json_fence(raw_output))
        except (JSONDecodeError, TypeError):
            return None, [], "Ответ не является одним JSON-объектом."
        if not isinstance(envelope, dict):
            return None, [], "Корневое значение должно быть JSON-объектом."

        response_type = str(envelope.get("type") or "").strip()
        if response_type == "assistant":
            text = envelope.get("text")
            if not isinstance(text, str) or not text.strip():
                return None, [], "Для assistant требуется непустое поле text."
            return text.strip(), [], None

        if response_type != "tool_call":
            return None, [], "Поле type должно быть assistant или tool_call."
        name = str(envelope.get("name") or "").strip()
        function = allowed_tools.get(name)
        if function is None:
            return None, [], "Запрошена неизвестная или недоступная функция."
        arguments = envelope.get("arguments")
        if not isinstance(arguments, dict):
            return None, [], "Поле arguments должно быть JSON-объектом."
        required = ((function.get("parameters") or {}).get("required") or [])
        missing = [key for key in required if key not in arguments]
        if missing:
            return None, [], f"Не переданы обязательные аргументы: {', '.join(missing)}."
        return None, [ToolCall(name=name, arguments=arguments)], None

    @staticmethod
    def _strip_json_fence(value: str) -> str:
        stripped = value.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return stripped

    @staticmethod
    def _safe_response_json(response) -> dict[str, Any]:
        try:
            data = response.json()
        except (ValueError, JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _kaigo_usage(data: dict[str, Any]) -> dict[str, int]:
        raw = data.get("usage") or {}
        prompt_tokens = OpenAIService._optional_positive_int(raw.get("input_tokens")) or 0
        completion_tokens = OpenAIService._optional_positive_int(raw.get("output_tokens")) or 0
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    @staticmethod
    def _optional_positive_int(value: Any) -> int | None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number >= 0 else None

    @staticmethod
    def _kaigo_http_error(data: dict[str, Any], http_status: int | None) -> tuple[str, bool]:
        error = data.get("error") if isinstance(data, dict) else None
        provider_type = str(error.get("type") or "") if isinstance(error, dict) else ""
        if provider_type:
            error_type = provider_type
        else:
            error_type = f"http_{http_status}" if http_status else "provider_error"
        retryable = http_status in {429, 502, 503, 504} or error_type in {
            "busy",
            "rate_limited",
            "provider_error",
            "codex_unavailable",
            "timeout",
        }
        return error_type, retryable

    @staticmethod
    def _kaigo_error_message(data: dict[str, Any], response) -> str:
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        return str(getattr(response, "text", ""))[:500]

    @staticmethod
    def _sleep_before_kaigo_retry(*, response, attempt: int) -> None:
        retry_after = getattr(response, "headers", {}).get("Retry-After")
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            delay = min(30.0, 7.0 * attempt)
        time.sleep(max(0.0, min(delay, 30.0)))

    def _run_via_openai(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str | dict[str, Any],
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
        tool_choice: str | dict[str, Any],
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
        tool_choice: str | dict[str, Any],
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
        return cls._merge_system_messages_for_google(messages)

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

    def _run_via_openai_compatible_http(
        self,
        *,
        provider_name: str,
        url: str,
        api_key: str,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str | dict[str, Any],
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
        # AMIX product truth comes only from the two local tools. Provider web
        # search must never expand that boundary, including no-tool final turns.
        del enable_web_search

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
            extra_content = call.get("extra_content") or {}
            google_metadata = extra_content.get("google") if isinstance(extra_content, dict) else {}
            thought_signature = (
                google_metadata.get("thought_signature") if isinstance(google_metadata, dict) else None
            )
            parsed.append(
                ToolCall(
                    name=name,
                    arguments=arguments,
                    call_id=call.get("id"),
                    thought_signature=thought_signature if isinstance(thought_signature, str) else None,
                )
            )
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
        formatted_calls: list[dict[str, Any]] = []
        for call in tool_calls:
            formatted_call: dict[str, Any] = {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": dumps(call.arguments, ensure_ascii=False),
                },
            }
            if call.thought_signature:
                formatted_call["extra_content"] = {
                    "google": {"thought_signature": call.thought_signature}
                }
            formatted_calls.append(formatted_call)

        return {
            "role": "assistant",
            "content": "",
            "tool_calls": formatted_calls,
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
