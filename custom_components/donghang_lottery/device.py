# custom_components/donghang_lottery/device.py

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def device_name_account(username: str) -> str:
    if username:
        return f"동행복권 ({username})"
    return "동행복권"


def device_name_lotto() -> str:
    return "로또6/45"


def device_name_pension() -> str:
    return "연금복권720+"


def device_name_lotto_shop() -> str:
    return "내 주변 로또 당첨 판매점"


def device_name_pension_shop() -> str:
    return "내 주변 연금복권 당첨 판매점"


def device_name_purchase_history() -> str:
    return "구매/당첨내역"


def device_info_for_group(entry_id: str, username: str, group: str) -> DeviceInfo:
    if group == "lotto":
        name = device_name_lotto()
    elif group == "pension":
        name = device_name_pension()
    elif group == "lotto_shop":
        name = device_name_lotto_shop()
    elif group == "pension_shop":
        name = device_name_pension_shop()
    elif group == "purchase_history":
        name = device_name_purchase_history()
    else:
        name = device_name_account(username)

    return DeviceInfo(
        identifiers={(DOMAIN, entry_id, group)},
        name=name,
        manufacturer="DHLottery",
    )
