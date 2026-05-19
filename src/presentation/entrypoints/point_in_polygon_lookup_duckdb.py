import random

from dependency_injector.wiring import Provide, inject
from duckdb import DuckDBPyConnection

from src import Config
from src.application.common.monitor import monitor
from src.application.contracts import IFilePathService
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, Theme, BenchmarkIteration, BoundingBox, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size

TOTAL_POINTS: int = 10
INSIDE_RATIO: float = 0.3
SEED: int = 42


@inject
def point_in_polygon_lookup_duckdb(
    db_context: DuckDBPyConnection = Provide[Containers.duckdb_context],
    path_service: IFilePathService = Provide[Containers.file_path_service],
) -> None:
    """
    Benchmark: point-in-polygon lookups against the buildings dataset using DuckDB's
    spatial extension over Azure Blob Storage. The dataset size is pulled from DI and
    parameterises the parquet path. Generates a mix of inside and outside
    Trondheim-area points up front, then times per-point ``ST_Contains`` counts.
    """
    dataset_size = _get_dataset_size()
    points = _generate_points(
        db_context=db_context, path_service=path_service, dataset_size=dataset_size
    )
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn(points=points, db_context=db_context, path_service=path_service)


def _generate_points(
    db_context: DuckDBPyConnection,
    path_service: IFilePathService,
    dataset_size: DatasetSize,
) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = BoundingBox.TRONDHEIM_WGS84.value
    n_inside = int(TOTAL_POINTS * INSIDE_RATIO)
    n_outside = TOTAL_POINTS - n_inside

    path = path_service.create_release_virtual_filesystem_path(
        storage_scheme="az",
        release=Config.BENCHMARK_DOPPA_DATA_RELEASE,
        container=StorageContainer.DATA,
        theme=Theme.BUILDINGS,
        dataset_size=dataset_size,
        region="*",
        file_name="*.parquet",
    )

    # TODO: See if this query can be improved in terms of efficiency
    rows = db_context.execute(
        f"""
        WITH buildings_with_point_on_surface AS (
            SELECT *, ST_PointOnSurface(geometry) AS point_on_surface FROM read_parquet('{path}')
        ),

        buildings AS(
            SELECT
                ST_X(bpof.point_on_surface) AS lon,
                ST_Y(bpof.point_on_surface) AS lat
            FROM buildings_with_point_on_surface bpof
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(?, ?, ?, ?)) AND ST_IsValid(geometry)
            ORDER BY lon, lat
            LIMIT ?
        )

        SELECT * FROM buildings;
        """,
        [min_lon, min_lat, max_lon, max_lat, n_inside],
    ).fetchall()

    inside_points = [(row[0], row[1]) for row in rows]

    # TODO: Explore comments from https://github.com/kartAI/doppa/pull/196
    rng = random.Random(SEED)
    outside_points = [
        (rng.uniform(min_lon, max_lon), rng.uniform(min_lat, max_lat))
        for _ in range(n_outside)
    ]

    combined = inside_points + outside_points
    rng.shuffle(combined)
    return combined


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("point-in-polygon-lookup-duckdb", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.POINT_IN_POLYGON_LOOKUP,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=True),
    )
    def _benchmark(
        points: list[tuple[float, float]],
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

        rows: list = []
        for lon, lat in points:
            rows.extend(
                db_context.execute(
                    f"""
                    SELECT COUNT(*) FROM read_parquet('{path}')
                    WHERE ST_Contains(geometry, ST_Point(?, ?))
                    """,
                    [lon, lat],
                ).fetchall()
            )
        return rows

    return _benchmark
