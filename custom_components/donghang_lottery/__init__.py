# custom_components/donghang_lottery/__init__.py
"""동행복권 Home Assistant 통합 - v0.7.0 당첨발표 스케줄 기반 업데이트."""

from __future__ import annotations

import aiohttp
import asyncio
import logging
import math
import ssl
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval

from .api import DonghangLotteryClient, DonghangLotteryError
from .const import (
    ATTR_CITY,
    ATTR_COUNT,
    ATTR_DISTRICT,
    ATTR_DRAW_NO,
    ATTR_END_DATE,
    ATTR_ENTRY_ID,
    ATTR_LIMIT,
    ATTR_LOCATION_ENTITY,
    ATTR_LOTTO520,
    ATTR_LOTTO645,
    ATTR_LOTTERY_TYPE,
    ATTR_MAX_DISTANCE,
    ATTR_MODE,
    ATTR_NUMBERS,
    ATTR_PAGE_NUM,
    ATTR_PAGE_SIZE,
    ATTR_PENSION720,
    ATTR_RANK,
    ATTR_REGION,
    ATTR_SPEETTO10,
    ATTR_SPEETTO20,
    ATTR_SPEETTO5,
    ATTR_START_DATE,
    ATTR_USE_MY_NUMBERS,
    ATTR_WIN_RESULT,
    CONF_LOCATION_ENTITY,
    CONF_LOTTO_UPDATE_HOUR,
    CONF_PENSION_UPDATE_HOUR,
    CONF_USE_PROXY,
    DEFAULT_LOTTO_UPDATE_HOUR,
    DEFAULT_MAX_REQUEST_INTERVAL,
    DEFAULT_MIN_REQUEST_INTERVAL,
    DEFAULT_PENSION_UPDATE_HOUR,
    DEFAULT_USE_PROXY,
    DOMAIN,
    LOTTERY_LOTTO645,
    LOTTERY_PENSION720,
    MODE_AUTO,
    MODE_MANUAL,
    SERVICE_BUY_LOTTO645,
    SERVICE_BUY_PENSION720,
    SERVICE_CHECK_LOTTO645_NUMBERS,
    SERVICE_CHECK_PENSION720_NUMBERS,
    SERVICE_FETCH_LOTTO645_RESULT,
    SERVICE_FETCH_NEXT_DRAW_INFO,
    SERVICE_FETCH_PENSION720_RESULT,
    SERVICE_FETCH_PURCHASE_LEDGER,
    SERVICE_FETCH_WINNING_SHOPS,
    SERVICE_GET_MY_NUMBERS,
    SERVICE_REFRESH_ACCOUNT,
    SERVICE_SEARCH_LOTTERY_SHOPS,
    SERVICE_SET_MY_NUMBERS,
)
from .coordinator import DonghangLotteryCoordinator
from .storage import MyNumberStore


LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "binary_sensor", "button"]

# 세션 유지를 위한 keepalive (사이트 세션 유효 시간: 30분)
KEEPALIVE_INTERVAL = timedelta(minutes=30)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    username = entry.options.get(CONF_USERNAME, entry.data.get(CONF_USERNAME))
    password = entry.options.get(CONF_PASSWORD, entry.data.get(CONF_PASSWORD))

    # 차단 방지 설정 (내부 기본값 사용)
    min_interval = DEFAULT_MIN_REQUEST_INTERVAL
    max_interval = DEFAULT_MAX_REQUEST_INTERVAL
    # 프록시 설정 (IP 차단 우회 - 기본값 True)
    use_proxy = entry.options.get(
        CONF_USE_PROXY,
        entry.data.get(CONF_USE_PROXY, DEFAULT_USE_PROXY),
    )

    # 당첨발표 업데이트 시간 설정
    lotto_update_hour = entry.options.get(
        CONF_LOTTO_UPDATE_HOUR,
        entry.data.get(CONF_LOTTO_UPDATE_HOUR, DEFAULT_LOTTO_UPDATE_HOUR),
    )
    pension_update_hour = entry.options.get(
        CONF_PENSION_UPDATE_HOUR,
        entry.data.get(CONF_PENSION_UPDATE_HOUR, DEFAULT_PENSION_UPDATE_HOUR),
    )

    # 커스텀 aiohttp 세션 (TLS 핑거프린트 차별화, 연결 제어)
    ssl_context = ssl.create_default_context()
    connector = aiohttp.TCPConnector(
        limit=10,
        limit_per_host=3,
        ttl_dns_cache=300,
        force_close=False,
        enable_cleanup_closed=True,
        ssl=ssl_context,
    )
    session = aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(
            total=60,
            connect=15,
            sock_connect=15,
            sock_read=30,
        ),
        cookie_jar=aiohttp.CookieJar(),
    )
    client = DonghangLotteryClient(
        session,
        username,
        password,
        min_request_interval=min_interval,
        max_request_interval=max_interval,
        use_proxy=use_proxy,
    )
    coordinator = DonghangLotteryCoordinator(
        hass, client,
        lotto_update_hour=lotto_update_hour,
        pension_update_hour=pension_update_hour,
    )

    # 최초 데이터 로드 - 실패 시 ConfigEntryNotReady 전파 (센서 미등록)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # 실패 시 커스텀 세션 정리
        await session.close()
        raise

    # 데이터 로드 성공 → 센서 등록 진행
    store = MyNumberStore(hass, entry.entry_id)
    await store.async_load()

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "store": store,
        "session": session,
        "keepalive_unsub": None,
        "username": username,
        "location_entity": entry.options.get(
            CONF_LOCATION_ENTITY, entry.data.get(CONF_LOCATION_ENTITY, "")
        ),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _keepalive(now) -> None:
        try:
            await client.async_keepalive()
        except DonghangLotteryError as err:
            LOGGER.debug("Keepalive failed: %s", err)

    hass.data[DOMAIN][entry.entry_id]["keepalive_unsub"] = async_track_time_interval(
        hass,
        _keepalive,
        KEEPALIVE_INTERVAL,
    )

    if not hass.data[DOMAIN].get("services_registered"):
        _register_services(hass)
        hass.data[DOMAIN]["services_registered"] = True

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].get(entry.entry_id, {})
        # keepalive 타이머 취소
        unsub = data.get("keepalive_unsub")
        if unsub:
            unsub()
        # 코디네이터 스케줄된 업데이트 취소
        coordinator = data.get("coordinator")
        if coordinator:
            coordinator.async_cancel_scheduled_update()
        # 커스텀 세션 정리
        custom_session = data.get("session")
        if custom_session:
            await custom_session.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_ACCOUNT,
        _handle_refresh_account,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_BUY_LOTTO645,
        _handle_buy_lotto645,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ENTRY_ID): cv.string,
                vol.Optional(ATTR_COUNT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
                vol.Optional(ATTR_MODE, default=MODE_AUTO): vol.In([MODE_AUTO, MODE_MANUAL]),
                vol.Optional(ATTR_NUMBERS): list,
                vol.Optional(ATTR_USE_MY_NUMBERS, default=False): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_BUY_PENSION720,
        _handle_buy_pension720,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ENTRY_ID): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FETCH_LOTTO645_RESULT,
        _handle_fetch_lotto645_result,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_DRAW_NO): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FETCH_PENSION720_RESULT,
        _handle_fetch_pension720_result,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_DRAW_NO): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FETCH_WINNING_SHOPS,
        _handle_fetch_winning_shops,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ENTRY_ID): cv.string,
                vol.Optional(ATTR_LOTTERY_TYPE, default=LOTTERY_LOTTO645): vol.In(
                    [LOTTERY_LOTTO645, LOTTERY_PENSION720, "st"]
                ),
                vol.Optional(ATTR_RANK, default="1"): cv.string,
                vol.Optional(ATTR_DRAW_NO): cv.string,
                vol.Optional(ATTR_REGION, default=""): cv.string,
                vol.Optional(ATTR_LOCATION_ENTITY, default=""): cv.string,
                vol.Optional(ATTR_MAX_DISTANCE, default=30): vol.Coerce(float),
                vol.Optional(ATTR_LIMIT, default=30): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MY_NUMBERS,
        _handle_set_my_numbers,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ENTRY_ID): cv.string,
                vol.Optional(ATTR_LOTTERY_TYPE, default=LOTTERY_LOTTO645): vol.In(
                    [LOTTERY_LOTTO645, LOTTERY_PENSION720]
                ),
                vol.Required(ATTR_NUMBERS): list,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MY_NUMBERS,
        _handle_get_my_numbers,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ENTRY_ID): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHECK_LOTTO645_NUMBERS,
        _handle_check_lotto645_numbers,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ENTRY_ID): cv.string,
                vol.Optional(ATTR_DRAW_NO): vol.Coerce(int),
                vol.Optional(ATTR_NUMBERS): list,
                vol.Optional(ATTR_USE_MY_NUMBERS, default=False): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHECK_PENSION720_NUMBERS,
        _handle_check_pension720_numbers,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ENTRY_ID): cv.string,
                vol.Optional(ATTR_DRAW_NO): vol.Coerce(int),
                vol.Optional(ATTR_NUMBERS): list,
                vol.Optional(ATTR_USE_MY_NUMBERS, default=False): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FETCH_NEXT_DRAW_INFO,
        _handle_fetch_next_draw_info,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ENTRY_ID): cv.string,
                vol.Optional(ATTR_LOTTERY_TYPE, default=LOTTERY_LOTTO645): vol.In(
                    [LOTTERY_LOTTO645, LOTTERY_PENSION720]
                ),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FETCH_PURCHASE_LEDGER,
        _handle_fetch_purchase_ledger,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ENTRY_ID): cv.string,
                vol.Optional(ATTR_START_DATE): cv.string,
                vol.Optional(ATTR_END_DATE): cv.string,
                vol.Optional(ATTR_LOTTERY_TYPE): cv.string,
                vol.Optional(ATTR_WIN_RESULT): cv.string,
                vol.Optional(ATTR_PAGE_NUM, default=1): vol.Coerce(int),
                vol.Optional(ATTR_PAGE_SIZE, default=10): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH_LOTTERY_SHOPS,
        _handle_search_lottery_shops,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CITY): cv.string,
                vol.Required(ATTR_DISTRICT): cv.string,
                vol.Optional(ATTR_LOTTO645, default=False): cv.boolean,
                vol.Optional(ATTR_LOTTO520, default=False): cv.boolean,
                vol.Optional(ATTR_SPEETTO5, default=False): cv.boolean,
                vol.Optional(ATTR_SPEETTO10, default=False): cv.boolean,
                vol.Optional(ATTR_SPEETTO20, default=False): cv.boolean,
                vol.Optional(ATTR_PENSION720, default=False): cv.boolean,
                vol.Optional(ATTR_PAGE_NUM, default=1): vol.Coerce(int),
                vol.Optional(ATTR_PAGE_SIZE, default=10): vol.Coerce(int),
                vol.Optional(ATTR_LOCATION_ENTITY): cv.string,
                vol.Optional(ATTR_MAX_DISTANCE): vol.Coerce(float),
                vol.Optional(ATTR_LIMIT): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )


def _get_entry(hass: HomeAssistant, call: ServiceCall) -> ConfigEntry:
    entry_id = call.data.get(ATTR_ENTRY_ID)
    if entry_id:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == entry_id:
                return entry
        raise DonghangLotteryError(f"Entry not found: {entry_id}")

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise DonghangLotteryError("No donghang_lottery entries configured")
    return entries[0]


def _get_entry_data(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    return hass.data[DOMAIN][entry.entry_id]


async def _handle_refresh_account(call: ServiceCall) -> None:
    hass = call.hass
    entry = _get_entry(hass, call)
    coordinator: DonghangLotteryCoordinator = _get_entry_data(hass, entry)["coordinator"]
    await coordinator.async_request_refresh()


async def _handle_buy_lotto645(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    entry = _get_entry(hass, call)
    data = _get_entry_data(hass, entry)
    client: DonghangLotteryClient = data["client"]
    store: MyNumberStore = data["store"]

    mode = call.data.get(ATTR_MODE, MODE_AUTO)
    count = call.data.get(ATTR_COUNT, 1)
    use_my_numbers = call.data.get(ATTR_USE_MY_NUMBERS, False)
    numbers = call.data.get(ATTR_NUMBERS)

    if use_my_numbers:
        numbers = store.data.lotto645
        mode = MODE_MANUAL if numbers else MODE_AUTO

    if mode == MODE_MANUAL:
        if not numbers:
            raise DonghangLotteryError("Manual mode requires numbers")
        result = await client.async_buy_lotto645_manual(_normalize_lotto_numbers(numbers))
    else:
        result = await client.async_buy_lotto645_auto(count)

    await data["coordinator"].async_request_refresh()
    return {"result": result}


async def _handle_buy_pension720(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    entry = _get_entry(hass, call)
    data = _get_entry_data(hass, entry)
    client: DonghangLotteryClient = data["client"]
    result = await client.async_buy_pension720_auto_result()
    await data["coordinator"].async_request_refresh()
    return {"result": result}


async def _handle_fetch_lotto645_result(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    entry = _get_entry(hass, call)
    client: DonghangLotteryClient = _get_entry_data(hass, entry)["client"]
    draw_no = call.data.get(ATTR_DRAW_NO)
    result = await client.async_get_lotto645_result(draw_no)
    return {"result": result}


async def _handle_fetch_pension720_result(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    entry = _get_entry(hass, call)
    client: DonghangLotteryClient = _get_entry_data(hass, entry)["client"]
    draw_no = call.data.get(ATTR_DRAW_NO)
    result = await client.async_get_pension720_result(draw_no)
    return {"result": result}


async def _handle_fetch_winning_shops(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    entry = _get_entry(hass, call)
    data = _get_entry_data(hass, entry)
    client: DonghangLotteryClient = data["client"]

    lottery_type = call.data.get(ATTR_LOTTERY_TYPE, LOTTERY_LOTTO645)
    rank = call.data.get(ATTR_RANK, "1")
    round_no = call.data.get(ATTR_DRAW_NO)
    region = call.data.get(ATTR_REGION, "")

    if not round_no:
        round_no = str(await client.async_get_latest_winning_shop_round(lottery_type))

    shops = await client.async_get_winning_shops(lottery_type, rank, round_no, region)
    items = shops.get("list") or shops.get("data") or shops.get("result") or []

    location_entity = call.data.get(ATTR_LOCATION_ENTITY) or data.get("location_entity")
    max_distance = call.data.get(ATTR_MAX_DISTANCE)
    limit = call.data.get(ATTR_LIMIT)

    if location_entity:
        state = hass.states.get(location_entity)
        if state:
            lat = state.attributes.get("latitude")
            lon = state.attributes.get("longitude")
            if lat is not None and lon is not None:
                items = _filter_by_distance(items, lat, lon, max_distance, limit)

    return {"result": items, "round_no": round_no, "lottery_type": lottery_type}


async def _handle_set_my_numbers(call: ServiceCall) -> None:
    hass = call.hass
    entry = _get_entry(hass, call)
    data = _get_entry_data(hass, entry)
    store: MyNumberStore = data["store"]

    lottery_type = call.data.get(ATTR_LOTTERY_TYPE, LOTTERY_LOTTO645)
    numbers = call.data.get(ATTR_NUMBERS) or []

    if lottery_type == LOTTERY_LOTTO645:
        store.data.lotto645 = _normalize_lotto_numbers(numbers)
    else:
        store.data.pension720 = [str(item) for item in numbers]

    await store.async_save()


async def _handle_get_my_numbers(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    entry = _get_entry(hass, call)
    store: MyNumberStore = _get_entry_data(hass, entry)["store"]
    return {"lotto645": store.data.lotto645, "pension720": store.data.pension720}


async def _handle_check_lotto645_numbers(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    entry = _get_entry(hass, call)
    data = _get_entry_data(hass, entry)
    client: DonghangLotteryClient = data["client"]
    store: MyNumberStore = data["store"]

    draw_no = call.data.get(ATTR_DRAW_NO)
    numbers = call.data.get(ATTR_NUMBERS)
    if call.data.get(ATTR_USE_MY_NUMBERS, False):
        numbers = store.data.lotto645
    numbers = _normalize_lotto_numbers(numbers or [])

    result = await client.async_get_lotto645_result(draw_no)
    win_info = _extract_lotto645_win_info(result)
    checked = _check_lotto645_numbers(win_info, numbers)
    return {"result": checked, "draw_no": win_info["draw_no"]}


async def _handle_check_pension720_numbers(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    entry = _get_entry(hass, call)
    data = _get_entry_data(hass, entry)
    client: DonghangLotteryClient = data["client"]
    store: MyNumberStore = data["store"]

    draw_no = call.data.get(ATTR_DRAW_NO)
    if draw_no is None:
        draw_no = await client.async_get_latest_pension720_round()

    numbers = call.data.get(ATTR_NUMBERS)
    if call.data.get(ATTR_USE_MY_NUMBERS, False):
        numbers = store.data.pension720
    numbers = [str(item) for item in numbers or []]

    result = await client.async_check_pension720_numbers(draw_no, numbers)
    return {"result": result, "draw_no": draw_no}


async def _handle_fetch_next_draw_info(call: ServiceCall) -> dict[str, Any]:
    """다음 회차 추첨 정보 조회 서비스 핸들러."""
    hass = call.hass
    entry = _get_entry(hass, call)
    client: DonghangLotteryClient = _get_entry_data(hass, entry)["client"]

    lottery_type = call.data.get(ATTR_LOTTERY_TYPE, LOTTERY_LOTTO645)

    result = await client.async_get_next_draw_info(lottery_type)
    return {"result": result, "lottery_type": lottery_type}


async def _handle_fetch_purchase_ledger(call: ServiceCall) -> dict[str, Any]:
    """구매 내역 조회 서비스 핸들러."""
    hass = call.hass
    entry = _get_entry(hass, call)
    client: DonghangLotteryClient = _get_entry_data(hass, entry)["client"]

    start_date = call.data.get(ATTR_START_DATE)
    end_date = call.data.get(ATTR_END_DATE)
    lottery_type = call.data.get(ATTR_LOTTERY_TYPE)
    win_result = call.data.get(ATTR_WIN_RESULT)
    page_num = call.data.get(ATTR_PAGE_NUM, 1)
    page_size = call.data.get(ATTR_PAGE_SIZE, 10)

    result = await client.async_get_purchase_ledger(
        start_date=start_date,
        end_date=end_date,
        lottery_type=lottery_type,
        win_result=win_result,
        page_num=page_num,
        page_size=page_size,
    )
    return {"result": result}


async def _handle_search_lottery_shops(call: ServiceCall) -> dict[str, Any]:
    """복권 판매점 검색 서비스 핸들러."""
    hass = call.hass
    entry = _get_entry(hass, call)
    data = _get_entry_data(hass, entry)
    client: DonghangLotteryClient = data["client"]

    city = call.data.get(ATTR_CITY)
    district = call.data.get(ATTR_DISTRICT)
    lotto645 = call.data.get(ATTR_LOTTO645, False)
    lotto520 = call.data.get(ATTR_LOTTO520, False)
    speetto5 = call.data.get(ATTR_SPEETTO5, False)
    speetto10 = call.data.get(ATTR_SPEETTO10, False)
    speetto20 = call.data.get(ATTR_SPEETTO20, False)
    pension720 = call.data.get(ATTR_PENSION720, False)
    page_num = call.data.get(ATTR_PAGE_NUM, 1)
    page_size = call.data.get(ATTR_PAGE_SIZE, 10)

    result = await client.async_search_lottery_shops(
        city=city,
        district=district,
        lotto645=lotto645,
        lotto520=lotto520,
        speetto5=speetto5,
        speetto10=speetto10,
        speetto20=speetto20,
        pension720=pension720,
        page_num=page_num,
        page_size=page_size,
    )

    items = result.get("list") or result.get("data") or result.get("result") or []

    # 위치 기반 필터링
    location_entity = call.data.get(ATTR_LOCATION_ENTITY) or data.get("location_entity")
    max_distance = call.data.get(ATTR_MAX_DISTANCE)
    limit = call.data.get(ATTR_LIMIT)

    if location_entity:
        state = hass.states.get(location_entity)
        if state:
            lat = state.attributes.get("latitude")
            lon = state.attributes.get("longitude")
            if lat is not None and lon is not None:
                items = _filter_by_distance(items, lat, lon, max_distance, limit)

    return {"result": items, "total_count": result.get("totalCount", len(items))}


def _normalize_lotto_numbers(raw_numbers: list[Any]) -> list[list[int]]:
    normalized: list[list[int]] = []
    for entry in raw_numbers:
        if isinstance(entry, str):
            parts = [part.strip() for part in entry.replace(",", " ").split()]
            numbers = [int(part) for part in parts if part]
        else:
            numbers = [int(num) for num in entry]
        if len(numbers) != 6:
            raise DonghangLotteryError("Each lotto645 set must contain 6 numbers")
        normalized.append(sorted(numbers))
    return normalized


def _extract_lotto645_win_info(data: dict[str, Any]) -> dict[str, Any]:
    # api.py가 _raw에 원본 API 키를 보존하므로 우선 사용
    if "_raw" in data:
        item = data["_raw"]
    else:
        payload = data.get("data", data)
        items = payload.get("list") or payload.get("result") or payload.get("data") or []
        if items:
            item = items[0]
        else:
            item = payload if isinstance(payload, dict) else {}

    numbers = [
        int(item.get("tm1WnNo", 0)),
        int(item.get("tm2WnNo", 0)),
        int(item.get("tm3WnNo", 0)),
        int(item.get("tm4WnNo", 0)),
        int(item.get("tm5WnNo", 0)),
        int(item.get("tm6WnNo", 0)),
    ]
    bonus = int(item.get("bnsWnNo", 0))
    return {"numbers": numbers, "bonus": bonus, "draw_no": item.get("ltEpsd")}


def _check_lotto645_numbers(win_info: dict[str, Any], numbers: list[list[int]]) -> list[dict[str, Any]]:
    result = []
    win_set = set(win_info["numbers"])
    bonus = win_info["bonus"]
    for entry in numbers:
        match_count = len(win_set.intersection(entry))
        bonus_match = bonus in entry
        rank = _lotto645_rank(match_count, bonus_match)
        result.append(
            {
                "numbers": entry,
                "match_count": match_count,
                "bonus_match": bonus_match,
                "rank": rank,
            }
        )
    return result


def _lotto645_rank(match_count: int, bonus_match: bool) -> int | None:
    if match_count == 6:
        return 1
    if match_count == 5 and bonus_match:
        return 2
    if match_count == 5:
        return 3
    if match_count == 4:
        return 4
    if match_count == 3:
        return 5
    return None


def _filter_by_distance(
    items: list[dict[str, Any]],
    lat: float,
    lon: float,
    max_distance: float,
    limit: int,
) -> list[dict[str, Any]]:
    results = []
    for item in items:
        try:
            shop_lat = float(item.get("shpLat"))
            shop_lon = float(item.get("shpLot"))
        except (TypeError, ValueError):
            continue
        dist_km = _distance_km(lat, lon, shop_lat, shop_lon)
        if max_distance and dist_km > max_distance:
            continue
        item = {**item, "distance_km": round(dist_km, 3)}
        results.append(item)
    results.sort(key=lambda x: x.get("distance_km", 0))
    if limit and limit > 0:
        return results[:limit]
    return results


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in kilometers using the haversine formula."""
    radius_km = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c
