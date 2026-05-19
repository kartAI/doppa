from dependency_injector.wiring import inject, Provide
from pmtiles.reader import Reader

from src import Config
from src.application.common.monitor import monitor
from src.application.contracts import IFilePathService, ITileApiService, ITileService
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, BenchmarkIteration
from src.infra.infrastructure import Containers


@inject
def vector_tiles_100k_pmtiles(
        file_path_service: IFilePathService = Provide[Containers.file_path_service],
        tile_service: ITileService = Provide[Containers.tile_service],
        tile_api_service: ITileApiService = Provide[Containers.tile_api_service]
) -> None:
    """
    Benchmark: 100k vector tile fetches from the buildings PMTiles archive on Azure
    Blob Storage. Opens a PMTiles reader against the blob URL and loads the
    candidate tile list before timing sequential per-tile reads.
    """
    pmtiles_azure_url = file_path_service.create_url_to_blob_resource(
        container=StorageContainer.TILES,
        blob_path=Config.BUILDINGS_PMTILES_FILE.name
    )

    reader = tile_api_service.create_pmtiles_reader(pmtiles_url=pmtiles_azure_url)

    tiles = tile_service.load_tiles(number_of_tiles=Config.VECTOR_TILES_100K_TOTAL_REQUESTS)
    _benchmark(reader=reader, tiles=tiles)


@inject
@monitor(
    query_id="vector-tiles-100k-pmtiles",
    benchmark_iteration=BenchmarkIteration.VECTOR_TILE_100K,
    cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=True)
)
def _benchmark(
        reader: Reader,
        tiles: list[tuple[int, int, int]],
        tile_api_service: ITileApiService = Provide[Containers.tile_api_service]
) -> None:
    for tile in tiles:
        z, x, y = tile
        tile_api_service.fetch_pmtiles_tile(reader=reader, z=z, x=x, y=y)
