"""binary_sensor.aurora_watch_dark_enough: sun below -12 deg (nautical dusk)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AuroraConfigEntry
from .const import DOMAIN
from .coordinator import AuroraCoordinator
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: AuroraConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([DarkEnough(entry.runtime_data)])


class DarkEnough(CoordinatorEntity[AuroraCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Dark enough"
    _attr_icon = "mdi:weather-night"

    def __init__(self, coordinator: AuroraCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_dark_enough"
        self._attr_device_info = device_info()

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.dark
