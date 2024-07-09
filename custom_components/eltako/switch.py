from collections.abc import Callable, Coroutine
from typing import Any, Optional, TypeVar
import voluptuous as vol

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_DEVICES, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import NoEntitySpecifiedError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .config import devices_from_config
from .const import CONF_VIRTUAL_SWITCH, CONF_SWITCH_LISTENERS
from .switch_user import (
    SWITCH_SCHEMA,
    SwitchUserData,
    SwitchUser,
    from_switch_config,
)
from .trigger_listener import (
    TRIGGERS_LISTENER_SCHEMA,
    TriggerListenerData,
    TriggerListener,
    from_trigger_config,
)


PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_DEVICES, default={}): vol.Schema(
            {
                cv.string: {
                    vol.Optional(CONF_NAME): cv.string,
                    vol.Required(CONF_SWITCH_LISTENERS): TRIGGERS_LISTENER_SCHEMA,
                    vol.Required(CONF_VIRTUAL_SWITCH): SWITCH_SCHEMA,
                }
            }
        ),
    }
)


class EltakoSwitch(SwitchEntity):
    def __init__(
        self,
        id: str,
        name: str,
        switch_user_data: SwitchUserData,
        trigger_listener_data: TriggerListenerData,
    ) -> None:
        self._attr_unique_id = id
        self._attr_name = name

        self._trigger_listener_data = trigger_listener_data

        self._switch_user = SwitchUser(switch_user_data)
        self._trigger_listener = TriggerListener(self, trigger_listener_data)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        await self._trigger_listener.async_added_to_hass(
            self.hass,
            self.on_trigger_on,
            self.on_trigger_off
        )

    def on_trigger_on(self) -> None:
        self._set_state(True)

    def on_trigger_off(self) -> None:
        self._set_state(False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._switch_user.push_on(self.hass)
        self._set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._switch_user.push_off(self.hass)
        self._set_state(False)

    def _set_state(self, state: bool) -> None:
        self._attr_is_on = state
        self.async_write_ha_state()


def from_config(
    entity_registry: er.EntityRegistry, id: str, config: ConfigType
) -> EltakoSwitch:
    return EltakoSwitch(
        id,
        name=config.pop(CONF_NAME),
        switch_user_data=from_switch_config(
            entity_registry, config.pop(CONF_VIRTUAL_SWITCH)
        ),
        trigger_listener_data=from_trigger_config(
            entity_registry, config.pop(CONF_SWITCH_LISTENERS)
        ),
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    async_add_entities(devices_from_config(hass, from_config, config))
