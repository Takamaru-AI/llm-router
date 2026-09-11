from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DEFAULT_CONTEXT_LENGTH: Final[int] = 65536


@dataclass(frozen=True)
class ModelConfig:
    id: str
    display_name: str
    context_length: int