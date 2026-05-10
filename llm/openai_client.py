import logging

from openai import OpenAI

from llm.prompts import SYSTEM_PROMPT, build_user_prompt
from llm.tools import trim_text


logger = logging.getLogger(__name__)


class OpenAIService:
    def __init__(self, settings) -> None:
        self.model = settings.openai_model
        self.enabled = bool(settings.openai_api_key)
        self.client = OpenAI(api_key=settings.openai_api_key) if self.enabled else None

    def generate_reply(self, customer_text: str, transcript: str) -> str | None:
        if not self.enabled or self.client is None:
            return None

        prompt = build_user_prompt(customer_text=customer_text, transcript=trim_text(transcript))

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
