from __future__ import annotations


class State:
    def __init__(self) -> None:
        self._model: str | None = None

    def record(self, model: str) -> None:
        self._model = model

    def read(self) -> str | None:
        return self._model