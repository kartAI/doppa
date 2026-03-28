import random

from dependency_injector.wiring import Provide, inject
from duckdb import DuckDBPyConnection

from src import Config
from src.application.common.monitor_network import monitor_network
from src.application.contracts import IFilePathService
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, Theme, BenchmarkIteration, BoundingBox
from src.infra.infrastructure import Containers

TOTAL_POINTS: int = 10
INSIDE_RATIO: float = 0.3
SEED: int = 42


@inject
def point_in_polygon_lookup_duckdb(
        db_context: DuckDBPyConnection = Provide[Containers.duckdb_context],
        path_service: IFilePathService = Provide[Containers.file_path_service],
) -> None:
    points = _generate_points(db_context=db_context, path_service=path_service)
    _benchmark(points=points)


def _generate_points(
        db_context: DuckDBPyConnection,
        path_service: IFilePathService,
) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = BoundingBox.TRONDHEIM_WGS84.value
    n_inside = int(TOTAL_POINTS * INSIDE_RATIO)
    n_outside = TOTAL_POINTS - n_inside

    path = path_service.create_release_virtual_filesystem_path(
        storage_scheme="az",
        release=Config.BENCHMARK_DOPPA_DATA_RELEASE,
        container=StorageContainer.DATA,
        theme=Theme.BUILDINGS,
        region="*",
        file_name="*.parquet",
    )

    rows = db_context.execute(
        f"""
        SELECT ST_X(ST_Centroid(geometry)) AS lon, ST_Y(ST_Centroid(geometry)) AS lat
        FROM read_parquet('{path}')
        WHERE ST_Intersects(geometry, ST_MakeEnvelope(?, ?, ?, ?))
          AND ST_IsValid(geometry)
        ORDER BY lon, lat
        LIMIT ?
        """,
        [min_lon, min_lat, max_lon, max_lat, n_inside],
    ).fetchall()

    inside_points = [(row[0], row[1]) for row in rows]

    rng = random.Random(SEED)
    outside_points = [
        (rng.uniform(min_lon, max_lon), rng.uniform(min_lat, max_lat))
        for _ in range(n_outside)
    ]

    combined = inside_points + outside_points
    rng.shuffle(combined)
    return combined


@inject
@monitor_network(
    query_id="point-in-polygon-lookup-duckdb",
    benchmark_iteration=BenchmarkIteration.POINT_IN_POLYGON_LOOKUP,
    cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=True)
)
def _benchmark(
        points: list[tuple[float, float]],
        db_context: DuckDBPyConnection = Provide[Containers.duckdb_context],
        path_service: IFilePathService = Provide[Containers.file_path_service],
) -> None:
    path = path_service.create_release_virtual_filesystem_path(
        storage_scheme="az",
        release=Config.BENCHMARK_DOPPA_DATA_RELEASE,
        container=StorageContainer.DATA,
        theme=Theme.BUILDINGS,
        region="*",
        file_name="*.parquet",
    )

    for lon, lat in points:
        db_context.execute(
            f"""
            SELECT COUNT(*) FROM read_parquet('{path}')
            WHERE ST_Contains(geometry, ST_Point(?, ?))
            """,
            [lon, lat],
        )
