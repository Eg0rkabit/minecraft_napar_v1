"""Optional model adapter. Disabled mode performs no network request."""
from typing import Any


class Decision:
    def __init__(self, text: str = '', tool_calls: list[dict[str, Any]] | None = None, tokens: int = 0,
                 assistant_message: dict[str, Any] | None = None):
        self.text, self.tool_calls = text, tool_calls or []
        self.tokens = tokens
        self.assistant_message = assistant_message


class DisabledBackend:
    async def decide(self, messages, tools, *, model, max_tokens):
        return Decision('Мозг выключен: задай NAPAR_LLM_BACKEND=openai после настройки ключа.')


def completion_options(model: str, max_tokens: int) -> dict[str, Any]:
    # Preserve legacy model compatibility; GPT-5 counts reasoning in this cap.
    name = model.rsplit('/', 1)[-1]
    if name == 'gpt-5' or name.startswith('gpt-5-2025-'):
        return {'max_completion_tokens': max_tokens, 'reasoning_effort': 'minimal'}
    if name == 'gemini-4-argon':
        return {'max_tokens': max_tokens, 'reasoning_effort': 'low'}
    return {'max_tokens': max_tokens}


class OpenAIBackend:
    def __init__(self, settings):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.llm_api_key.get_secret_value(),
                                  base_url=settings.llm_base_url.rstrip('/'), timeout=60, max_retries=0)

    async def decide(self, messages, tools, *, model, max_tokens):
        response = await self.client.chat.completions.create(
            model=model, messages=messages, tools=tools, tool_choice='auto',
            parallel_tool_calls=False, **completion_options(model, max_tokens))
        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            calls.append({'id': call.id, 'name': call.function.name, 'arguments': call.function.arguments})
        # Keep provider metadata (including Gemini tool signatures) verbatim in the next turn.
        assistant = {'role': 'assistant', 'content': message.content or None}
        if message.tool_calls:
            assistant['tool_calls'] = [call.model_dump(exclude_none=True) for call in message.tool_calls]
        assistant.update(message.model_extra or {})
        return Decision(message.content or '', calls, response.usage.total_tokens if response.usage else 0,
                        assistant_message=assistant)

    async def close(self):
        await self.client.close()


def make_backend(settings):
    if settings.llm_backend == 'openai':
        if not settings.llm_api_key.get_secret_value():
            raise ValueError('NAPAR_LLM_API_KEY is required when NAPAR_LLM_BACKEND=openai')
        return OpenAIBackend(settings)
    return DisabledBackend()
