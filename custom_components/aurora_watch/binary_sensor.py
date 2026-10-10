"""Binary sensors: dark_enough (sun below -12 deg at the selected spot) and
loading_incoming (south Bz measured at L1 that has not reached Earth yet)."""

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
    async_add_entities([DarkEnough(entry.runtime_data), LoadingIncoming(entry.runtime_data)])


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


class LoadingIncoming(CoordinatorEntity[AuroraCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Loading incoming"
    _attr_icon = "mdi:weather-windy-variant"

    def __init__(self, coordinator: AuroraCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_loading_incoming"
        self._attr_device_info = device_info()

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.incoming

    @property
    def extra_state_attributes(self) -> dict:
        r = self.coordinator.data
        return {"arrives": r.incoming_at.isoformat() if r.incoming_at else None, "reason": r.incoming_reason}
