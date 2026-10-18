"""Wire protocol v1. Unknown fields and non-finite coordinates are rejected."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GameTool = Literal["inspect", "move_to", "follow_player", "look_at", "stop", "say",
                   "mine", "place", "use_block", "equip", "eat", "drop", "pickup",
                   "attack", "craft", "open_container", "transfer", "smelt", "sleep", "jump", "sneak"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Position(StrictModel):
    x: float = Field(ge=-30_000_000, le=30_000_000)
    y: float = Field(ge=-2048, le=2048)
    z: float = Field(ge=-30_000_000, le=30_000_000)


class Item(StrictModel):
    item: str = Field(max_length=120)
    count: int = Field(ge=0, le=99999)
    slot: int = Field(default=-1, ge=-1, le=200)
    durability: int | None = Field(default=None, ge=0)
    max_durability: int | None = Field(default=None, ge=0)
    enchanted: bool = False


class Entity(StrictModel):
    id: str = Field(max_length=80)
    kind: str = Field(max_length=120)
    name: str = Field(default="", max_length=80)
    position: Position
    visible: bool
    health: float | None = None
    distance: float = Field(default=0, ge=0)
    targeting_me: bool = False


class Snapshot(StrictModel):
    halt_generation: int = Field(default=-1, ge=-1)
    session_id: str = Field(max_length=80)
    sequence: int = Field(ge=0)
    source_sequence: int = Field(default=0, ge=0)
    dimension: str = Field(default="minecraft:overworld", max_length=120)
    position: Position
    health: float = Field(ge=0, le=2048)
    food: int = Field(ge=0, le=20)
    inventory: list[Item] = Field(default_factory=list, max_length=128)
    entities: list[Entity] = Field(default_factory=list, max_length=64)
    dangers: list[str] = Field(default_factory=list, max_length=16)
    environment: dict = Field(default_factory=dict, max_length=32)
    physiology: dict = Field(default_factory=dict, max_length=32)
    activity: str = Field(default="idle", max_length=200)


class Connect(StrictModel):
    protocol_version: Literal[1] = 1
    world_id: str = Field(min_length=1, max_length=100)
    agent_name: str = Field(min_length=1, max_length=80)
    capabilities: list[GameTool] = Field(max_length=32)


class GameEvent(StrictModel):
    session_id: str = Field(max_length=80)
    event_id: str = Field(min_length=1, max_length=100)
    kind: Literal["chat", "danger", "stuck", "death", "disconnected", "initiative", "recovered"]
    text: str = Field(default="", max_length=2000)
    sender: str = Field(default="", max_length=80)


class ActionResult(StrictModel):
    session_id: str = Field(max_length=80)
    action_id: str = Field(max_length=80)
    status: Literal["succeeded", "failed", "cancelled"]
    detail: str = Field(max_length=4000)
    data: dict = Field(default_factory=dict, max_length=64)
    snapshot_sequence: int = Field(default=0, ge=0)


class ChatMessage(StrictModel):
    text: str = Field(min_length=1, max_length=2000)


class InspectArgs(StrictModel):
    sensor: Literal["inventory", "area", "entity", "navigation", "block", "container", "recipes"]
    target: str | None = Field(max_length=100)
    radius: int = Field(ge=1, le=24)


class MoveArgs(Position):
    pass


class FollowArgs(StrictModel):
    player: str = Field(min_length=1, max_length=80)


class SayArgs(StrictModel):
    message: str = Field(min_length=1, max_length=240)


class EmptyArgs(StrictModel):
    pass


class BlockArgs(StrictModel):
    x: int = Field(ge=-30_000_000, le=30_000_000)
    y: int = Field(ge=-2048, le=2048)
    z: int = Field(ge=-30_000_000, le=30_000_000)


class ItemArgs(StrictModel):
    item: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")


class EquipArgs(ItemArgs):
    slot: Literal["mainhand", "offhand", "head", "chest", "legs", "feet"]


class DropArgs(ItemArgs):
    count: int = Field(ge=1, le=64)


class PlaceArgs(BlockArgs, ItemArgs):
    face: Literal["up", "down", "north", "south", "east", "west"]


class TargetArgs(StrictModel):
    target: str = Field(min_length=1, max_length=80)


class AttackArgs(TargetArgs):
    tactic: Literal['melee', 'shield'] = 'melee'


class CraftArgs(StrictModel):
    recipe: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
    times: int = Field(ge=1, le=16)


class TransferArgs(BlockArgs):
    direction: Literal["take", "put"]
    slot: int = Field(ge=0, le=200)
    count: int = Field(ge=1, le=64)
    item: str = Field(min_length=1, max_length=120)


class SmeltArgs(BlockArgs):
    input: str = Field(min_length=1, max_length=120)
    fuel: str = Field(min_length=1, max_length=120)
    count: int = Field(ge=1, le=16)


class SneakArgs(StrictModel):
    enabled: bool


class RememberArgs(StrictModel):
    key: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=2000)
    kind: Literal["place", "knowledge", "experience", "preference", "promise"]
    evidence: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    truth: Literal['observation', 'owner_statement', 'hypothesis', 'external'] = 'hypothesis'
    source: str = Field(default='', max_length=1000)


class RecallArgs(StrictModel):
    query: str = Field(max_length=200)


class GoalCheck(StrictModel):
    kind: Literal['position', 'inventory']
    dimension: str = Field(max_length=120)
    position: Position | None
    item: str | None = Field(max_length=120)
    count: int | None = Field(ge=1, le=99999)


class GoalArgs(StrictModel):
    description: str = Field(min_length=1, max_length=1000)
    success_condition: str = Field(min_length=1, max_length=1000)
    success_check: GoalCheck | None = None
    parent_id: str | None = Field(default=None, max_length=80)
    priority: int = Field(default=5, ge=1, le=10)


class GoalUpdateArgs(StrictModel):
    goal_id: str
    status: Literal["paused", "active", "completed", "failed"]
    summary: str = Field(max_length=1000)
    evidence_action_id: str | None


class SearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=250)
    scope: Literal['minecraft', 'open']


class FetchArgs(StrictModel):
    url: str = Field(min_length=1, max_length=2000)


class ReflectionArgs(StrictModel):
    situation: str = Field(min_length=1, max_length=1000)
    outcome: str = Field(min_length=1, max_length=1000)
    lesson: str = Field(min_length=1, max_length=1500)
    evidence_action_id: str = Field(min_length=1, max_length=80)


class AutonomyArgs(StrictModel):
    mode: Literal['wait', 'normal', 'expanded']


class PlanStep(StrictModel):
    tool: GameTool
    arguments: str = Field(min_length=2, max_length=2000, description='JSON object matching the named game tool schema')


class PlanArgs(StrictModel):
    steps: list[PlanStep] = Field(min_length=1, max_length=8)
