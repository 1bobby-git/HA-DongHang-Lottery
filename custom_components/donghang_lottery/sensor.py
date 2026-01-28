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
from homeassistant.config_entries import ConfigEntry
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
        icon="mdi:help-circle-outline",
        value_fn=lambda data: data.account.unconfirmed_count,
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="unclaimed_high_value_count",
        translation_key="unclaimed_high_value",
        icon="mdi:cash-clock",
        value_fn=lambda data: data.account.unclaimed_high_value_count,
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="has_unclaimed_prizes",
        translation_key="has_unclaimed_prizes",
        icon="mdi:cash-multiple",
        value_fn=lambda data: "있음" if data.account.unclaimed_high_value_count > 0 else "없음",
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="has_unconfirmed_games",
        translation_key="has_unconfirmed_games",
        icon="mdi:help-circle-outline",
        value_fn=lambda data: "있음" if data.account.unconfirmed_count > 0 else "없음",
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="last_update",
        translation_key="last_update",
        icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="next_update",
        translation_key="next_update",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_group="account",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_round",
        translation_key="lotto645_round",
        icon="mdi:counter",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("ltEpsd")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_number1",
        translation_key="lotto645_number1",
        icon="mdi:numeric-1-circle",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("tm1WnNo")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_number2",
        translation_key="lotto645_number2",
        icon="mdi:numeric-2-circle",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("tm2WnNo")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_number3",
        translation_key="lotto645_number3",
        icon="mdi:numeric-3-circle",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("tm3WnNo")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_number4",
        translation_key="lotto645_number4",
        icon="mdi:numeric-4-circle",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("tm4WnNo")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_number5",
        translation_key="lotto645_number5",
        icon="mdi:numeric-5-circle",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("tm5WnNo")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_number6",
        translation_key="lotto645_number6",
        icon="mdi:numeric-6-circle",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("tm6WnNo")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_bonus",
        translation_key="lotto645_bonus",
        icon="mdi:star-circle",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("bnsWnNo")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_draw_date",
        translation_key="lotto645_draw_date",
        icon="mdi:calendar",
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
        icon="mdi:account-star",
        value_fn=lambda data: _format_with_commas(_get_lotto645_item(data).get("rnk1WnNope")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_second_winners",
        translation_key="lotto645_second_winners",
        icon="mdi:account-star-outline",
        value_fn=lambda data: _format_with_commas(_get_lotto645_item(data).get("rnk2WnNope")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_third_winners",
        translation_key="lotto645_third_winners",
        icon="mdi:account-outline",
        value_fn=lambda data: _format_with_commas(_get_lotto645_item(data).get("rnk3WnNope")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_total_winners",
        translation_key="lotto645_total_winners",
        icon="mdi:account-group",
        value_fn=lambda data: _format_with_commas(_get_lotto645_item(data).get("sumWnNope")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="lotto645_sales_amount",
        translation_key="lotto645_sales_amount",
        icon="mdi:chart-line",
        native_unit_of_measurement="KRW",
        value_fn=lambda data: _safe_int(_get_lotto645_item(data).get("rlvtEpsdSumNtslAmt")),
        device_group="lotto",
    ),
    DonghangLotterySensorDescription(
        key="pension720_round",
        translation_key="pension720_round",
        icon="mdi:counter",
        value_fn=lambda data: data.pension720_round
        or _safe_int(_get_pension720_item(data).get("psltEpsd")),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_draw_date",
        translation_key="pension720_draw_date",
        icon="mdi:calendar",
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
            _first_present(_get_pension720_item(data), ["rnk1WnAmt", "wnAmt", "wnAmt1", "winAmt1"])
        ),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_first_winners",
        translation_key="pension720_first_winners",
        icon="mdi:account-star",
        value_fn=lambda data: _safe_int(
            _first_present(_get_pension720_item(data), ["rnk1WnNope", "wnTotalCnt", "wnNope1", "winNope1", "wnCnt1"])
        ),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_group",
        translation_key="pension720_group",
        icon="mdi:label",
        value_fn=lambda data: _first_present(_get_pension720_item(data), ["wnBndNo", "wnRnk", "wnGroup"]),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_number1",
        translation_key="pension720_number1",
        icon="mdi:numeric-1-circle",
        value_fn=lambda data: _get_pension_digit(_get_pension720_item(data), 0),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_number2",
        translation_key="pension720_number2",
        icon="mdi:numeric-2-circle",
        value_fn=lambda data: _get_pension_digit(_get_pension720_item(data), 1),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_number3",
        translation_key="pension720_number3",
        icon="mdi:numeric-3-circle",
        value_fn=lambda data: _get_pension_digit(_get_pension720_item(data), 2),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_number4",
        translation_key="pension720_number4",
        icon="mdi:numeric-4-circle",
        value_fn=lambda data: _get_pension_digit(_get_pension720_item(data), 3),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_number5",
        translation_key="pension720_number5",
        icon="mdi:numeric-5-circle",
        value_fn=lambda data: _get_pension_digit(_get_pension720_item(data), 4),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_number6",
        translation_key="pension720_number6",
        icon="mdi:numeric-6-circle",
        value_fn=lambda data: _get_pension_digit(_get_pension720_item(data), 5),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_bonus_group",
        translation_key="pension720_bonus_group",
        icon="mdi:label-outline",
        value_fn=lambda data: _first_present(_get_pension720_bonus_item(data), ["wnBndNo", "wnRnk", "wnGroup"]) or "각 조",
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_bonus_number1",
        translation_key="pension720_bonus_number1",
        icon="mdi:numeric-1-circle-outline",
        value_fn=lambda data: _get_pension_digit(_get_pension720_bonus_item(data), 0),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_bonus_number2",
        translation_key="pension720_bonus_number2",
        icon="mdi:numeric-2-circle-outline",
        value_fn=lambda data: _get_pension_digit(_get_pension720_bonus_item(data), 1),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_bonus_number3",
        translation_key="pension720_bonus_number3",
        icon="mdi:numeric-3-circle-outline",
        value_fn=lambda data: _get_pension_digit(_get_pension720_bonus_item(data), 2),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_bonus_number4",
        translation_key="pension720_bonus_number4",
        icon="mdi:numeric-4-circle-outline",
        value_fn=lambda data: _get_pension_digit(_get_pension720_bonus_item(data), 3),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_bonus_number5",
        translation_key="pension720_bonus_number5",
        icon="mdi:numeric-5-circle-outline",
        value_fn=lambda data: _get_pension_digit(_get_pension720_bonus_item(data), 4),
        device_group="pension",
    ),
    DonghangLotterySensorDescription(
        key="pension720_bonus_number6",
        translation_key="pension720_bonus_number6",
        icon="mdi:numeric-6-circle-outline",
        value_fn=lambda data: _get_pension_digit(_get_pension720_bonus_item(data), 5),
        device_group="pension",
    ),
    # === 내 주변 로또 당첨 판매점 ===
    DonghangLotterySensorDescription(
        key="lotto_shop_name",
        translation_key="lotto_shop_name",
        icon="mdi:store",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _get_lotto_shop(data).get("shpNm"),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_address",
        translation_key="lotto_shop_address",
        icon="mdi:map-marker",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _get_lotto_shop(data).get("shpAddr"),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_distance",
        translation_key="lotto_shop_distance",
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement="km",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _get_lotto_shop(data).get("distance_km"),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_phone",
        translation_key="lotto_shop_phone",
        icon="mdi:phone",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _format_phone(_get_lotto_shop(data).get("shpTelno")),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_win_type",
        translation_key="lotto_shop_win_type",
        icon="mdi:ticket-confirmation",
        value_fn=lambda data: _get_lotto_shop(data).get("atmtPsvYnTxt"),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_win_rank",
        translation_key="lotto_shop_win_rank",
        icon="mdi:trophy",
        value_fn=lambda data: _format_win_rank(_get_lotto_shop(data).get("wnShpRnk")),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_sells_lotto645",
        translation_key="lotto_shop_sells_lotto645",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_lotto_shop(data).get("l645LtNtslYn")),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_sells_pension720",
        translation_key="lotto_shop_sells_pension720",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_lotto_shop(data).get("pt720NtslYn")),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_sells_speetto500",
        translation_key="lotto_shop_sells_speetto500",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_lotto_shop(data).get("st5LtNtslYn")),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_sells_speetto1000",
        translation_key="lotto_shop_sells_speetto1000",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_lotto_shop(data).get("st10LtNtslYn")),
        device_group="lotto_shop",
    ),
    DonghangLotterySensorDescription(
        key="lotto_shop_sells_speetto2000",
        translation_key="lotto_shop_sells_speetto2000",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_lotto_shop(data).get("st20LtNtslYn")),
        device_group="lotto_shop",
    ),
    # === 내 주변 연금복권 당첨 판매점 ===
    DonghangLotterySensorDescription(
        key="pension_shop_name",
        translation_key="pension_shop_name",
        icon="mdi:store",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _get_pension_shop(data).get("shpNm"),
        device_group="pension_shop",
    ),
    DonghangLotterySensorDescription(
        key="pension_shop_address",
        translation_key="pension_shop_address",
        icon="mdi:map-marker",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _get_pension_shop(data).get("shpAddr"),
        device_group="pension_shop",
    ),
    DonghangLotterySensorDescription(
        key="pension_shop_distance",
        translation_key="pension_shop_distance",
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement="km",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _get_pension_shop(data).get("distance_km"),
        device_group="pension_shop",
    ),
    DonghangLotterySensorDescription(
        key="pension_shop_phone",
        translation_key="pension_shop_phone",
        icon="mdi:phone",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _format_phone(_get_pension_shop(data).get("shpTelno")),
        device_group="pension_shop",
    ),
    DonghangLotterySensorDescription(
        key="pension_shop_win_rank",
        translation_key="pension_shop_win_rank",
        icon="mdi:trophy",
        value_fn=lambda data: _format_win_rank(_get_pension_shop(data).get("wnShpRnk")),
        device_group="pension_shop",
    ),
    DonghangLotterySensorDescription(
        key="pension_shop_sells_lotto645",
        translation_key="pension_shop_sells_lotto645",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_pension_shop(data).get("l645LtNtslYn")),
        device_group="pension_shop",
    ),
    DonghangLotterySensorDescription(
        key="pension_shop_sells_pension720",
        translation_key="pension_shop_sells_pension720",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_pension_shop(data).get("pt720LtNtslYn")),
        device_group="pension_shop",
    ),
    DonghangLotterySensorDescription(
        key="pension_shop_sells_speetto500",
        translation_key="pension_shop_sells_speetto500",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_pension_shop(data).get("st5LtNtslYn")),
        device_group="pension_shop",
    ),
    DonghangLotterySensorDescription(
        key="pension_shop_sells_speetto1000",
        translation_key="pension_shop_sells_speetto1000",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_pension_shop(data).get("st10LtNtslYn")),
        device_group="pension_shop",
    ),
    DonghangLotterySensorDescription(
        key="pension_shop_sells_speetto2000",
        translation_key="pension_shop_sells_speetto2000",
        icon="mdi:ticket",
        value_fn=lambda data: _format_yn(_get_pension_shop(data).get("st20LtNtslYn")),
        device_group="pension_shop",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DonghangLotteryCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    username = hass.data[DOMAIN][entry.entry_id].get("username") or ""

    # 정적 센서
    entities: list[SensorEntity] = [
        DonghangLotterySensor(coordinator, description, entry.entry_id, username)
        for description in SENSORS
    ]

    # 구매 내역 센서 (복권 종류별 고정 2개)
    entities.append(DonghangLotteryPurchaseHistorySensor(
        coordinator, entry.entry_id, username, "lotto645",
    ))
    entities.append(DonghangLotteryPurchaseHistorySensor(
        coordinator, entry.entry_id, username, "pension720",
    ))

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
        """진단 속성 - 모든 센서에 연결 상태, last_update 센서에 원시 데이터."""
        attrs: dict[str, Any] = {
            "data_source": self.coordinator.data_source,
            "data_loaded": self.coordinator._data_loaded,
        }
        if self.coordinator.last_error:
            attrs["last_error"] = self.coordinator.last_error

        # "최근 업데이트" 센서에만 전체 진단 + 원시 데이터 추가
        if self.entity_description.key == "last_update":
            # 클라이언트 연결 상태
            try:
                attrs["circuit_breaker"] = self.coordinator.client._circuit_state
                attrs["consecutive_failures"] = self.coordinator.client._consecutive_failures
                attrs["logged_in"] = self.coordinator.client._logged_in
            except Exception:
                pass

            # 원시 API 데이터
            data: DonghangLotteryData | None = self.coordinator.data
            if data:
                attrs["account_total_amount"] = data.account.total_amount
                attrs["account_unconfirmed_count"] = data.account.unconfirmed_count
                attrs["account_unclaimed_high_value"] = data.account.unclaimed_high_value_count
                attrs["lotto645_raw"] = data.lotto645_result if data.lotto645_result else None
                attrs["pension720_raw"] = data.pension720_result if data.pension720_result else None
                attrs["pension720_round"] = data.pension720_round

        return attrs


def _get_lotto645_item(data: DonghangLotteryData) -> dict[str, Any]:
    result = data.lotto645_result or {}
    # api.py returns {drwNo, drwtNo1, ..., _raw: {ltEpsd, tm1WnNo, ...}}
    # 센서는 원본 API 키(ltEpsd, tm1WnNo 등)를 사용하므로 _raw 반환
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


def _get_pension720_item(data: DonghangLotteryData) -> dict[str, Any]:
    result = data.pension720_result or {}
    # API 응답: {resultCode, resultMessage, data: {result: [{...}, ...]}}
    # 여러 회차의 등수별 항목이 포함됨 (wnSqNo: 1=1등, 2=2등, ..., 7=7등, 21=보너스)
    inner = result.get("data") or result
    if isinstance(inner, dict):
        items = inner.get("result") or inner.get("list")
        if isinstance(items, list) and items:
            # 1등 항목 우선 선택 (wnSqNo == 1)
            for item in items:
                if item.get("wnSqNo") == 1:
                    return item
            return items[0]
        return inner
    if isinstance(inner, list) and inner:
        return inner[0]
    return {}


def _get_pension720_bonus_item(data: DonghangLotteryData) -> dict[str, Any]:
    """연금복권720+ 보너스 당첨 항목 (wnSqNo == 21)."""
    result = data.pension720_result or {}
    inner = result.get("data") or result
    if isinstance(inner, dict):
        items = inner.get("result") or inner.get("list")
        if isinstance(items, list):
            for item in items:
                if item.get("wnSqNo") == 21:
                    return item
    if isinstance(inner, list):
        for item in inner:
            if isinstance(item, dict) and item.get("wnSqNo") == 21:
                return item
    return {}


def _get_pension_digit(item: dict[str, Any], position: int) -> int | None:
    """연금복권 번호에서 특정 위치의 숫자 추출."""
    value = _first_present(item, ["wnRnkVl", "wnNo", "wnNumber", "wnNum"])
    if value is None:
        return None
    text = str(value).strip()
    if position < len(text):
        try:
            return int(text[position])
        except ValueError:
            return None
    return None


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


def _format_with_commas(value: Any) -> str | None:
    """천 단위 콤마 포맷."""
    n = _safe_int(value)
    if n is None:
        return None
    return f"{n:,}"


def _first_present(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _get_lotto_shop(data: DonghangLotteryData) -> dict[str, Any]:
    """로또6/45 가장 가까운 당첨 판매점 데이터."""
    return data.nearest_lotto_shop or {}


def _get_pension_shop(data: DonghangLotteryData) -> dict[str, Any]:
    """연금복권720+ 가장 가까운 당첨 판매점 데이터."""
    return data.nearest_pension_shop or {}


def _format_phone(value: Any) -> str | None:
    """전화번호 포맷: '0212345678' → '02-1234-5678'."""
    if value is None:
        return None
    phone = str(value).strip()
    if not phone:
        return None
    if "-" in phone:
        return phone
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        return None
    # 서울 (02)
    if digits.startswith("02"):
        if len(digits) == 10:
            return f"{digits[:2]}-{digits[2:6]}-{digits[6:]}"
        elif len(digits) == 9:
            return f"{digits[:2]}-{digits[2:5]}-{digits[5:]}"
    # 기타 지역 (0XX)
    elif digits.startswith("0"):
        if len(digits) == 11:
            return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
        elif len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return phone


def _format_win_rank(value: Any) -> str | None:
    """당첨 등수 포맷: 1 → '1등', 2 → '2등'."""
    if value is None:
        return None
    try:
        rank = int(value)
        return f"{rank}등"
    except (ValueError, TypeError):
        return str(value)


def _format_yn(value: Any) -> str | None:
    """Y/N → 있음/없음 변환."""
    if value is None:
        return None
    v = str(value).strip().upper()
    if v == "Y":
        return "있음"
    elif v == "N":
        return "없음"
    return str(value)


def _format_pension_gm_info(gm_info: str) -> str:
    """연금복권 게임정보 포맷: '1:603973' → '1조 6,0,3,9,7,3'."""
    if not gm_info or ":" not in gm_info:
        return gm_info or ""
    parts = gm_info.split(":", 1)
    group = parts[0]
    number = parts[1] if len(parts) > 1 else ""
    digits = ",".join(number)
    return f"{group}조 {digits}"


class DonghangLotteryPurchaseHistorySensor(
    CoordinatorEntity[DonghangLotteryCoordinator], SensorEntity
):
    """복권 종류별 구매/당첨 내역 센서."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DonghangLotteryCoordinator,
        entry_id: str,
        username: str,
        lottery_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._lottery_type = lottery_type
        self._attr_unique_id = f"{entry_id}_purchase_history_{lottery_type}"
        self._attr_device_info = device_info_for_group(
            entry_id, username, "purchase_history"
        )
        if lottery_type == "lotto645":
            self._attr_name = "로또6/45 구매내역"
            self._attr_icon = "mdi:clover"
        else:
            self._attr_name = "연금복권720+ 구매내역"
            self._attr_icon = "mdi:cash-clock"

    def _get_items(self) -> list[dict[str, Any]]:
        """현재 데이터에서 해당 복권 종류의 구매 항목 추출."""
        data: DonghangLotteryData | None = self.coordinator.data
        if not data or not data.purchase_ledger:
            return []
        if self._lottery_type == "lotto645":
            return [i for i in data.purchase_ledger if i.get("_type", "").startswith("lotto645")]
        else:
            return [i for i in data.purchase_ledger if i.get("_type") == "pension720"]

    @property
    def native_value(self) -> int:
        """상태값: 구매 건수."""
        items = self._get_items()
        if self._lottery_type == "lotto645":
            # 로또: 티켓(바코드) 기준 건수 (게임이 아닌 티켓 수)
            barcodes = set()
            for item in items:
                bc = item.get("barcd") or item.get("barCode") or ""
                if bc:
                    barcodes.add(bc)
            return len(barcodes) if barcodes else len(items)
        return len(items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = self._get_items()
        if self._lottery_type == "lotto645":
            return self._format_lotto645_attrs(items)
        return self._format_pension720_attrs(items)

    def _format_lotto645_attrs(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """로또6/45 구매 내역을 티켓별로 그룹화."""
        # 바코드별로 게임 그룹화
        tickets: dict[str, dict[str, Any]] = {}
        for item in items:
            bc = item.get("barcd") or item.get("barCode") or "unknown"
            if bc not in tickets:
                tickets[bc] = {
                    "회차": item.get("ltEpsdView") or item.get("game_round"),
                    "구매일": item.get("sale_date") or item.get("eltOrdrDt"),
                    "추첨일": item.get("draw_date"),
                    "추첨여부": item.get("drawed"),
                    "당첨번호": item.get("win_num"),
                    "총당첨금": item.get("win_total_amt", 0),
                    "바코드": bc,
                    "게임": [],
                }
            # 게임 상세 추가
            game_id = item.get("game_id")
            if game_id:
                win_rank = item.get("win_rank", 0)
                tickets[bc]["게임"].append({
                    "ID": game_id,
                    "번호": item.get("numbers", []),
                    "등수": win_rank,
                    "결과": f"{win_rank}등" if win_rank > 0 else "미당첨",
                    "당첨금": item.get("win_amt", 0),
                })

        ticket_list = list(tickets.values())
        return {
            "총건수": len(ticket_list),
            "내역": ticket_list,
        }

    def _format_pension720_attrs(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """연금복권720+ 구매 내역 포맷."""
        entries = []
        for item in items:
            gm_info = item.get("gmInfo", "")
            lt_wn_amt = item.get("ltWnAmt")
            entries.append({
                "회차": item.get("ltEpsdView"),
                "주문일시": item.get("eltOrdrDt"),
                "게임정보": _format_pension_gm_info(gm_info) if gm_info else "",
                "당첨결과": item.get("ltWnResult") or "",
                "당첨금액": lt_wn_amt if lt_wn_amt is not None else 0,
            })
        return {
            "총건수": len(entries),
            "내역": entries,
        }
