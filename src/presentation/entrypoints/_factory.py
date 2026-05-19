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
    the active dataset size. ``DatasetSize.SMALL`` returns the bare base so historical
    SMALL-only run keys in blob storage remain accessible without renaming; other sizes
    get a ``"-{size}"`` suffix so results stay keyed unambiguously.
    """
    if dataset_size is DatasetSize.SMALL:
        return base
    return f"{base}-{dataset_size.value}"
