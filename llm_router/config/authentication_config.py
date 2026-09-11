from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticationConfig:
    type: str = "none"
    environment_variable: str | None = None
    header_name: str | None = None