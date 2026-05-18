from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from json import JSONDecodeError, dumps, loads
from typing import Any

import httpx
from openai import OpenAI

from llm.prompts import build_llm_messages
from llm.tools import trim_text


logger = logging.getLogger(__name__)


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


class OpenAIService:
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
        return self._run_via_openai(messages=messages, tools=tools, tool_choice=tool_choice)

    def _is_enabled(self) -> bool:
        if self.provider == "kie":
            return bool(self.kie_api_key)
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
        payload_messages = [self._format_kie_message(msg) for msg in messages]
        payload: dict[str, Any] = {
            "messages": payload_messages,
            "reasoning_effort": self.kie_reasoning_effort,
            "temperature": self.kie_temperature,
            "top_p": self.kie_top_p,
            "parallel_tool_calls": self.kie_parallel_tool_calls,
            "stream": self.kie_stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if self.kie_enable_web_search:
            payload.setdefault("tools", [])
            payload["tools"] = [*payload["tools"], {"type": "web_search"}]

        headers = {
            "Authorization": f"Bearer {self.kie_api_key}",
            "Content-Type": "application/json",
        }

        started_at = time.monotonic()
        last_error_type = "provider_error"
        last_retryable = True
        for attempt in range(1, max(1, self.kie_retry_max_attempts) + 1):
            try:
                timeout = httpx.Timeout(
                    connect=self.kie_http_connect_timeout_seconds,
                    read=self.kie_http_read_timeout_seconds,
                    write=self.kie_http_connect_timeout_seconds,
                    pool=self.kie_http_connect_timeout_seconds,
                )
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
            except httpx.HTTPStatusError as exc:  # pragma: no cover - external API failure path
                status_code = exc.response.status_code
                last_error_type = "rate_limit_or_quota" if status_code == 429 else f"http_{status_code}"
                last_retryable = status_code in {429, 500, 502, 503, 504}
                logger.warning("KIE request failed with HTTP %s on attempt %s", status_code, attempt)
                if self._should_retry_kie(started_at, attempt, last_retryable):
                    self._sleep_before_retry(attempt)
                    continue
                return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=last_retryable)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:  # pragma: no cover - external API failure path
                last_error_type = "timeout" if isinstance(exc, httpx.TimeoutException) else "network_error"
                last_retryable = True
                logger.warning("KIE %s on attempt %s: %s", last_error_type, attempt, exc)
                if self._should_retry_kie(started_at, attempt, last_retryable):
                    self._sleep_before_retry(attempt)
                    continue
                return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=True)
            except Exception:  # pragma: no cover - external API failure path
                logger.exception("KIE request failed")
                return LLMTurnResult(text=None, tool_calls=[], error_type="provider_error", retryable=True)

            provider_error = self._extract_provider_error(data)
            if provider_error is not None:
                last_error_type, last_retryable = provider_error
                logger.warning("KIE provider returned %s on attempt %s", last_error_type, attempt)
                if self._should_retry_kie(started_at, attempt, last_retryable):
                    self._sleep_before_retry(attempt)
                    continue
                return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=last_retryable)

            text = self._extract_kie_text(data)
            tool_calls = self._extract_kie_tool_calls(data)
            if not text and not tool_calls:
                last_error_type = "empty_response"
                last_retryable = True
                logger.warning("KIE provider returned empty response on attempt %s", attempt)
                if self._should_retry_kie(started_at, attempt, last_retryable):
                    self._sleep_before_retry(attempt)
                    continue
                return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=last_retryable)
            return LLMTurnResult(text=text, tool_calls=tool_calls)

        return LLMTurnResult(text=None, tool_calls=[], error_type=last_error_type, retryable=last_retryable)

    def _should_retry_kie(self, started_at: float, attempt: int, retryable: bool) -> bool:
        if not retryable:
            return False
        if attempt >= max(1, self.kie_retry_max_attempts):
            return False
        return (time.monotonic() - started_at) < self.kie_retry_total_timeout_seconds

    @staticmethod
    def _sleep_before_retry(attempt: int) -> None:
        delay = min(40.0, 2.0 * (2 ** (attempt - 1))) + random.uniform(0, 2)
        time.sleep(delay)

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
