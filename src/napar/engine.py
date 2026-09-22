"""Bounded event loop around the optional model and validated tools."""
import json


SYSTEM = (
    "Ты напарник игрока в Minecraft. Говори по-русски, будь инициативным, но не выдумывай "
    "наблюдения и результат действий. Сначала наблюдай или вспоминай, если данных не хватает. "
    "У тебя есть один мир и ограниченный бюджет вызовов. Завершай цель только с доказательством "
    "успешного действия в этом ходе. Коротко объясняй игроку принятое решение."
)


class Engine:
    def __init__(self, settings, store, bridge, toolbox, backend):
        self.settings, self.store, self.bridge = settings, store, bridge
        self.toolbox, self.backend = toolbox, backend
        self.busy = False
        self.cancelled = False

    def stop(self):
        self.cancelled = True
        self.bridge.halt('Stopped by owner')

    def _context(self, user_text=''):
        world = self.bridge.world_id
        return [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps({
                'message': user_text,
                'world': world,
                'goals': self.store.goals(world) if world else [],
                'memories': self.store.recall(world, user_text) if world else [],
                'recent': self.store.recent(world) if world else [],
            }, ensure_ascii=False)},
        ]

    async def handle(self, user_text='', trigger='chat'):
        if self.busy:
            return {'status': 'busy', 'message': 'Уже выполняю предыдущую мысль.'}
        if not self.bridge.world_id:
            return {'status': 'offline', 'message': 'Игровой адаптер ещё не подключён.'}
        self.busy, self.cancelled = True, False
        evidence = set()
        messages = self._context(user_text)
        transcript = []
        try:
            for _ in range(self.settings.max_steps):
                if self.cancelled:
                    return {'status': 'cancelled', 'message': 'Остановлено владельцем.'}
                self.store.reserve_call(self.settings.max_calls_per_day)
                decision = await self.backend.decide(
                    messages, self.toolbox.specs(), model=self.settings.llm_model,
                    max_tokens=self.settings.max_output_tokens)
                if decision.text:
                    transcript.append(decision.text[:4000])
                if not decision.tool_calls:
                    break
                messages.append({
                    'role': 'assistant', 'content': decision.text or None,
                    'tool_calls': [
                        {'id': c['id'], 'type': 'function',
                         'function': {'name': c['name'], 'arguments': c['arguments']}}
                        for c in decision.tool_calls
                    ],
                })
                for call in decision.tool_calls:
                    if self.cancelled:
                        break
                    result = await self.toolbox.execute(call['name'], call['arguments'], evidence)
                    transcript.append(f"{call['name']}: {json.dumps(result, ensure_ascii=False)[:1000]}")
                    messages.append({
                        'role': 'tool', 'tool_call_id': call['id'],
                        'content': json.dumps(result, ensure_ascii=False),
                    })
            self.store.audit(self.bridge.world_id, 'reasoning', {'trigger': trigger, 'transcript': transcript})
            return {'status': 'completed', 'message': '\n'.join(transcript)[-6000:]}
        except ValueError as exc:
            return {'status': 'failed', 'message': str(exc)[:1000]}
        finally:
            self.busy = False
