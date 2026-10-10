"""number.aurora_watch_kp_trigger: the Kp go needs, tunable from the UI.

The one threshold worth changing without a release: whether the oval reaches us depends
on more than Kp, and how far south is worth going out for is a judgement call.
"""

from __future__ import annotations

from dataclasses import replace

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AuroraConfigEntry
from .const import DOMAIN
from .coordinator import AuroraCoordinator
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: AuroraConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([KpTrigger(entry.runtime_data)])


class KpTrigger(RestoreNumber):
    _attr_has_entity_name = True
    _attr_name = "Kp trigger"
    _attr_icon = "mdi:gauge"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 1.0
    _attr_native_max_value = 9.0
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: AuroraCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_kp_trigger"
        self._attr_device_info = device_info()

    @property
    def native_value(self) -> float:
        return self.coordinator.thresholds.kp_reach

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._apply(last.native_value)
            await self.coordinator.async_request_refresh()

    async def async_set_native_value(self, value: float) -> None:
        self._apply(value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    def _apply(self, value: float) -> None:
        self.coordinator.thresholds = replace(self.coordinator.thresholds, kp_reach=round(value, 2))
