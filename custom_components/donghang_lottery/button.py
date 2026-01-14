# custom_components/donghang_lottery/button.py

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DonghangLotteryCoordinator
from .device import device_info_for_group


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DonghangLotteryCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    username = hass.data[DOMAIN][entry.entry_id].get("username") or ""
    async_add_entities([DonghangLotteryUpdateButton(coordinator, entry.entry_id, username)])


class DonghangLotteryUpdateButton(CoordinatorEntity[DonghangLotteryCoordinator], ButtonEntity):
    _attr_translation_key = "update"
    _attr_has_entity_name = True

    def __init__(self, coordinator: DonghangLotteryCoordinator, entry_id: str, username: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_update"
        self._attr_device_info = device_info_for_group(entry_id, username, "account")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
