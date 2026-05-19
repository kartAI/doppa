from dependency_injector.wiring import Provide, inject
from duckdb import DuckDBPyConnection

from src import Config
from src.application.common.monitor import monitor
from src.application.contracts import IFilePathService
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, Theme, BenchmarkIteration, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


@inject
def national_scale_spatial_join_duckdb(
    db_context: DuckDBPyConnection = Provide[Containers.duckdb_context],
    path_service: IFilePathService = Provide[Containers.file_path_service],
) -> list:
    """
    Benchmark: national-scale spatial join between Norwegian municipalities and the
    buildings dataset using DuckDB's spatial extension over Azure Blob Storage. The
    dataset size is pulled from DI and parameterises the buildings parquet path.
    Returns the per-municipality building count ordered by descending count.
    """
    dataset_size = _get_dataset_size()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    return benchmark_fn(db_context=db_context, path_service=path_service)


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("national-scale-spatial-join-duckdb", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.NATIONAL_SCALE_SPATIAL_JOIN,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=True),
    )
    def _benchmark(
        db_context: DuckDBPyConnection,
        path_service: IFilePathService,
    ) -> list:
        buildings_path = path_service.create_release_virtual_filesystem_path(
            storage_scheme="az",
            release=Config.BENCHMARK_DOPPA_DATA_RELEASE,
            container=StorageContainer.DATA,
            theme=Theme.BUILDINGS,
            dataset_size=dataset_size,
            region="*",
            file_name="*.parquet",
        )
        municipalities_path = (
            f"az://{StorageContainer.METADATA.value}/{Config.DATABRICKS_MUNICIPALITIES_FILE}"
        )

        return db_context.execute(f"""
            WITH municipalities AS (
                SELECT
                    region AS municipality_name,
                    ST_GeomFromWKB(wkb) AS geometry
                FROM read_parquet('{municipalities_path}')
            )
            SELECT
                m.municipality_name,
                COUNT(*) AS building_count
            FROM municipalities m
            JOIN read_parquet('{buildings_path}') b
              ON ST_Intersects(m.geometry, b.geometry)
            GROUP BY m.municipality_name
            ORDER BY building_count DESC
        """).fetchall()

    return _benchmark
