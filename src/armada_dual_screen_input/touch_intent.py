"""Input intents shared by positioning and native touch; no I/O or capture."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TouchIntent:
    kind: Literal["down", "move", "up", "cancel", "wheel"]
    position: tuple[float, float]
    wheel: tuple[float, float] = (0.0, 0.0)
    contact_id: int = 1
