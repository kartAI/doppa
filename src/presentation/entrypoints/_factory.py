from dependency_injector.wiring import Provide, inject

from src.domain.enums import DatasetSize
from src.infra.infrastructure import Containers


@inject
def _get_dataset_size(
    dataset_size_value: str = Provide[Containers.config.dataset_size],
) -> DatasetSize:
    """
    Resolve the current dataset size from the DI container as a typed enum.

    The container stores the raw enum value (string) so it can be injected anywhere
    via ``Provide[Containers.config.dataset_size]``; this helper converts it back to
    the ``DatasetSize`` enum so call sites can pattern-match on members.
    """
    return DatasetSize(dataset_size_value)


def _build_query_id(base: str, dataset_size: DatasetSize) -> str:
    """
    Compose the ``query_id`` for a benchmark entrypoint from its base identifier and
    the active dataset size by appending ``"-{size}"`` for every size, including
    ``SMALL``. Historical SMALL run keys written under the bare ``base`` no longer
    share a prefix with new SMALL runs, but every run is now self-describing about
    the dataset tier it ran against.
    """
    return f"{base}-{dataset_size.value}"
