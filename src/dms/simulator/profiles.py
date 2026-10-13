from dataclasses import dataclass
from typing import Protocol


class Profile(Protocol):
    def fraction(self, progress: float) -> float: ...


@dataclass(frozen=True, slots=True)
class LinearProfile:
    def fraction(self, progress: float) -> float:
        return progress


LINEAR = LinearProfile()
