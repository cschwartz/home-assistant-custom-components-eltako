from collections.abc import Callable
from typing import Optional, TypeVar

from homeassistant.const import CONF_DEVICES
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import NoEntitySpecifiedError
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import entity_registry as er

E = TypeVar('E')


def from_config_or_none(from_config_function: Callable[[er.EntityRegistry, str, ConfigType], E],
                        entity_registry: er.EntityRegistry,
                        id: str,
                        config: ConfigType) -> Optional[E]:
    try:
        return from_config_function(entity_registry, id, config)
    except NoEntitySpecifiedError:
        return None


def devices_from_config(
    hass: HomeAssistant,
    from_config_function: Callable[[er.EntityRegistry, str, ConfigType], E],
    domain_config: ConfigType
) -> list[E]:
    entity_registry = er.async_get(hass)

    return [
        entity
        for device_id, config in domain_config[CONF_DEVICES].items()
        if (entity := from_config_or_none(from_config_function,
                                          entity_registry,
                                          device_id,
                                          config)) is not None
    ]
