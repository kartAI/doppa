from enum import Enum


class StopReason(Enum):
    PRECISION = "precision"
    TIMEOUT = "timeout"
    CEILING = "ceiling"
    FIXED = "fixed"
    PARTIAL = "partial"
    FAILED = "failed"
