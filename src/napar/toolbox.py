import json

from .protocol import (EmptyArgs, FollowArgs, GoalArgs, GoalUpdateArgs, InspectArgs,
                       MoveArgs, RecallArgs, RememberArgs, SayArgs)

LOCAL = {
    'observe': (EmptyArgs, 'Read the latest compact observed state. No omniscient world access.'),
    'recall': (RecallArgs, 'Search persistent memories in the current world; empty query returns recent memories.'),
    'remember': (RememberArgs, 'Persist a useful fact, experience or promise with its evidence. Do not save guesses as facts.'),
    'create_goal': (GoalArgs, 'Record a goal and its observable success condition.'),
    'update_goal': (GoalUpdateArgs, 'Update an existing goal. Completion requires a successful action ID from this turn.'),
}
REMOTE = {
    'inspect': (InspectArgs, 'Actively inspect a sensor to resolve missing information.'),
    'move_to': (MoveArgs, 'Request navigation to a nearby point, at most 64 blocks away. Wait for the result.'),
    'follow_player': (FollowArgs, 'Follow a visible player for a bounded interval. The result describes progress, not a permanent promise.'),
    'look_at': (MoveArgs, 'Turn towards a position.'),
    'stop': (EmptyArgs, 'Request immediate cancellation of movement.'),
    'say': (SayArgs, 'Say a short Russian message in Minecraft chat.'),
}


class Toolbox:
    def __init__(self, bridge, store):
        self.bridge, self.store = bridge, store

    def specs(self):
        available = LOCAL | {k: v for k, v in REMOTE.items() if k in self.bridge.capabilities}
        return [{'type': 'function', 'function': {'name': name, 'description': desc,
                'strict': True, 'parameters': schema.model_json_schema()}}
                for name, (schema, desc) in available.items()]

    async def execute(self, name, raw_arguments, evidence):
        available = LOCAL | {k: v for k, v in REMOTE.items() if k in self.bridge.capabilities}
        if name not in available:
            return {'status': 'failed', 'detail': f'Unknown or unavailable tool: {name}'}
        try:
            args = available[name][0].model_validate_json(raw_arguments).model_dump()
            world = self.bridge.world_id
            if not world:
                raise ValueError('No world connected')
            if name == 'observe':
                result = self.bridge.observe()
            elif name == 'recall':
                result = self.store.recall(world, **args)
            elif name == 'remember':
                result = self.store.remember(world, **args)
            elif name == 'create_goal':
                result = self.store.create_goal(world, **args)
            elif name == 'update_goal':
                proof = args.pop('evidence_action_id')
                if args['status'] == 'completed' and (not proof or proof not in evidence):
                    raise ValueError('Completion requires a successful adapter action in this turn')
                result = self.store.update_goal(world, **args)
            else:
                result = await self.bridge.execute(name, args)
                if result.get('status') == 'succeeded':
                    evidence.add(result['action_id'])
            self.store.audit(world, 'tool', {'name': name, 'arguments': args, 'result': result})
            return result
        except (ValueError, TypeError) as exc:
            # Avoid Pydantic errors that include an unbounded copy of invalid model output.
            return {'status': 'failed', 'detail': str(exc)[:1000]}
