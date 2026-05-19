from dependency_injector.wiring import Provide, inject
from duckdb import DuckDBPyConnection

from src import Config
from src.application.common.monitor import monitor
from src.application.contracts import IFilePathService
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, Theme, BenchmarkIteration, BoundingBox, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


@inject
def bbox_filtering_duckdb(
    db_context: DuckDBPyConnection = Provide[Containers.duckdb_context],
    path_service: IFilePathService = Provide[Containers.file_path_service],
) -> None:
    """
    Benchmark: bounding-box filter at neighborhood scale on the buildings dataset
    using DuckDB's spatial extension over Azure Blob Storage. The dataset size is
    pulled from DI and parameterises the parquet path. Filters by bbox intersection
    and a minimum projected area in EPSG:25832.
    """
    dataset_size = _get_dataset_size()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn(db_context=db_context, path_service=path_service)


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("bbox-filtering-duckdb", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.BBOX_FILTERING_RESULT_SET_SIZES,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=True)
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

        min_lon, min_lat, max_lon, max_lat = BoundingBox.NEIGHBORHOOD_WGS84.value

        return db_context.execute(
            f"""
            SELECT *, ST_Area(ST_Transform(geometry, 'EPSG:4326', 'EPSG:25832')) AS area
            FROM read_parquet('{path}')
            WHERE ST_Intersects(
                geometry,
                ST_MakeEnvelope(?, ?, ?, ?)
            )
            AND ST_Area(ST_Transform(geometry, 'EPSG:4326', 'EPSG:25832')) > 10;
            """,
            [min_lon, min_lat, max_lon, max_lat],
        ).fetchall()

    return _benchmark
