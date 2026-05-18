from __future__ import annotations

import logging
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


class OpenAIService:
    def __init__(self, settings) -> None:
        self.provider = settings.llm_provider.lower()
        self.model = settings.openai_model
        self.openai_api_key = settings.openai_api_key
        self.kie_api_key = settings.kie_api_key
        self.kie_api_base_url = settings.kie_api_base_url.rstrip("/")
        self.kie_chat_model_path = settings.kie_chat_model_path
        self.kie_reasoning_effort = settings.kie_reasoning_effort
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

        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception:  # pragma: no cover - external API failure path
            logger.exception("KIE request failed")
            return LLMTurnResult(text=None, tool_calls=[])

        text = self._extract_kie_text(data)
        tool_calls = self._extract_kie_tool_calls(data)
        return LLMTurnResult(text=text, tool_calls=tool_calls)

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
            payload["content"] = [{"type": "text", "text": content}]
        else:
            payload["content"] = []
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
