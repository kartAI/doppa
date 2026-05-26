from enum import Enum


class StopReason(Enum):
    PRECISION = "precision"
    TIMEOUT = "timeout"
    CEILING = "ceiling"
    FIXED = "fixed"
    PARTIAL = "partial"
    FAILED = "failed"

    @classmethod
    def from_skip(cls, value) -> "StopReason":
        if isinstance(value, str):
            return cls(value)
        return cls.FAILED
