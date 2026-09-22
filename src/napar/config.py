from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NAPAR_", env_file=".env", extra="ignore")

    bridge_token: SecretStr = Field(min_length=32)
    database: Path = Path("data/napar.db")
    llm_backend: Literal["disabled", "openai"] = "disabled"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    max_calls_per_day: int = Field(default=120, ge=1, le=10000)
    max_steps: int = Field(default=6, ge=1, le=20)
    max_output_tokens: int = Field(default=700, ge=100, le=4000)
    owner_name: str = ""
    initiative_seconds: int = Field(default=0, ge=0)
    action_timeout: float = Field(default=20, gt=0, le=120)
    state_max_age: float = Field(default=3, gt=0, le=30)
