from __future__ import annotations

from dataclasses import dataclass

from .preset_route_config import PresetRouteConfig


@dataclass(frozen=True)
class PresetConfig:
    id: str
    display_name: str
    system_prompt: str | None
    routes: tuple[PresetRouteConfig, ...]