# custom_components/donghang_lottery/binary_sensor.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DonghangLotteryCoordinator, DonghangLotteryData
from .device import device_info_for_group


@dataclass(frozen=True)
class DonghangLotteryBinarySensorDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[DonghangLotteryData], bool] | None = None
    device_group: str = "account"


BINARY_SENSORS: tuple[DonghangLotteryBinarySensorDescription, ...] = (
    DonghangLotteryBinarySensorDescription(
        key="has_balance",
        translation_key="has_balance",
        icon="mdi:wallet-outline",
        is_on_fn=lambda data: data.account.total_amount > 0,
        device_group="account",
    ),
    DonghangLotteryBinarySensorDescription(
        key="lotto645_has_first_winner",
        translation_key="lotto645_has_first_winner",
        icon="mdi:trophy-award",
        is_on_fn=lambda data: _get_lotto645_first_winners(data) > 0,
        device_group="lotto",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DonghangLotteryCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    username = hass.data[DOMAIN][entry.entry_id].get("username") or ""
    entities = [
        DonghangLotteryBinarySensor(coordinator, description, entry.entry_id, username)
        for description in BINARY_SENSORS
    ]
    async_add_entities(entities)


class DonghangLotteryBinarySensor(
    CoordinatorEntity[DonghangLotteryCoordinator], BinarySensorEntity
):
    entity_description: DonghangLotteryBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DonghangLotteryCoordinator,
        description: DonghangLotteryBinarySensorDescription,
        entry_id: str,
        username: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info_for_group(
            entry_id,
            username,
            description.device_group,
        )

    @property
    def is_on(self) -> bool | None:
        data: DonghangLotteryData | None = self.coordinator.data
        if not data:
            return None
        is_on_fn = self.entity_description.is_on_fn
        if is_on_fn is None:
            return None
        return is_on_fn(data)


def _get_lotto645_item(data: DonghangLotteryData) -> dict[str, Any]:
    result = data.lotto645_result or {}
    # api.py returns {drwNo, ..., _raw: {ltEpsd, tm1WnNo, rnk1WnNope, ...}}
    # 센서는 원본 API 키(rnk1WnNope 등)를 사용하므로 _raw 반환
    if "_raw" in result:
        return result["_raw"]
    # 폴백: 중첩된 응답 구조 탐색
    payload = result.get("data", result)
    if isinstance(payload, dict):
        items = payload.get("list") or payload.get("result") or payload.get("data")
        if isinstance(items, list) and items:
            return items[0]
        if isinstance(items, dict):
            return items
        return payload
    if isinstance(payload, list) and payload:
        return payload[0]
    return {}


def _get_lotto645_first_winners(data: DonghangLotteryData) -> int:
    item = _get_lotto645_item(data)
    value = item.get("rnk1WnNope")
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0
