from io import BytesIO

import geopandas as gpd
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContainerClient, PublicAccess

from src import Config
from src.application.common import logger
from src.application.contracts import IBlobStorageService, IFilePathService
from src.domain.enums import StorageContainer, Theme, DatasetSize


class BlobStorageService(IBlobStorageService):
    __blob_storage_context: BlobServiceClient
    __file_path_service: IFilePathService

    def __init__(self, blob_storage_context: BlobServiceClient, file_path_service: IFilePathService):
        self.__blob_storage_context = blob_storage_context
        self.__file_path_service = file_path_service

    def ensure_container(self, container_name: StorageContainer) -> None:
        container_client = self.__blob_storage_context.get_container_client(container_name.value)
        if not container_client.exists():
            logger.info(f"Blob storage container '{container_name.value}' does not exist. Creating...")
            self.__blob_storage_context.create_container(container_name.value, public_access=PublicAccess.CONTAINER)
            logger.info(f"Created blob storage container: {container_name.value}")

    def get_container(self, container_name: StorageContainer) -> ContainerClient:
        self.ensure_container(container_name)
        return self.__blob_storage_context.get_container_client(container_name.value)

    def upload_file(self, container_name: StorageContainer, blob_name: str, data: bytes) -> str | None:
        if len(data) == 0:
            return None

        container = self.get_container(container_name)
        blob_client = container.upload_blob(
            name=blob_name,
            data=data,
            overwrite=True,
            max_concurrency=Config.AZURE_BLOB_STORAGE_MAX_CONCURRENCY
        )

        logger.debug(f"Uploaded blob '{blob_name}'. It can be accessed at: {blob_client.url}")
        return blob_client.url

    def delete_file(self) -> bool:
        raise NotImplementedError

    def download_file(self, container_name: StorageContainer, blob_name: str) -> bytes | None:
        try:
            logger.debug(f"Downloading bytes from blob '{blob_name}' from container '{container_name.value}'.")
            container = self.get_container(container_name)
            blob_client = container.get_blob_client(blob_name)
            data = blob_client.download_blob().readall()
            return data
        except ResourceNotFoundError:
            logger.warning(f"No blob found with name '{blob_name}' in container '{container_name.value}'.")
            return None

    def is_blob_in_storage_container(self, container_name: StorageContainer, blob_name: str) -> bool:
        container = self.get_container(container_name)
        blob_client = container.get_blob_client(blob_name)
        return blob_client.exists()

    def upload_blobs_as_parquet(
            self,
            container: StorageContainer,
            release: str,
            theme: Theme,
            region: str,
            partitions: list[gpd.GeoDataFrame],
            dataset_size: DatasetSize | None = None,
            row_group_size: int | None = None,
            **kwargs: str
    ) -> list[str]:
        asset_paths = []

        for index, partition in enumerate(partitions):
            if partition.empty:
                logger.info(f"Partition {index} for region '{region}' is empty. Skipping upload.")
                continue

            storage_path = self.__file_path_service.create_dataset_blob_path(
                release=release,
                theme=theme,
                region=region,
                file_name=f"part_{index:05d}.parquet",
                dataset_size=dataset_size,
                **kwargs if kwargs else {}
            )

            extra_parquet_kwargs: dict[str, int] = (
                {"row_group_size": row_group_size} if row_group_size is not None else {}
            )

            with BytesIO() as buffer:
                partition.to_parquet(
                    buffer,
                    index=False,
                    compression="snappy",
                    geometry_encoding="WKB",
                    schema_version="1.1.0",
                    write_covering_bbox="bbox" not in partition.columns,
                    **extra_parquet_kwargs,
                )

                buffer.seek(0)

                asset_file_path = self.upload_file(
                    container_name=container,
                    blob_name=storage_path,
                    data=buffer.getvalue()
                )

                if asset_file_path:
                    asset_paths.append(asset_file_path)

        return asset_paths

    def has_files_under_blob_path_base(self, container: StorageContainer, path: str) -> bool:
        container_client = self.__blob_storage_context.get_container_client(container.value)
        blobs = list(container_client.list_blob_names(name_starts_with=path))
        return len(blobs) > 0

    def get_blob_summary(self, container: StorageContainer, path: str) -> tuple[int, int]:
        base_path = self.__file_path_service.remove_blob_file_name_from_path(
            file_path=path, file_name="region=*/*.parquet"
        )
        count = 0
        total_size = 0
        for blob in self.__blob_storage_context.get_container_client(
                container=container.value
        ).list_blobs(name_starts_with=base_path):
            count += 1
            total_size += blob.size
        return count, total_size
