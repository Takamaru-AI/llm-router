from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetModelConfig:
    id: str
    priority: int