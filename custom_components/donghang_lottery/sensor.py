# custom_components/donghang_lottery/sensor.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DonghangLotteryCoordinator, DonghangLotteryData
from .device import device_info_for_group


@dataclass(frozen=True)
class DonghangLotterySensorDescription(SensorEntityDescription):
    value_attr: str | None = None
    value_fn: Callable[[DonghangLotteryData], Any] | None = None
    device_group: str = "account"


SENSORS: tuple[DonghangLotterySensorDescription, ...] = (
    DonghangLotterySensorDescription(
        key="total_amount",
        translation_key="balance",
        icon="mdi:wallet",
        native_unit_of_measurement="KRW",
        value_fn=lambda data: data.account.total_amount,
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="unconfirmed_count",
        translation_key="unconfirmed_games",
        icon="mdi:help-circle",
        value_fn=lambda data: data.account.unconfirmed_count,
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="unclaimed_high_value_count",
        translation_key="unclaimed_high_value",
        icon="mdi:alert-circle",
        value_fn=lambda data: data.account.unclaimed_high_value_count,
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="next_update",
        translation_key="next_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_round",
        translation_key="lotto645_round",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("ltEpsd")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_numbers",
        translation_key="lotto645_numbers",
        value_fn=lambda data: _format_numbers(_get_lotto645_numbers(_get_lotto645_item(data))),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_bonus",
        translation_key="lotto645_bonus",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("bnsWnNo")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_draw_date",
        translation_key="lotto645_draw_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: _parse_yyyymmdd(_get_lotto645_item(data).get("ltRflYmd")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_first_prize",
        translation_key="lotto645_first_prize",
        icon="mdi:trophy",
        native_unit_of_measurement="KRW",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("rnk1WnAmt")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_first_winners",
        translation_key="lotto645_first_winners",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("rnk1WnNope")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_second_winners",
        translation_key="lotto645_second_winners",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("rnk2WnNope")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_third_winners",
        translation_key="lotto645_third_winners",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("rnk3WnNope")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_total_winners",
        translation_key="lotto645_total_winners",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("sumWnNope")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_sales_amount",
        translation_key="lotto645_sales_amount",
        native_unit_of_measurement="KRW",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("rlvtEpsdSumNtslAmt")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="pension720_round",
        translation_key="pension720_round",
        value_fn=lambda data: data.pension720_round
        or _safe_int(_get_pension720_item(data).get("psltEpsd")),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_draw_date",
        translation_key="pension720_draw_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: _parse_yyyymmdd(
            _first_present(_get_pension720_item(data), ["drwDate", "drwYmd", "psltRflYmd"])
        ),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_first_prize",
        translation_key="pension720_first_prize",
        icon="mdi:trophy",
        native_unit_of_measurement="KRW",
        value_fn=lambda data: _safe_int(
            _first_present(_get_pension720_item(data), ["rnk1WnAmt", "wnAmt1", "winAmt1"])
        ),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_first_winners",
        translation_key="pension720_first_winners",
        value_fn=lambda data: _safe_int(
            _first_present(_get_pension720_item(data), ["rnk1WnNope", "wnNope1", "winNope1", "wnCnt1"])
        ),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_group",
        translation_key="pension720_group",
        value_fn=lambda data: _first_present(_get_pension720_item(data), ["wnRnkVl", "wnRnk", "wnGroup"]),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_number",
        translation_key="pension720_number",
        value_fn=lambda data: _first_present(_get_pension720_item(data), ["wnNo", "wnNumber", "wnNum"]),
        device_group="pension",
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
        DonghangLotterySensor(coordinator, description, entry.entry_id, username)
        for description in SENSORS
    ]
    async_add_entities(entities)


class DonghangLotterySensor(CoordinatorEntity[DonghangLotteryCoordinator], SensorEntity):
    entity_description: DonghangLotterySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DonghangLotteryCoordinator,
        description: DonghangLotterySensorDescription,
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
    def native_value(self) -> Any:
        if self.entity_description.key == "last_update":
            return self.coordinator.last_update_time
        if self.entity_description.key == "next_update":
            return self.coordinator.next_update_time
        data: DonghangLotteryData | None = self.coordinator.data
        if not data:
            return None
        value_fn = self.entity_description.value_fn
        if value_fn is None:
            return None
        return value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """진단 속성 - 원시 API 데이터 및 연결 상태 노출."""
        if self.entity_description.key != "last_update":
            return None

        attrs: dict[str, Any] = {}

        # 코디네이터 진단 정보
        attrs.update(self.coordinator.debug_info)

        # 원시 API 데이터
        data: DonghangLotteryData | None = self.coordinator.data
        if data:
            # 계정 데이터
            attrs["account_total_amount"] = data.account.total_amount
            attrs["account_unconfirmed_count"] = data.account.unconfirmed_count
            attrs["account_unclaimed_high_value"] = data.account.unclaimed_high_value_count

            # 로또 645 원시 결과
            if data.lotto645_result:
                attrs["lotto645_raw"] = data.lotto645_result
            else:
                attrs["lotto645_raw"] = None

            # 연금복권 720 원시 결과
            if data.pension720_result:
                attrs["pension720_raw"] = data.pension720_result
            else:
                attrs["pension720_raw"] = None

            # 연금복권 720 회차
            attrs["pension720_round"] = data.pension720_round

        return attrs


def _get_lotto645_item(data: DonghangLotteryData) -> dict[str, Any]:
    result = data.lotto645_result or {}
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


def _get_lotto645_numbers(item: dict[str, Any]) -> list[int]:
    numbers = []
    for key in ("tm1WnNo", "tm2WnNo", "tm3WnNo", "tm4WnNo", "tm5WnNo", "tm6WnNo"):
        value = _safe_int(item.get(key))
        if value:
            numbers.append(value)
    return numbers


def _get_pension720_item(data: DonghangLotteryData) -> dict[str, Any]:
    result = data.pension720_result or {}
    payload = result.get("result") or result.get("data") or result
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload:
        return payload[0]
    return {}


def _parse_yyyymmdd(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) != 8 or not text.isdigit():
        return None
    year = int(text[0:4])
    month = int(text[4:6])
    day = int(text[6:8])
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _format_numbers(numbers: list[int]) -> str | None:
    if not numbers:
        return None
    return ", ".join(str(num) for num in numbers)


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _first_present(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None
