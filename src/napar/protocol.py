"""Wire protocol v1. Unknown fields and non-finite coordinates are rejected."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GameTool = Literal["inspect", "move_to", "follow_player", "look_at", "stop", "say"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Position(StrictModel):
    x: float = Field(ge=-30_000_000, le=30_000_000)
    y: float = Field(ge=-2048, le=2048)
    z: float = Field(ge=-30_000_000, le=30_000_000)


class Item(StrictModel):
    item: str = Field(max_length=120)
    count: int = Field(ge=0, le=99999)


class Entity(StrictModel):
    id: str = Field(max_length=80)
    kind: str = Field(max_length=120)
    name: str = Field(default="", max_length=80)
    position: Position
    visible: bool


class Snapshot(StrictModel):
    session_id: str = Field(max_length=80)
    sequence: int = Field(ge=0)
    dimension: str = Field(default="minecraft:overworld", max_length=120)
    position: Position
    health: float = Field(ge=0, le=2048)
    food: int = Field(ge=0, le=20)
    inventory: list[Item] = Field(default_factory=list, max_length=128)
    entities: list[Entity] = Field(default_factory=list, max_length=64)
    dangers: list[str] = Field(default_factory=list, max_length=16)


class Connect(StrictModel):
    protocol_version: Literal[1] = 1
    world_id: str = Field(min_length=1, max_length=100)
    agent_name: str = Field(min_length=1, max_length=80)
    capabilities: list[GameTool] = Field(max_length=6)


class GameEvent(StrictModel):
    session_id: str = Field(max_length=80)
    event_id: str = Field(min_length=1, max_length=100)
    kind: Literal["chat", "danger", "stuck", "death", "disconnected"]
    text: str = Field(default="", max_length=2000)
    sender: str = Field(default="", max_length=80)


class ActionResult(StrictModel):
    session_id: str = Field(max_length=80)
    action_id: str = Field(max_length=80)
    status: Literal["succeeded", "failed", "cancelled"]
    detail: str = Field(max_length=4000)


class ChatMessage(StrictModel):
    text: str = Field(min_length=1, max_length=2000)


class InspectArgs(StrictModel):
    sensor: Literal["inventory", "area", "entity", "navigation"]
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


class RememberArgs(StrictModel):
    key: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=2000)
    kind: Literal["place", "knowledge", "experience", "preference", "promise"]
    evidence: str = Field(min_length=1, max_length=1000)


class RecallArgs(StrictModel):
    query: str = Field(max_length=200)


class GoalArgs(StrictModel):
    description: str = Field(min_length=1, max_length=1000)
    success_condition: str = Field(min_length=1, max_length=1000)


class GoalUpdateArgs(StrictModel):
    goal_id: str
    status: Literal["paused", "active", "completed", "failed"]
    summary: str = Field(max_length=1000)
    evidence_action_id: str | None
