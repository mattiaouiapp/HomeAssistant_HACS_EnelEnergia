"""Sensors for the enelgrid integration.

The real consumption history lives in the external statistics imported by the
coordinator (use those in the Energy dashboard). These sensors only show a
summary of the latest data downloaded from Enel.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, ENEL_TZ
from .coordinator import EnelGridConfigEntry, EnelGridCoordinator
from .parser import ConsumptionSummary, first_of_month
from .statistics import CURRENCY, normalize_pod

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EnelGridSensorDescription(SensorEntityDescription):
    value_fn: Callable[[EnelGridCoordinator, ConsumptionSummary], Any]
    attrs_fn: Callable[[EnelGridCoordinator, ConsumptionSummary], dict[str, Any]] | None = None
    legacy_object_id: str | None = None


def _month_start() -> datetime:
    today = dt_util.now(ENEL_TZ).date()
    return datetime.combine(first_of_month(today), time(), ENEL_TZ)


SENSORS: tuple[EnelGridSensorDescription, ...] = (
    EnelGridSensorDescription(
        key="monthly_consumption",
        translation_key="monthly_consumption",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda c, d: d.current_month_kwh,
        legacy_object_id="monthly_consumption",
    ),
    EnelGridSensorDescription(
        key="previous_month_consumption",
        translation_key="previous_month_consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda c, d: d.previous_month_kwh,
    ),
    EnelGridSensorDescription(
        key="last_day_consumption",
        translation_key="last_day_consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda c, d: d.last_day_kwh,
        attrs_fn=lambda c, d: {"date": d.last_day.isoformat() if d.last_day else None},
    ),
    EnelGridSensorDescription(
        key="monthly_cost",
        translation_key="monthly_cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY,
        suggested_display_precision=2,
        value_fn=lambda c, d: round(d.current_month_kwh * c.price_per_kwh, 2),
        attrs_fn=lambda c, d: {"price_per_kwh": c.price_per_kwh},
    ),
    EnelGridSensorDescription(
        key="last_reading",
        translation_key="last_reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, d: d.last_reading_end,
        attrs_fn=lambda c, d: {"historical_import": c.historical_status},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnelGridConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(EnelGridSensor(coordinator, description) for description in SENSORS)


class EnelGridSensor(CoordinatorEntity[EnelGridCoordinator], SensorEntity):
    """Summary sensor for one POD."""

    _attr_has_entity_name = True
    entity_description: EnelGridSensorDescription

    def __init__(self, coordinator: EnelGridCoordinator, description: EnelGridSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        pod = coordinator.pod
        pod_id = normalize_pod(pod)
        self._attr_unique_id = f"{pod_id}_{description.key}"
        if description.legacy_object_id:
            # Keep the entity_id used by v1.x so dashboards keep working.
            self.entity_id = f"sensor.enelgrid_{pod_id}_{description.legacy_object_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, pod)},
            name=f"Enel {pod}",
            manufacturer="Enel",
            model="POD",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.enel.it/it/area-clienti",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator, self.coordinator.data)

    @property
    def last_reset(self) -> datetime | None:
        if self.entity_description.state_class == SensorStateClass.TOTAL:
            return _month_start()
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator, self.coordinator.data)
