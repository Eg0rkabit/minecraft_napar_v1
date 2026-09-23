"""Optional model adapter. Disabled mode performs no network request."""
from typing import Any


class Decision:
    def __init__(self, text: str = '', tool_calls: list[dict[str, Any]] | None = None, tokens: int = 0):
        self.text, self.tool_calls = text, tool_calls or []
        self.tokens = tokens


class DisabledBackend:
    async def decide(self, messages, tools, *, model, max_tokens):
        return Decision('Мозг выключен: задай NAPAR_LLM_BACKEND=openai после настройки ключа.')


class OpenAIBackend:
    def __init__(self, settings):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.llm_api_key.get_secret_value(),
                                  base_url=settings.llm_base_url.rstrip('/'), timeout=30, max_retries=0)

    async def decide(self, messages, tools, *, model, max_tokens):
        response = await self.client.chat.completions.create(
            model=model, messages=messages, tools=tools, tool_choice='auto',
            max_tokens=max_tokens, parallel_tool_calls=False)
        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            calls.append({'id': call.id, 'name': call.function.name, 'arguments': call.function.arguments})
        return Decision(message.content or '', calls, response.usage.total_tokens if response.usage else 0)

    async def close(self):
        await self.client.close()


def make_backend(settings):
    if settings.llm_backend == 'openai':
        if not settings.llm_api_key.get_secret_value():
            raise ValueError('NAPAR_LLM_API_KEY is required when NAPAR_LLM_BACKEND=openai')
        return OpenAIBackend(settings)
    return DisabledBackend()
