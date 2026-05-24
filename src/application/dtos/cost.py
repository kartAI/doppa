import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Cost:
    compute_cost: float
    storage_cost: float
    network_cost: float
    operations_cost: float
    total_cost: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass(frozen=True)
class CostConfiguration:
    include_aci: bool = False
    include_blob_storage: bool = False
    include_postgres: bool = False
    include_databricks: bool = False
    num_workers: int = 0
    is_cross_region_blob: bool = False
