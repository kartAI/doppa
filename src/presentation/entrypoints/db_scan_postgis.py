from dependency_injector.wiring import inject, Provide
from sqlalchemy import Engine, text

from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


@inject
def db_scan_postgis(
    db_context: Engine = Provide[Containers.postgres_context],
) -> list:
    """
    Benchmark: full table scan (``COUNT(*)``) on the seeded ``buildings_{size}``
    table using PostGIS. The dataset size is pulled from DI and parameterises the
    buildings table reference.
    """
    dataset_size = _get_dataset_size()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    return benchmark_fn(db_context=db_context)


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("db-scan-postgis", dataset_size)
    buildings_table = f"buildings_{dataset_size.value}"

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.DB_SCAN,
        cost_configuration=CostConfiguration(include_aci=True, include_postgres=True),
    )
    def _benchmark(
        db_context: Engine,
    ) -> list:
        with db_context.connect() as conn:
            return [
                conn.execute(
                    text(f"SELECT count(*) AS count FROM {buildings_table}")
                ).scalar_one()
            ]

    return _benchmark
