from __future__ import annotations

from dataclasses import dataclass, field

from .authentication_config import AuthenticationConfig
from .model_config import ModelConfig


@dataclass(frozen=True)
class EndpointConfig:
    id: str | None = None
    openai_base_url: str = ""
    authentication: AuthenticationConfig = field(default_factory=AuthenticationConfig)
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 300.0
    attempt_timeout_seconds: float | None = None
    health_check_timeout_seconds: float = 3.0
    models: tuple[ModelConfig, ...] = ()