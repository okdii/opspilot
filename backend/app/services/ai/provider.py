"""AI provider abstraction — Anthropic, OpenAI, Gemini.

Each provider returns (text, prompt_tokens, completion_tokens).
SDKs are imported lazily so the app starts even if a package is missing.
"""
from abc import ABC, abstractmethod


class BaseAIProvider(ABC):
    @abstractmethod
    async def complete(
        self, system: str, user: str, max_tokens: int = 4000
    ) -> tuple[str, int, int]:
        """Returns (response_text, prompt_tokens, completion_tokens)."""
        ...


class AnthropicProvider(BaseAIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def complete(self, system: str, user: str, max_tokens: int = 4000) -> tuple[str, int, int]:
        import anthropic  # noqa: PLC0415
        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        msg = await client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text, msg.usage.input_tokens, msg.usage.output_tokens


class OpenAIProvider(BaseAIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def complete(self, system: str, user: str, max_tokens: int = 4000) -> tuple[str, int, int]:
        import openai  # noqa: PLC0415
        client = openai.AsyncOpenAI(api_key=self.api_key)
        resp = await client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (
            resp.choices[0].message.content or "",
            resp.usage.prompt_tokens,
            resp.usage.completion_tokens,
        )


class GeminiProvider(BaseAIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def complete(self, system: str, user: str, max_tokens: int = 4000) -> tuple[str, int, int]:
        import google.generativeai as genai  # noqa: PLC0415
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model, system_instruction=system)
        resp = await model.generate_content_async(
            user, generation_config={"max_output_tokens": max_tokens}
        )
        pt = getattr(resp.usage_metadata, "prompt_token_count", 0) or 0
        ct = getattr(resp.usage_metadata, "candidates_token_count", 0) or 0
        return resp.text, pt, ct


async def get_provider(db) -> BaseAIProvider | None:
    """Return the configured AI provider instance, or None if disabled/unconfigured."""
    from sqlalchemy import select
    from app.models.other import Settings
    from app.core import crypto

    s = await db.scalar(select(Settings).where(Settings.id == 1))
    if not s or s.ai_provider == "disabled" or not s.ai_api_key_encrypted:
        return None

    api_key = crypto.decrypt(s.ai_api_key_encrypted)

    if s.ai_provider == "anthropic":
        return AnthropicProvider(api_key, s.ai_model)
    if s.ai_provider == "openai":
        return OpenAIProvider(api_key, s.ai_model)
    if s.ai_provider == "gemini":
        return GeminiProvider(api_key, s.ai_model)
    return None
