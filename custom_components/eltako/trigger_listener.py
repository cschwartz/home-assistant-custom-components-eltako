from dataclasses import dataclass
from typing import Optional
import voluptuous as vol

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv

from homeassistant.core import HomeAssistant, State, callback, Event, EventStateChangedData
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry

from .const import CONF_TRIGGER_OFF_ID, CONF_TRIGGER_ON_ID
from .entity_registry import from_entity_ids

TRIGGERS_LISTENER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TRIGGER_ON_ID): vol.All(
            cv.ensure_list,
            [cv.entity_domain(["binary_sensor", "input_boolean"])]
        ),
        vol.Required(CONF_TRIGGER_OFF_ID): vol.All(
            cv.ensure_list,
            [cv.entity_domain(["binary_sensor", "input_boolean"])]
        )
    }
)


@dataclass(frozen=True, kw_only=True)
class TriggerListenerData:
    on_entries: list[RegistryEntry]
    off_entries: list[RegistryEntry]


def from_trigger_config(entity_registry: EntityRegistry, trigger_config: ConfigType) -> TriggerListenerData:
    return TriggerListenerData(
        on_entries=from_entity_ids(
            entity_registry,
            trigger_config[CONF_TRIGGER_ON_ID]),
        off_entries=from_entity_ids(
            entity_registry,
            trigger_config[CONF_TRIGGER_OFF_ID])
    )


class TriggerListener:
    def __init__(self, entity: Entity, data: TriggerListenerData) -> None:
        self._hass: Optional[HomeAssistant] = None
        self._entity = entity
        self._data = data

    async def async_added_to_hass(self, hass: HomeAssistant) -> None:
        self._hass = hass

        entity_ids = self._to_entity_ids([
            *self._data.on_entries,
            *self._data.off_entries
        ])

        self._entity.async_on_remove(
            async_track_state_change_event(
                self._hass,
                entity_ids,
                self.trigger_state_change_listener
            )
        )

    @callback
    async def trigger_state_change_listener(
        self,
        event: Event[EventStateChangedData],
    ) -> None:
        # The callback is registered in async_added_to_hass after self._hass is set
        assert self._hass is not None

        if (new_state_data := event.data["new_state"]):

            if self._state_changed_for_entities(new_state_data, self._data.on_entries):
                self._entity.on_trigger_on()

            if self._state_changed_for_entities(new_state_data, self._data.off_entries):
                self._entity.on_trigger_off()

            self._entity.async_write_ha_state()

    def _state_changed_for_entities(self,
                                    new_state: State,
                                    listened_entites: list[RegistryEntry]
                                    ) -> bool:
        triggering_entity_id = new_state.entity_id
        triggered_state = new_state.state

        return (triggering_entity_id in self._to_entity_ids(listened_entites)) and triggered_state == "on"

    def _to_entity_ids(self, entries: list[RegistryEntry]) -> list[str]:
        return [entry.entity_id for entry in entries]
