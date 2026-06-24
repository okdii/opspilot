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
        client = anthropic.AsyncAnthropic(api_key=self.api_key, timeout=30.0)
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
        client = openai.AsyncOpenAI(api_key=self.api_key, timeout=30.0)
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


class CustomProvider(BaseAIProvider):
    """OpenAI-compatible endpoint — LiteLLM, Ollama, vLLM, etc."""

    def __init__(self, base_url: str, model: str, api_key: str = "not-required") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or "not-required"

    async def complete(self, system: str, user: str, max_tokens: int = 4000) -> tuple[str, int, int]:
        import openai  # noqa: PLC0415
        client = openai.AsyncOpenAI(base_url=self.base_url, api_key=self.api_key, timeout=30.0)
        resp = await client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        pt = resp.usage.prompt_tokens if resp.usage else 0
        ct = resp.usage.completion_tokens if resp.usage else 0
        return resp.choices[0].message.content or "", pt, ct


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
    if not s or s.ai_provider == "disabled":
        return None

    # Custom provider only needs a base_url; API key is optional
    if s.ai_provider == "custom":
        if not s.ai_base_url:
            return None
        api_key = crypto.decrypt(s.ai_api_key_encrypted) if s.ai_api_key_encrypted else "not-required"
        return CustomProvider(s.ai_base_url, s.ai_model, api_key)

    # All other providers require an API key
    if not s.ai_api_key_encrypted:
        return None

    api_key = crypto.decrypt(s.ai_api_key_encrypted)

    if s.ai_provider == "anthropic":
        return AnthropicProvider(api_key, s.ai_model)
    if s.ai_provider == "openai":
        return OpenAIProvider(api_key, s.ai_model)
    if s.ai_provider == "gemini":
        return GeminiProvider(api_key, s.ai_model)
    return None
