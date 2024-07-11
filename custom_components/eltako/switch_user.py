from dataclasses import dataclass
from enum import Enum, StrEnum

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry
from homeassistant.helpers.typing import ConfigType

from .const import CONF_SWITCH_ID, CONF_SWITCH_OPTION_DOWN, CONF_SWITCH_OPTION_UP
from .entity_registry import from_entity_id
from .schema import enum_schema


class ButtonOption(StrEnum):
    AO = "AO"
    AI = "AI"
    BO = "BO"
    BI = "BI"


SWITCH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SWITCH_ID): cv.entity_domain(["select", "input_select"]),
        vol.Required(
            CONF_SWITCH_OPTION_UP,
            default=ButtonOption.BO.name
        ): enum_schema(ButtonOption),
        vol.Required(
            CONF_SWITCH_OPTION_DOWN,
            default=ButtonOption.BI.name
        ): enum_schema(ButtonOption),
    }
)


@dataclass(frozen=True, kw_only=True)
class SwitchUserData:
    entry: RegistryEntry
    off_action: ButtonOption
    on_action: ButtonOption


def from_switch_config(entity_registry: EntityRegistry, switch_config: ConfigType) -> SwitchUserData:
    return SwitchUserData(
        entry=from_entity_id(
            entity_registry,
            switch_config.pop(CONF_SWITCH_ID)
        ),
        off_action=switch_config.pop(CONF_SWITCH_OPTION_DOWN),
        on_action=switch_config.pop(CONF_SWITCH_OPTION_UP)
    )


class SwitchUser:
    def __init__(self, data: SwitchUserData) -> None:
        self._data = data

    async def push_on(self, hass: HomeAssistant) -> None:
        await self._push_switch(hass, self._data.on_action)

    async def push_off(self, hass: HomeAssistant) -> None:
        await self._push_switch(hass, self._data.off_action)

    async def _push_switch(self, hass: HomeAssistant, action: ButtonOption) -> None:
        domain = self._data.entry.domain
        entity_id = self._data.entry.entity_id

        option_none = "None"
        option = str(action)

        await hass.services.async_call(
            domain,
            "select_option",
            {"option": option_none, "entity_id": entity_id},
        )
        await hass.services.async_call(
            domain,
            "select_option",
            {"option": option, "entity_id": entity_id},
        )
        await hass.services.async_call(
            domain,
            "select_option",
            {"option": option_none, "entity_id": entity_id},
        )
