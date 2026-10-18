import json

import httpx
import openai
import pytest

from napar.config import Settings
from napar.llm import OpenAIBackend


@pytest.mark.parametrize('model,expected', [
    ('openai/gpt-5', {'max_completion_tokens': 700, 'reasoning_effort': 'minimal'}),
    ('gpt-5', {'max_completion_tokens': 700, 'reasoning_effort': 'minimal'}),
    ('gpt-4o-mini', {'max_tokens': 700}),
])
async def test_model_options_on_wire(monkeypatch, model, expected):
    def respond(request):
        assert str(request.url) == 'https://api.proxyapi.ru/v1/chat/completions'
        body = json.loads(request.content)
        assert body['model'] == model
        assert body['parallel_tool_calls'] is False
        for key, value in expected.items():
            assert body[key] == value
        other = 'max_tokens' if 'max_completion_tokens' in expected else 'max_completion_tokens'
        assert other not in body
        return httpx.Response(200, json={
            'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': model,
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'call-check', 'type': 'function', 'function': {
                        'name': 'inspect', 'arguments': '{"target":"inventory"}'}}]}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
    original = openai.AsyncOpenAI
    monkeypatch.setattr(openai, 'AsyncOpenAI', lambda **kwargs: original(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    backend = OpenAIBackend(Settings(_env_file=None, bridge_token='x' * 40,
        llm_api_key='test-secret', llm_base_url='https://api.proxyapi.ru/v1'))
    try:
        result = await backend.decide([{'role': 'user', 'content': 'test'}], [], model=model, max_tokens=700)
        assert result.tokens == 15
        assert result.tool_calls == [{'id': 'call-check', 'name': 'inspect',
                                      'arguments': '{"target":"inventory"}'}]
    finally:
        await backend.close()
