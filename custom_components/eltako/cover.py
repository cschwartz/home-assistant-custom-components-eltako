"""Cover for Eltako devices."""

from collections.abc import Callable
from dataclasses import dataclass
import logging

from datetime import datetime, timedelta
from typing import Any, Literal, Optional
import voluptuous as vol

from xknx.devices import TravelStatus

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_time_interval,
)
from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_CURRENT_TILT_POSITION,
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    PLATFORM_SCHEMA,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import (
    CONF_DEVICES,
    CONF_NAME,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_STOP_COVER,
    STATE_CLOSING,
    STATE_OPENING,
    STATE_CLOSED,
    STATE_OPEN,
)


import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.reload import async_setup_reload_service

from . import DOMAIN
from .config import devices_from_config
from .const import (
    CONF_VIRTUAL_SWITCH,
    CONF_TIME_DOWN,
    CONF_TIME_UP,
    CONF_TILTING_TIME,
    CONF_TRAVELING_TIME,
    CONF_SWITCH_LISTENERS,
)
from .switch_listener import (
    SWITCH_LISTENER_SCHEMA,
    SwitchListenerData,
    from_switch_listener_config,
    SwitchListener,
)
from .switch_user import (
    SWITCH_SCHEMA,
    SwitchUserData,
    SwitchUser,
    from_switch_user_config,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM = "cover"

DEFAULT_TRAVEL_TIME = 30
DEFAULT_TILTING_TIME = 5


TIME_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TIME_UP): cv.time_period_seconds,
        vol.Optional(CONF_TIME_DOWN): cv.time_period_seconds,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_DEVICES, default={}): vol.Schema(
            {
                cv.string: {
                    vol.Optional(CONF_NAME): cv.string,
                    vol.Required(CONF_SWITCH_LISTENERS): SWITCH_LISTENER_SCHEMA,
                    vol.Required(CONF_VIRTUAL_SWITCH): SWITCH_SCHEMA,
                    vol.Required(CONF_TRAVELING_TIME): TIME_SCHEMA,
                    vol.Optional(CONF_TILTING_TIME): TIME_SCHEMA,
                }
            }
        ),
    }
)


@dataclass(frozen=True, kw_only=True)
class TimeData:
    up: timedelta
    down: timedelta


CoverCommand = Literal["open_cover"] | Literal["close_cover"] | Literal["stop_cover"]


class EltakoCoverTimeBased(CoverEntity, RestoreEntity):

    def __init__(
        self,
        device_id: str,
        name: str,
        switch_user_data: SwitchUserData,
        switch_listener_data: SwitchListenerData,
        traveling_time_data: TimeData,
        tilting_time_data: Optional[TimeData] = None,
    ) -> None:
        """Initialize the cover."""
        from xknx.devices import TravelCalculator

        self._attr_unique_id = device_id
        self._attr_name = name
        self._attr_device_class = None

        self._unsubscribe_auto_updater: Optional[Callable[[], None]] = None

        self._switch_user = SwitchUser(switch_user_data)
        self._switch_listener = SwitchListener(self, switch_listener_data)

        self.travel_calc = TravelCalculator(
            travel_time_down=traveling_time_data.down.total_seconds(),
            travel_time_up=traveling_time_data.up.total_seconds(),
        )

        self.tilt_calc = (
            TravelCalculator(
                travel_time_down=tilting_time_data.down.total_seconds(),
                travel_time_up=tilting_time_data.up.total_seconds(),
            )
            if tilting_time_data is not None
            else None
        )

    def on_switch_off(self) -> None:
        if self.state == STATE_OPENING:
            self._handle_stop()
        elif self.state in (STATE_CLOSING, STATE_CLOSED) or (
            self.state == STATE_OPEN
            and self.current_cover_position is not None
            and self.current_cover_position < 100
        ):
            self.travel_calc.start_travel_up()
            self.start_auto_updater()
            self._update_tilt_before_travel(SERVICE_OPEN_COVER)

    def on_switch_on(self) -> None:
        if self.state == STATE_CLOSING:
            self._handle_stop()
        elif self.state in (STATE_OPENING, STATE_OPEN):
            self.travel_calc.start_travel_down()
            self.start_auto_updater()
            self._update_tilt_before_travel(SERVICE_CLOSE_COVER)

    async def async_added_to_hass(self) -> None:
        """Only cover's position and tilt matters."""
        old_state = await self.async_get_last_state()
        _LOGGER.debug("async_added_to_hass :: oldState %s", old_state)
        if (
            old_state is not None
            and self.travel_calc is not None
            and (old_position := old_state.attributes.get(ATTR_CURRENT_POSITION))
            is not None
        ):
            self.travel_calc.set_position(100 - int(old_position))

            if (
                self._has_tilt_support()
                and (
                    old_tilt_position := old_state.attributes.get(
                        ATTR_CURRENT_TILT_POSITION
                    )
                )
                is not None
            ):
                self.tilt_calc.set_position(100 - int(old_tilt_position))

        await self._switch_listener.async_added_to_hass(
            self.hass, self.on_switch_on, self.on_switch_off
        )

    def _handle_stop(self) -> None:
        """Handle stop"""
        if self.travel_calc.is_traveling():
            _LOGGER.debug("_handle_stop :: button stops cover movement")
            self.travel_calc.stop()
            self.stop_auto_updater()

        if self._has_tilt_support() and self.tilt_calc.is_traveling():
            _LOGGER.debug("_handle_stop :: button stops tilt movement")
            self.tilt_calc.stop()
            self.stop_auto_updater()

    @property
    def current_cover_position(self) -> Optional[int]:
        """Return the current position of the cover."""
        if (current_position := self.travel_calc.current_position()) is not None:
            return 100 - current_position
        else:
            return None

    @property
    def current_cover_tilt_position(self) -> Optional[int]:
        """Return the current tilt of the cover."""
        if self._has_tilt_support() and (
            current_position := self.tilt_calc.current_position()
        ):
            return 100 - current_position
        else:
            return None

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening or not."""
        return (
            self.travel_calc.is_traveling()
            and self.travel_calc.travel_direction == TravelStatus.DIRECTION_UP
        ) or (
            self._has_tilt_support()
            and self.tilt_calc.is_traveling()
            and self.tilt_calc.travel_direction == TravelStatus.DIRECTION_UP
        )

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing or not."""
        from xknx.devices import TravelStatus

        return (
            self.travel_calc.is_traveling()
            and self.travel_calc.travel_direction == TravelStatus.DIRECTION_DOWN
        ) or (
            self._has_tilt_support()
            and self.tilt_calc.is_traveling()
            and self.tilt_calc.travel_direction == TravelStatus.DIRECTION_DOWN
        )

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        return self.travel_calc.is_closed()

    @property
    def assumed_state(self) -> bool:
        """Return True because covers can be stopped midway."""
        return True

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Flag supported features."""
        supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        )
        if self.current_cover_position is not None:
            supported_features |= CoverEntityFeature.SET_POSITION

        if self._has_tilt_support():
            supported_features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.STOP_TILT
            )
            if self.current_cover_tilt_position is not None:
                supported_features |= CoverEntityFeature.SET_TILT_POSITION

        return supported_features

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        if ATTR_POSITION in kwargs:
            position = kwargs[ATTR_POSITION]
            _LOGGER.debug("async_set_cover_position: %d", position)
            await self.set_position(position)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Move the cover tilt to a specific position."""
        if ATTR_TILT_POSITION in kwargs:
            position = kwargs[ATTR_TILT_POSITION]
            _LOGGER.debug("async_set_cover_tilt_position: %d", position)
            await self.set_tilt_position(position)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Turn the device close."""
        _LOGGER.debug("async_close_cover")
        if (
            current_position := self.travel_calc.current_position()
        ) is not None and current_position < 100:
            self.travel_calc.start_travel_down()
            self.start_auto_updater()
            self._update_tilt_before_travel(SERVICE_CLOSE_COVER)
            await self._async_handle_command(SERVICE_CLOSE_COVER)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Turn the device open."""
        _LOGGER.debug("async_open_cover")
        if (
            current_position := self.travel_calc.current_position()
        ) is not None and current_position > 0:
            self.travel_calc.start_travel_up()
            self.start_auto_updater()
            self._update_tilt_before_travel(SERVICE_OPEN_COVER)
            await self._async_handle_command(SERVICE_OPEN_COVER)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Turn the device close."""
        _LOGGER.debug("async_close_cover_tilt")
        if (
            current_tilt := self.tilt_calc.current_position()
        ) is not None and current_tilt < 100:
            self.tilt_calc.start_travel_down()
            self.start_auto_updater()
            await self._async_handle_command(SERVICE_CLOSE_COVER)

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Turn the device open."""
        _LOGGER.debug("async_open_cover_tilt")
        if (
            current_tilt := self.tilt_calc.current_position()
        ) is not None and current_tilt > 0:
            self.tilt_calc.start_travel_up()
            self.start_auto_updater()
            await self._async_handle_command(SERVICE_OPEN_COVER)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Turn the device stop."""
        _LOGGER.debug("async_stop_cover")
        await self._async_handle_command(SERVICE_STOP_COVER)
        self._handle_stop()

    async def set_position(self, target_position: int) -> None:
        """Move cover to a designated position."""
        _LOGGER.debug("set_position")
        if (calc_position := self.travel_calc.current_position()) is not None:
            current_position = 100 - calc_position
            _LOGGER.debug(
                "set_position :: current_position: %d, new_position: %d",
                current_position,
                target_position,
            )
            command: Optional[CoverCommand] = None
            if target_position < current_position:
                command = SERVICE_CLOSE_COVER
            elif target_position > current_position:
                command = SERVICE_OPEN_COVER

            if command is not None:
                self.start_auto_updater()
                self.travel_calc.start_travel(100 - target_position)
                _LOGGER.debug("set_position :: command %s", command)
                self._update_tilt_before_travel(command)
                await self._async_handle_command(command)

    async def set_tilt_position(self, target_position: int) -> None:
        """Move cover tilt to a designated position."""
        _LOGGER.debug("set_tilt_position")
        if (calc_position := self.tilt_calc.current_position()) is not None:
            current_position = 100 - calc_position
            _LOGGER.debug(
                "set_tilt_position :: current_position: %d, new_position: %d",
                current_position,
                target_position,
            )
            command: Optional[CoverCommand] = None
            if target_position < current_position:
                command = SERVICE_CLOSE_COVER
            elif target_position > current_position:
                command = SERVICE_OPEN_COVER

            if command is not None:
                self.start_auto_updater()
                self.tilt_calc.start_travel(100 - target_position)
                _LOGGER.debug("set_tilt_position :: command %s", command)
                await self._async_handle_command(command)

    def start_auto_updater(self) -> None:
        """Start the autoupdater to update HASS while cover is moving."""
        _LOGGER.debug("start_auto_updater")
        if self._unsubscribe_auto_updater is None:
            _LOGGER.debug("init _unsubscribe_auto_updater")
            interval = timedelta(seconds=0.1)
            self._unsubscribe_auto_updater = async_track_time_interval(
                self.hass, self.auto_updater_hook, interval
            )

    @callback
    def auto_updater_hook(self, now: datetime) -> None:
        """Call for the autoupdater."""
        _LOGGER.debug("auto_updater_hook")
        self.async_schedule_update_ha_state()
        if self.position_reached():
            _LOGGER.debug("auto_updater_hook :: position_reached")
            self.stop_auto_updater()
        self.hass.async_create_task(self.auto_stop_if_necessary())

    def stop_auto_updater(self) -> None:
        """Stop the autoupdater."""
        _LOGGER.debug("stop_auto_updater")
        if self._unsubscribe_auto_updater is not None:
            self._unsubscribe_auto_updater()
            self._unsubscribe_auto_updater = None

    def position_reached(self) -> bool:
        """Return if cover has reached its final position."""
        return self.travel_calc.position_reached() and (
            not self._has_tilt_support() or self.tilt_calc.position_reached()
        )

    def _has_tilt_support(self) -> bool:
        """Return if cover has tilt support."""
        return self.tilt_calc is not None

    def _update_tilt_before_travel(self, command: CoverCommand) -> None:
        """Updating tilt before travel."""
        if self._has_tilt_support():
            _LOGGER.debug("_update_tilt_before_travel :: command %s", command)
            if command == SERVICE_OPEN_COVER:
                self.tilt_calc.set_position(0)
            elif command == SERVICE_CLOSE_COVER:
                self.tilt_calc.set_position(100)

    async def auto_stop_if_necessary(self) -> None:
        """Do auto stop if necessary."""
        if self.position_reached():
            _LOGGER.debug("auto_stop_if_necessary :: calling stop command")
            self.travel_calc.stop()
            if self._has_tilt_support():
                self.tilt_calc.stop()
            await self._async_handle_command(SERVICE_STOP_COVER)

    async def _async_handle_command(self, command: CoverCommand) -> None:
        if command == SERVICE_CLOSE_COVER:
            await self._switch_user.push_on(self.hass)
        elif command == SERVICE_OPEN_COVER:
            await self._switch_user.push_off(self.hass)
        elif command == SERVICE_STOP_COVER:
            if not self._cover_is_last_toggle_direction_open:
                await self._switch_user.push_on(self.hass)
            if self._cover_is_last_toggle_direction_open:
                await self._switch_user.push_off(self.hass)

        self.async_write_ha_state()


def from_time_config_or_none(config: Optional[ConfigType]) -> Optional[TimeData]:
    if config is not None:
        return from_time_config(config)
    else:
        return None


def from_time_config(config: ConfigType) -> TimeData:
    return TimeData(up=config[CONF_TIME_UP], down=config[CONF_TIME_DOWN])


def from_config(
    entity_registry: er.EntityRegistry, id: str, config: ConfigType
) -> EltakoCoverTimeBased:
    return EltakoCoverTimeBased(
        id,
        name=config[CONF_NAME],
        switch_user_data=from_switch_user_config(
            entity_registry, config[CONF_VIRTUAL_SWITCH]
        ),
        switch_listener_data=from_switch_listener_config(
            entity_registry, config[CONF_SWITCH_LISTENERS]
        ),
        traveling_time_data=from_time_config(config[CONF_TRAVELING_TIME]),
        tilting_time_data=from_time_config_or_none(config.get(CONF_TILTING_TIME)),
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    await async_setup_reload_service(hass, DOMAIN, [PLATFORM])
    async_add_entities(devices_from_config(hass, from_config, config))
