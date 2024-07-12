from typing import Optional

import voluptuous as vol

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType


from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import CONF_DEVICES, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import entity_registry as er

from .config import devices_from_config
from .const import CONF_SWITCH_LISTENERS
from .switch_listener import (
    SWITCH_LISTENER_SCHEMA,
    SwitchListenerData,
    from_switch_listener_config,
    SwitchListener,
)


class EltakoBinarySensor(BinarySensorEntity):
    def __init__(
        self,
        device_id: str,
        name: str,
        switch_listener_data: SwitchListenerData,
    ) -> None:

        self._attr_unique_id = device_id
        self._attr_name = name

        self._switch_listener = SwitchListener(self, switch_listener_data)

    async def async_added_to_hass(self) -> None:
        await self._switch_listener.async_added_to_hass(
            self.hass, self.on_switch_on, self.on_switch_off
        )

    def on_switch_on(self) -> None:
        self._attr_is_on = True

    def on_switch_off(self) -> None:
        self._attr_is_on = False


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_DEVICES, default={}): vol.Schema(
            {
                cv.string: {
                    vol.Required(CONF_NAME): cv.string,
                    vol.Required(CONF_SWITCH_LISTENERS): SWITCH_LISTENER_SCHEMA,
                }
            }
        ),
    }
)


def from_config(
    entity_registry: er.EntityRegistry, id: str, config: ConfigType
) -> EltakoBinarySensor:
    return EltakoBinarySensor(
        id,
        config[CONF_NAME],
        switch_listener_data=from_switch_listener_config(
            entity_registry, config[CONF_SWITCH_LISTENERS]
        ),
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    async_add_entities(devices_from_config(hass, from_config, config))
