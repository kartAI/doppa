import geopandas as gpd
from dependency_injector.wiring import Provide, inject
from shapely.geometry import box

from src import Config
from src.application.common.monitor import monitor
from src.application.contracts import IBlobStorageService
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, BenchmarkIteration, BoundingBox, DataSource, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


def attribute_spatial_compound_filter_local() -> None:
    """
    Benchmark: compound attribute + spatial filter on the buildings shapefile,
    executed locally via GeoPandas. The Shapefile target is the small dataset only
    per Table 4.2.1, so this entrypoint refuses to run at MEDIUM or LARGE rather
    than silently producing comparable numbers. Downloads the pre-baked shapefile
    copy from blob storage and selects OSM-sourced buildings that intersect the
    neighborhood-scale bounding box.
    """
    dataset_size = _get_dataset_size()
    if dataset_size is not DatasetSize.SMALL:
        raise ValueError(
            f"attribute_spatial_compound_filter_local only supports DatasetSize.SMALL; "
            f"got {dataset_size}. The Shapefile target is small-only per Table 4.2.1."
        )
    _download_data()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn()


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("attribute-spatial-compound-filter-local", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.ATTRIBUTE_SPATIAL_COMPOUND_FILTER,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=False),
    )
    def _benchmark() -> gpd.GeoDataFrame:
        min_lon, min_lat, max_lon, max_lat = BoundingBox.NEIGHBORHOOD_WGS84.value
        envelope = box(min_lon, min_lat, max_lon, max_lat)

        gdf = gpd.read_file(Config.BUILDINGS_SHAPEFILE).set_crs(epsg=4326, allow_override=True)
        return gdf[(gdf["source"] == DataSource.OSM.value) & gdf.geometry.intersects(envelope)]

    return _benchmark


@inject
def _download_data(
    blob_storage_service: IBlobStorageService = Provide[Containers.blob_storage_service],
) -> None:
    Config.BUILDINGS_SHAPEFILE.parent.mkdir(parents=True, exist_ok=True)

    blob_prefix = "copies/shapefile"
    base = Config.BUILDINGS_SHAPEFILE.with_suffix("")
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix"):
        blob_name = f"{blob_prefix}/{base.name}{ext}"
        data = blob_storage_service.download_file(
            container_name=StorageContainer.DATA,
            blob_name=blob_name,
        )
        if data is not None:
            base.with_suffix(ext).write_bytes(data)
