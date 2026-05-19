from dependency_injector.wiring import Provide, inject
from duckdb import DuckDBPyConnection

from src import Config
from src.application.common.monitor import monitor
from src.application.contracts import IFilePathService
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, Theme, BenchmarkIteration, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size

K: int = 10


@inject
def knn_search_duckdb(
    db_context: DuckDBPyConnection = Provide[Containers.duckdb_context],
    path_service: IFilePathService = Provide[Containers.file_path_service],
) -> None:
    """
    Benchmark: k-nearest-neighbour search against the buildings dataset using DuckDB's
    spatial extension over Azure Blob Storage. DuckDB has no native KNN index, so the
    engine must scan and sort by ``ST_Distance`` to the fixed Trondheim-center
    reference point. The dataset size is pulled from DI and parameterises the parquet
    path.
    """
    dataset_size = _get_dataset_size()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn(db_context=db_context, path_service=path_service)


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("knn-search-duckdb", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.KNN_SEARCH,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=True),
    )
    def _benchmark(
        db_context: DuckDBPyConnection,
        path_service: IFilePathService,
    ) -> list:
        path = path_service.create_release_virtual_filesystem_path(
            storage_scheme="az",
            release=Config.BENCHMARK_DOPPA_DATA_RELEASE,
            container=StorageContainer.DATA,
            theme=Theme.BUILDINGS,
            dataset_size=dataset_size,
            region="*",
            file_name="*.parquet",
        )

        lon, lat = Config.TRONDHEIM_CENTER_WGS84

        return db_context.execute(
            f"""
            SELECT * FROM read_parquet('{path}')
            ORDER BY ST_Distance(geometry, ST_Point(?, ?))
            LIMIT {K};
            """,
            [lon, lat],
        ).fetchall()

    return _benchmark
