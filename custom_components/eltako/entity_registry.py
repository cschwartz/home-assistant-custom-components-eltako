import logging
from typing import Optional
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry

_LOGGER = logging.getLogger(__name__)


def from_entity_ids(entity_registry: EntityRegistry, entity_ids: list[str]) -> list[RegistryEntry]:
    return [registry_entry
            for entity_id in entity_ids
            if (registry_entry := entity_registry.async_get(entity_id))]


def from_entity_id(entity_registry: EntityRegistry, entity_id: str) -> Optional[RegistryEntry]:
    registry_entity = entity_registry.async_get(entity_id)

    if not registry_entity:
        _LOGGER.error(f"Entity with id '{entity_id}' not found.")

    return registry_entity
