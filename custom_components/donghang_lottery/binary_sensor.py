# custom_components/donghang_lottery/binary_sensor.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DonghangLotteryCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    username = hass.data[DOMAIN][entry.entry_id].get("username") or ""

    # 1. 기존 정적 binary sensor
    entities = [
        DonghangLotteryBinarySensor(coordinator, description, entry.entry_id, username)
        for description in BINARY_SENSORS
    ]
    async_add_entities(entities)

    # 2. 구매 내역 동적 binary sensor 트래커
    tracker = DonghangLotteryPurchaseHistoryTracker(
        coordinator, entry.entry_id, username, async_add_entities,
    )
    entry.async_on_unload(
        coordinator.async_add_listener(tracker._handle_coordinator_update)
    )
    # 현재 데이터로 초기 생성
    tracker._handle_coordinator_update()


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


class DonghangLotteryPurchaseHistoryTracker:
    """구매 내역 binary sensor 동적 관리."""

    def __init__(
        self,
        coordinator: DonghangLotteryCoordinator,
        entry_id: str,
        username: str,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        self._coordinator = coordinator
        self._entry_id = entry_id
        self._username = username
        self._async_add_entities = async_add_entities
        self._tracked_ids: set[str] = set()

    def _make_unique_id(self, item: dict[str, Any]) -> str:
        """고유 ID 생성."""
        round_no = item.get("ltEpsdView") or item.get("round", "0")
        barcode = item.get("barcd") or item.get("barCode") or "unknown"
        barcode_suffix = barcode[-6:] if len(barcode) >= 6 else barcode
        item_type = item.get("_type", "unknown")

        if item_type == "lotto645_game":
            game_id = item.get("game_id", "X")
            return f"{self._entry_id}_purchase_{round_no}_lotto645_{game_id}_{barcode_suffix}"
        else:
            return f"{self._entry_id}_purchase_{round_no}_pension720_{barcode_suffix}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """coordinator 데이터 변경시 호출. 새 엔티티 추가."""
        data: DonghangLotteryData | None = self._coordinator.data
        if not data or not data.purchase_ledger:
            return

        new_entities: list[DonghangLotteryPurchaseBinarySensor] = []
        for item in data.purchase_ledger:
            uid = self._make_unique_id(item)
            if uid not in self._tracked_ids:
                self._tracked_ids.add(uid)
                new_entities.append(
                    DonghangLotteryPurchaseBinarySensor(
                        self._coordinator,
                        item,
                        uid,
                        self._entry_id,
                        self._username,
                    )
                )
        if new_entities:
            self._async_add_entities(new_entities)


class DonghangLotteryPurchaseBinarySensor(
    CoordinatorEntity[DonghangLotteryCoordinator], BinarySensorEntity
):
    """구매/당첨 내역 binary sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DonghangLotteryCoordinator,
        item: dict[str, Any],
        unique_id: str,
        entry_id: str,
        username: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._lookup_key = unique_id  # Used to find current data
        self._barcode = item.get("barcd") or item.get("barCode") or ""
        self._game_id = item.get("game_id", "")
        self._item_type = item.get("_type", "unknown")
        self._attr_device_info = device_info_for_group(
            entry_id, username, "purchase_history"
        )

        # Name (computed once, doesn't change)
        round_no = item.get("ltEpsdView") or item.get("game_round") or item.get("round", "")
        gds_nm = item.get("ltGdsNm", "")
        name_parts = [f"{round_no}회", gds_nm]
        if self._game_id:
            name_parts.append(self._game_id)
        self._attr_name = " ".join(name_parts).strip()
        self._attr_icon = "mdi:ticket-confirmation"

        # Store initial item as fallback
        self._initial_item = item

    @property
    def _current_item(self) -> dict[str, Any]:
        """현재 coordinator 데이터에서 매칭되는 항목 찾기."""
        data: DonghangLotteryData | None = self.coordinator.data
        if data and data.purchase_ledger:
            for item in data.purchase_ledger:
                barcode = item.get("barcd") or item.get("barCode") or ""
                if barcode == self._barcode:
                    if self._item_type == "lotto645_game":
                        if item.get("game_id", "") == self._game_id:
                            return item
                    else:
                        return item
        return self._initial_item

    @property
    def is_on(self) -> bool | None:
        """당첨 = True, 미당첨 = False."""
        item = self._current_item
        # 로또6/45 게임별: win_rank 사용 (게임별 정확한 당첨 여부)
        if self._item_type == "lotto645_game":
            win_rank = item.get("win_rank")
            if win_rank is not None:
                return win_rank > 0
        # 그 외: ltWnResult 문자열로 판단
        win_result = item.get("ltWnResult", "")
        if not win_result:
            return None
        return "당첨" in win_result

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._current_item
        attrs: dict[str, Any] = {
            # 구매 내역 (ledger)
            "eltOrdrDt": item.get("eltOrdrDt"),
            "ltGdsNm": item.get("ltGdsNm"),
            "gmInfo": item.get("gmInfo"),
            "prchsQty": item.get("prchsQty"),
            "ltWnResult": item.get("ltWnResult"),
            "ltWnAmt": item.get("ltWnAmt"),
            "epsdRflDt": item.get("epsdRflDt"),
            "ltEpsdView": item.get("ltEpsdView"),
            "barcode": item.get("barcd"),
        }
        # 로또6/45 게임별 상세 (ticket detail)
        if self._item_type == "lotto645_game":
            attrs.update({
                "game_id": item.get("game_id"),
                "numbers": item.get("numbers"),
                "win_rank": item.get("win_rank"),
                "win_amt": item.get("win_amt"),
                "game_type": item.get("game_type"),
                "win_num": item.get("win_num"),
                "game_round": item.get("game_round"),
                "drawed": item.get("drawed"),
                "draw_date": item.get("draw_date"),
                "sale_date": item.get("sale_date"),
                "win_total_amt": item.get("win_total_amt"),
            })
        return attrs
