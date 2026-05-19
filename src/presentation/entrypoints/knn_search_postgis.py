from dependency_injector.wiring import Provide, inject
from sqlalchemy import Engine, text

from src import Config
from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size

K: int = 10


@inject
def knn_search_postgis(
    db_context: Engine = Provide[Containers.postgres_context],
) -> None:
    """
    Benchmark: k-nearest-neighbour search against the seeded ``buildings_{size}`` table
    using PostGIS. The ``<->`` operator triggers a GIST index-ordered scan, which is
    the point of testing PostGIS for KNN. Note: ``<->`` returns bounding-box distance,
    not true geometry distance; for the small building polygons used here the
    difference is negligible and matches typical real-world usage.
    """
    dataset_size = _get_dataset_size()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn(db_context=db_context)


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("knn-search-postgis", dataset_size)
    buildings_table = f"buildings_{dataset_size.value}"

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.KNN_SEARCH,
        cost_configuration=CostConfiguration(include_aci=True, include_postgres=True),
    )
    def _benchmark(
        db_context: Engine,
    ) -> list:
        lon, lat = Config.TRONDHEIM_CENTER_WGS84

        sql = text(
            f"""
            SELECT *
            FROM {buildings_table}
            ORDER BY geometry <-> ST_SetSRID(ST_Point(:lon, :lat), 4326)
            LIMIT {K};
            """
        )

        with db_context.connect() as conn:
            return conn.execute(sql, {"lon": lon, "lat": lat}).fetchall()

    return _benchmark
