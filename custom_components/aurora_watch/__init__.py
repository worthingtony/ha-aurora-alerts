"""Aurora Watch: substorm-based aurora alerts from NOAA SWPC real-time data."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import AuroraCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

type AuroraConfigEntry = ConfigEntry[AuroraCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AuroraConfigEntry) -> bool:
    coordinator = AuroraCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AuroraConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
