import logging

import httpx
from openai import OpenAI

from llm.prompts import SYSTEM_PROMPT, build_user_prompt
from llm.tools import trim_text


logger = logging.getLogger(__name__)


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

        prompt = build_user_prompt(customer_text=customer_text, transcript=trim_text(transcript))

        if self.provider == "kie":
            return self._generate_via_kie(prompt)

        return self._generate_via_openai(prompt)

    def _is_enabled(self) -> bool:
        if self.provider == "kie":
            return bool(self.kie_api_key)
        return bool(self.openai_api_key)

    def _generate_via_openai(self, prompt: str) -> str | None:
        if self.client is None:
            return None

        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=prompt,
            )
        except Exception:  # pragma: no cover - external API failure path
            logger.exception("OpenAI request failed")
            return None

        output_text = getattr(response, "output_text", "")
        return output_text.strip() or None

    def _generate_via_kie(self, prompt: str) -> str | None:
        if not self.kie_api_key:
            return None

        url = f"{self.kie_api_base_url}{self.kie_chat_model_path}"
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": [{"type": "text", "text": SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                },
            ],
            "reasoning_effort": self.kie_reasoning_effort,
        }
        if self.kie_enable_web_search:
            payload["tools"] = [{"type": "web_search"}]

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
            return None

        return self._extract_kie_text(data)

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
