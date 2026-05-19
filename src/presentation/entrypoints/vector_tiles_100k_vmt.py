from dependency_injector.wiring import inject, Provide

from src import Config
from src.application.common.monitor import monitor
from src.application.contracts import ITileApiService, ITileService
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration
from src.infra.infrastructure import Containers


@inject
def vector_tiles_100k_vmt(tile_service: ITileService = Provide[Containers.tile_service]) -> None:
    """
    Benchmark: 100k vector tile fetches from the on-demand MVT tile server backed by
    PostGIS. Loads the candidate tile list before timing sequential per-tile HTTP
    requests.
    """
    tiles = tile_service.load_tiles(number_of_tiles=Config.VECTOR_TILES_100K_TOTAL_REQUESTS)
    _benchmark(tiles=tiles)


@inject
@monitor(
    query_id="vector-tiles-100k-vmt",
    benchmark_iteration=BenchmarkIteration.VECTOR_TILE_100K,
    cost_configuration=CostConfiguration(include_aci=True, include_postgres=True)
)
def _benchmark(
        tiles: list[tuple[int, int, int]],
        tile_api_service: ITileApiService = Provide[Containers.tile_api_service]
) -> None:
    for tile in tiles:
        z, x, y = tile
        tile_api_service.fetch_vmt_tile(z=z, x=x, y=y)
