from dependency_injector.wiring import Provide, inject

from src import Config
from src.application.contracts import IBlobStorageService
from src.domain.enums import StorageContainer
from src.infra.infrastructure import Containers

_BLOB_PREFIX: str = "copies/shapefile"
_SHAPEFILE_EXTENSIONS: tuple[str, ...] = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix")


@inject
def download_buildings_shapefile(
    blob_storage_service: IBlobStorageService = Provide[Containers.blob_storage_service],
) -> None:
    """
    Download the pre-baked buildings shapefile bundle from blob storage into
    ``Config.BUILDINGS_SHAPEFILE``'s directory. Shared by every ``*_local``
    entrypoint that consumes the Shapefile representation; centralising it here
    keeps the blob prefix and the sidecar extension set in one place.
    """
    Config.BUILDINGS_SHAPEFILE.parent.mkdir(parents=True, exist_ok=True)

    base = Config.BUILDINGS_SHAPEFILE.with_suffix("")
    for ext in _SHAPEFILE_EXTENSIONS:
        blob_name = f"{_BLOB_PREFIX}/{base.name}{ext}"
        data = blob_storage_service.download_file(
            container_name=StorageContainer.DATA,
            blob_name=blob_name,
        )
        if data is not None:
            base.with_suffix(ext).write_bytes(data)
