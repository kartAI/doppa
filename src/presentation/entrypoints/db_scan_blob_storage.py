from dependency_injector.wiring import Provide, inject
from duckdb import DuckDBPyConnection

from src import Config
from src.application.common.monitor import monitor
from src.application.contracts import IFilePathService
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, Theme, BenchmarkIteration, DatasetSize
from src.infra.infrastructure import Containers


@inject
@monitor(
    query_id="db-scan-blob-storage",
    benchmark_iteration=BenchmarkIteration.DB_SCAN,
    cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=True)
)
def db_scan_blob_storage(
        db_context: DuckDBPyConnection = Provide[Containers.duckdb_context],
        path_service: IFilePathService = Provide[Containers.file_path_service]
) -> list:
    """
    Benchmark: full table scan (``COUNT(*)``) on the small buildings dataset using
    DuckDB over Azure Blob Storage via the ``read_parquet`` virtual filesystem.
    """
    path = path_service.create_release_virtual_filesystem_path(
        storage_scheme="az",
        release=Config.BENCHMARK_DOPPA_DATA_RELEASE,
        container=StorageContainer.DATA,
        theme=Theme.BUILDINGS,
        dataset_size=DatasetSize.SMALL,
        region="*",
        file_name="*.parquet"
    )

    return db_context.execute(f"SELECT count(*) AS count FROM read_parquet('{path}')").fetchall()
