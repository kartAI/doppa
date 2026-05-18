from enum import Enum


class DatasetSize(Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"

    @property
    def clones_per_polygon(self) -> int:
        """
        Number of synthetic clones generated per source polygon when synthesizing this dataset size.
        `SMALL` is a passthrough (no clones), `MEDIUM` produces 9 clones per source polygon (target ~40M total),
        and `LARGE` produces 23 clones per source polygon (target ~100M total).
        """
        match self:
            case DatasetSize.SMALL:
                return 0
            case DatasetSize.MEDIUM:
                return 9
            case DatasetSize.LARGE:
                return 23
