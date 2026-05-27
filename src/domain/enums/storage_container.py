import os
from enum import Enum


class StorageContainer(Enum):
    CONTRIBUTION = "contributions"
    METADATA = os.getenv("AZURE_BLOB_STORAGE_METADATA_CONTAINER")
    SCHEMA = "schema"
    STAC = "stac"
    RAW = "raw"
    DATA = "data"
    OPEN_STREET_MAP = "open_street_map"
    FKB = "fkb"
    BENCHMARKS = os.getenv("AZURE_BLOB_STORAGE_BENCHMARK_CONTAINER")
