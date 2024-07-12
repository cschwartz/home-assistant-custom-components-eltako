from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Optional, assert_never
import voluptuous as vol

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv

from homeassistant.core import (
    CALLBACK_TYPE,
    HomeAssistant,
    State,
    callback,
    Event,
    EventStateChangedData,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry

from .const import (
    CONF_SWITCH_IS_INVERTED,
    CONF_SWITCH_POSITION,
)
from .entity_registry import from_entity_ids
from .schema import enum_schema


class SwitchPosition(StrEnum):
    left = "left"
    right = "right"


class ActionType(StrEnum):
    on = "on"
    off = "off"


SWITCH_LISTENER_SCHEMA = vol.Schema(
    {
        cv.string: {
            vol.Optional(
                CONF_SWITCH_POSITION, default=SwitchPosition.left
            ): enum_schema(SwitchPosition),
            vol.Optional(CONF_SWITCH_IS_INVERTED, default=False): cv.boolean,
        }
    }
)


@dataclass(frozen=True, kw_only=True)
class SwitchListenerData:
    on_entries: list[RegistryEntry]
    off_entries: list[RegistryEntry]


class SwitchListener:
    def __init__(self, entity: Entity, data: SwitchListenerData) -> None:
        self._hass: Optional[HomeAssistant] = None
        self._entity = entity
        self._data = data

        self._on_switch_on: Optional[CALLBACK_TYPE] = None
        self._on_switch_off: Optional[CALLBACK_TYPE] = None

    async def async_added_to_hass(
        self,
        hass: HomeAssistant,
        on_switch_on: CALLBACK_TYPE,
        on_switch_off: CALLBACK_TYPE,
    ) -> None:
        self._hass = hass

        self._on_switch_on = on_switch_on
        self._on_switch_off = on_switch_off

        entity_ids = self._to_entity_ids(
            [*self._data.on_entries, *self._data.off_entries]
        )

        self._entity.async_on_remove(
            async_track_state_change_event(
                self._hass, entity_ids, self.switch_state_change_listener
            )
        )

    @callback
    async def switch_state_change_listener(
        self,
        event: Event[EventStateChangedData],
    ) -> None:
        # The callback is registered in async_added_to_hass after self._hass is set
        assert self._hass is not None

        if new_state_data := event.data["new_state"]:
            if (
                self._state_changed_for_entities(new_state_data, self._data.on_entries)
                and self._on_switch_on is not None
            ):
                self._on_switch_on()

            if (
                self._state_changed_for_entities(new_state_data, self._data.off_entries)
                and self._on_switch_off is not None
            ):
                self._on_switch_off()

            self._entity.async_write_ha_state()

    def _state_changed_for_entities(
        self, new_state: State, listened_entites: list[RegistryEntry]
    ) -> bool:
        return (
            new_state.entity_id in self._to_entity_ids(listened_entites)
        ) and new_state.state == "on"

    def _to_entity_ids(self, entries: list[RegistryEntry]) -> list[str]:
        return [entry.entity_id for entry in entries]


def to_action_code(action: ActionType, is_inverted: bool) -> Literal["o", "i"]:
    if not is_inverted:
        if action == ActionType.off:
            return "i"
        elif action == ActionType.on:
            return "o"
    else:
        if action == ActionType.off:
            return "o"
        elif action == ActionType.on:
            return "i"


def to_entity_id(
    device_id: str, action: ActionType, position: SwitchPosition, is_inverted: bool
) -> str:
    position_code = "a" if position == SwitchPosition.left else "b"
    action_code = to_action_code(action, is_inverted)

    return f"binary_sensor.{device_id}_{position_code}{action_code}_pressed"


def to_entity_pair(device_id: str, device_config: ConfigType) -> tuple[str, str]:
    position = device_config.get(CONF_SWITCH_POSITION)
    is_inverted = device_config.get(CONF_SWITCH_IS_INVERTED)

    on_entity_id = to_entity_id(device_id, ActionType.on, position, is_inverted)
    off_entity_id = to_entity_id(device_id, ActionType.off, position, is_inverted)

    return on_entity_id, off_entity_id


def from_switch_listener_config(
    entity_registry: EntityRegistry, switch_listener_config: ConfigType
) -> SwitchListenerData:
    entity_pairs = [
        to_entity_pair(device_id, device_config)
        for device_id, device_config in switch_listener_config.items()
    ]
    on_sensor_ids = [pair[0] for pair in entity_pairs]
    off_sensor_ids = [pair[1] for pair in entity_pairs]
    return SwitchListenerData(
        on_entries=from_entity_ids(
            entity_registry,
            on_sensor_ids,
        ),
        off_entries=from_entity_ids(
            entity_registry,
            off_sensor_ids,
        ),
    )
