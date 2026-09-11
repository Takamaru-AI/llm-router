from __future__ import annotations

from dataclasses import dataclass

from .preset_model_config import PresetModelConfig


@dataclass(frozen=True)
class PresetRouteConfig:
    endpoint_id: str | None
    priority: int
    models: tuple[PresetModelConfig, ...]