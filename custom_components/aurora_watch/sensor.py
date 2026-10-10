"""Sensors. Entity ids come out as sensor.aurora_watch_<name>."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AuroraConfigEntry
from .const import ATTRIBUTION, DOMAIN, NAME
from .coordinator import AuroraCoordinator
from .engine import STATUSES, Result

NT = "nT"


@dataclass(frozen=True, kw_only=True)
class AuroraSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Result], Any]
    attrs_fn: Callable[[Result], dict[str, Any]] | None = None


def _status_attrs(r: Result) -> dict[str, Any]:
    return {
        "reasons": r.reasons,
        "fresh": r.fresh,
        "loaded": r.loaded,
        "strong_driving": r.strong,
        "shock": r.shock,
        "onset": r.onset,
        "watch": r.watch,
        "watch_reason": r.watch_reason,
        "kp_trigger": r.kp_reach,
        "goes_satellite": r.goes_satellite,
        "goes_night_side": r.goes_night_side,
        "location": r.location,
        "sun_elevation": None if r.sun_elevation is None else round(r.sun_elevation, 1),
        "incoming": r.incoming,
        "glendale_onset": r.glendale_onset,
        "go_started": r.go_started.isoformat() if r.go_started else None,
        "go_ended": r.go_ended.isoformat() if r.go_ended else None,
    }


def _alert_attrs(r: Result) -> dict[str, Any]:
    if r.alert is None:
        return {}
    return {"issued": r.alert.issued.isoformat(), "product_id": r.alert.product_id, "message": r.alert.message}


def _measure(key: str, name: str, unit: str | None, fn: Callable[[Result], Any], precision: int = 1, **kw: Any) -> AuroraSensorDescription:
    return AuroraSensorDescription(
        key=key, name=name, native_unit_of_measurement=unit, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=precision, value_fn=fn, **kw,
    )


SENSORS: tuple[AuroraSensorDescription, ...] = (
    AuroraSensorDescription(
        key="status", name="Status", device_class=SensorDeviceClass.ENUM, options=STATUSES,
        icon="mdi:aurora", value_fn=lambda r: r.status, attrs_fn=_status_attrs,
    ),
    _measure("bz", "Bz", NT, lambda r: r.bz, icon="mdi:magnet"),
    _measure("bt", "Bt", NT, lambda r: r.bt, icon="mdi:magnet"),
    # No device_class: HA has no km/s unit, and SPEED would offer to convert this to mph.
    _measure("speed", "Solar wind speed", "km/s", lambda r: r.speed, 0, icon="mdi:weather-windy"),
    _measure("density", "Solar wind density", "p/cm³", lambda r: r.density, icon="mdi:grain"),
    _measure("bz_south_fraction", "Bz south fraction", PERCENTAGE,
             lambda r: None if r.bz_south_fraction is None else round(r.bz_south_fraction * 100), 0, icon="mdi:arrow-down-bold"),
    _measure("minutes_south", "Minutes south", UnitOfTime.MINUTES, lambda r: r.minutes_south, 0, icon="mdi:timer-sand"),
    _measure("goes_hp", "GOES Hp", NT, lambda r: r.hp, icon="mdi:satellite-variant",
             attrs_fn=lambda r: {"satellite": r.goes_satellite, "night_side": r.goes_night_side}),
    _measure("kp", "Kp estimated", None, lambda r: r.kp, 2, icon="mdi:gauge"),
    _measure("g_now", "G scale now", None, lambda r: r.g_now, 0, icon="mdi:alpha-g-box"),
    _measure("g_forecast", "G scale tonight", None, lambda r: r.g_forecast, 0, icon="mdi:alpha-g-box-outline"),
    _measure("data_age", "Data age", UnitOfTime.MINUTES, lambda r: r.data_age_min, 0, icon="mdi:clock-alert-outline"),
    AuroraSensorDescription(key="glendale", name="Glendale", icon="mdi:alarm-light-outline",
                            value_fn=lambda r: r.glendale.text[:255] if r.glendale else None,
                            attrs_fn=lambda r: {"posted": r.glendale.posted.isoformat(), "level": r.glendale.level} if r.glendale else {}),
    AuroraSensorDescription(key="alert", name="SWPC alert", icon="mdi:alert-outline",
                            value_fn=lambda r: r.alert.headline[:255] if r.alert else None, attrs_fn=_alert_attrs),
)


async def async_setup_entry(hass: HomeAssistant, entry: AuroraConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AuroraSensor(coordinator, d) for d in SENSORS)


def device_info() -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, DOMAIN)}, name=NAME, manufacturer="NOAA SWPC", entry_type=DeviceEntryType.SERVICE)


class AuroraSensor(CoordinatorEntity[AuroraCoordinator], SensorEntity):
    _attr_has_entity_name = True
    # The alert's full text is for the dashboard, not for history.
    _unrecorded_attributes = frozenset({"message"})
    _attr_attribution = ATTRIBUTION
    entity_description: AuroraSensorDescription

    def __init__(self, coordinator: AuroraCoordinator, description: AuroraSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"
        self._attr_device_info = device_info()

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None
