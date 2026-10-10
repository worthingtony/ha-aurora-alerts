"""select.aurora_watch_location: which saved spot darkness and the Kp trigger are for.

Spots are Home Assistant zones (Settings - Areas, labels and zones - Zones), so adding
one needs no change here. Home is zone.home.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import AuroraConfigEntry
from .const import DOMAIN, HOME_ZONE
from .coordinator import AuroraCoordinator
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: AuroraConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([LocationSelect(entry.runtime_data)])


class LocationSelect(SelectEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = "Location"
    _attr_icon = "mdi:map-marker-star"

    def __init__(self, coordinator: AuroraCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_location"
        self._attr_device_info = device_info()

    def _zones(self) -> dict[str, str]:
        """Friendly name -> zone entity id, home first."""
        zones = {s.name: s.entity_id for s in self.hass.states.async_all("zone") if s.entity_id != HOME_ZONE}
        home = self.hass.states.get(HOME_ZONE)
        return {(home.name if home else "Home"): HOME_ZONE} | dict(sorted(zones.items()))

    @property
    def options(self) -> list[str]:
        return list(self._zones())

    @property
    def current_option(self) -> str | None:
        return next((name for name, zone in self._zones().items() if zone == self.coordinator.location), None)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"zone": self.coordinator.location}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        zone = last.attributes.get("zone") if last else None
        if zone and self.hass.states.get(zone) is not None:
            self.coordinator.set_location(zone)
        self.async_on_remove(self.coordinator.async_add_listener(self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()  # zones may have been added or renamed

    async def async_select_option(self, option: str) -> None:
        self.coordinator.set_location(self._zones()[option])
        self.coordinator.async_update_listeners()  # the Kp box shows the new spot's value now
        await self.coordinator.async_request_refresh()
