from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class EstimationMethodId(StrEnum):
    MEAN_RATE = "mean_rate"


class MissingReason(StrEnum):
    RULE_VIOLATION = "rule_violation"
    OVERLAP_WITH_RULE_VIOLATION = "overlap_with_rule_violation"
    UNKNOWN_DURATION = "unknown_duration"
    UNMEASURED_CHANGE = "unmeasured_change"
    NO_RATE_HISTORY = "no_rate_history"


@dataclass(frozen=True, slots=True, kw_only=True)
class EventEstimate:
    method: EstimationMethodId
    params: Mapping[str, int]
    value_kg: int | None
    missing_reason: MissingReason | None
