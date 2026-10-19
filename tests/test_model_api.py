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
    ('gemini-4-argon', {'max_tokens': 700, 'reasoning_effort': 'low'}),
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


async def test_gemini_tool_metadata_survives_adapter(monkeypatch):
    wire_call = {'id': 'signed-tool', 'type': 'function',
                 'function': {'name': 'observe', 'arguments': '{}'},
                 'extra_content': {'google': {'thought_signature': 'opaque-signature'}}}
    def respond(request):
        return httpx.Response(200, json={
            'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': 'gemini-4-argon',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [wire_call],
                'reasoning_content': 'provider continuation metadata'}}]})
    original = openai.AsyncOpenAI
    monkeypatch.setattr(openai, 'AsyncOpenAI', lambda **kwargs: original(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    backend = OpenAIBackend(Settings(_env_file=None, bridge_token='x' * 40,
        llm_api_key='test-secret', llm_base_url='https://direct.beatapi.io/v1'))
    try:
        result = await backend.decide([{'role': 'user', 'content': 'test'}], [],
                                      model='gemini-4-argon', max_tokens=700)
        assert result.assistant_message['tool_calls'] == [wire_call]
        assert result.assistant_message['reasoning_content'] == 'provider continuation metadata'
    finally:
        await backend.close()
