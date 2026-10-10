"""number.aurora_watch_kp_trigger: the Kp go needs, tunable from the UI, per saved spot.

The one threshold worth changing without a release: whether the oval reaches us depends
on more than Kp, and how far south is worth going out for is a judgement call. A dark
site sees fainter aurora, so it can take a lower trigger than home.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AuroraConfigEntry
from .const import DOMAIN
from .coordinator import AuroraCoordinator
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: AuroraConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([KpTrigger(entry.runtime_data)])


class KpTrigger(NumberEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = "Kp trigger"
    _attr_icon = "mdi:gauge"
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

    @property
    def extra_state_attributes(self) -> dict:
        return {"location": self.coordinator.location, "per_location": dict(self.coordinator.kp_by_location)}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            saved = last.attributes.get("per_location") or {}
            if not saved and last.state not in ("unknown", "unavailable"):
                saved = {last.attributes.get("location", "zone.home"): float(last.state)}  # v1 kept one value
            self.coordinator.kp_by_location.update({k: float(v) for k, v in saved.items()})
            self.coordinator.set_location(self.coordinator.location)
            await self.coordinator.async_request_refresh()
        self.async_on_remove(self.coordinator.async_add_listener(self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()  # the location may have changed

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_kp(value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
