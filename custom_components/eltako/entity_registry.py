import logging
from homeassistant.exceptions import NoEntitySpecifiedError
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry

_LOGGER = logging.getLogger(__name__)


def from_entity_ids(entity_registry: EntityRegistry, entity_ids: list[str]) -> list[RegistryEntry]:
    return [from_entity_id(entity_registry, entity_id) for entity_id in entity_ids]


def from_entity_id(entity_registry: EntityRegistry, entity_id: str) -> RegistryEntry:
    registry_entity = entity_registry.async_get(entity_id)

    if not registry_entity:
        _LOGGER.error(f"Entity with id '{entity_id}' not found.")
        raise NoEntitySpecifiedError

    return registry_entity
