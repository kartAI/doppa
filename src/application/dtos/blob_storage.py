import json
from dataclasses import asdict, dataclass


@dataclass
class BlobStorageUsage:
    read_transactions: int
    write_transactions: int
    list_transactions: int
    bytes_ingress: float
    bytes_egress: float
    storage_bytes: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass(frozen=True)
class BlobStoragePricing:
    read_operation_cost: float
    write_operation_cost: float
    list_operation_cost: float
    storage_gb_per_month: float
    ingress_per_gb: float = 0.0
    egress_per_gb: float = 0.0
    cross_region_egress_per_gb: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
