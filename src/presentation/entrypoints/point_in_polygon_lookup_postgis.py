from dependency_injector.wiring import Provide, inject
from sqlalchemy import Engine, text

from src import Config
from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


@inject
def point_in_polygon_lookup_postgis(
    db_context: Engine = Provide[Containers.postgres_context],
) -> None:
    """
    Benchmark: point-in-polygon lookup against the seeded ``buildings_{size}`` table
    using PostGIS. Tests a single fixed query point against all building polygons
    and returns the containing polygon(s).
    """
    dataset_size = _get_dataset_size()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn(db_context=db_context)


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("point-in-polygon-lookup-postgis", dataset_size)
    buildings_table = f"buildings_{dataset_size.value}"

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.POINT_IN_POLYGON_LOOKUP,
        cost_configuration=CostConfiguration(include_aci=True, include_postgres=True),
    )
    def _benchmark(
        db_context: Engine,
    ) -> list:
        sql = text(f"""
            SELECT *
            FROM {buildings_table}
            WHERE ST_Contains(geometry, ST_SetSRID(ST_Point(:lon, :lat), 4326))
            """)

        lon, lat = Config.POINT_IN_POLYGON_PROBE_WGS84
        with db_context.connect() as conn:
            return conn.execute(sql, {"lon": lon, "lat": lat}).fetchall()

    return _benchmark
