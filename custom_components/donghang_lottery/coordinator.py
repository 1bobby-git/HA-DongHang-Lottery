# custom_components/donghang_lottery/coordinator.py

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from dataclasses import dataclass
from typing import Any

from .api import AccountSummary, DonghangLotteryClient, DonghangLotteryError
from .const import DOMAIN

# First refresh timeout (seconds) - must be shorter than HA setup timeout (60s)
FIRST_REFRESH_TIMEOUT = 45

LOGGER = logging.getLogger(__name__)


class DonghangLotteryCoordinator(DataUpdateCoordinator["DonghangLotteryData"]):
    """Coordinator for managing Donghang Lottery data updates.

    Handles scheduled updates after lottery draws and provides
    data refresh functionality with error handling.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: DonghangLotteryClient,
        location_entity: str = "",
    ) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.client = client
        self._location_entity = location_entity
        self._scheduled_update_unsub = None
        self._retry_unsub = None
        self._next_update_time: datetime | None = None
        self._last_update_time: datetime | None = None
        self._data_loaded = False
        self._last_error: str | None = None
        self._data_source: str = "none"

    async def async_config_entry_first_refresh(self) -> None:
        """Initial data load and schedule setup.

        Applies timeout to complete within HA setup timeout (60 seconds).
        On failure, raises ConfigEntryNotReady for automatic retry.
        """
        try:
            await asyncio.wait_for(
                super().async_config_entry_first_refresh(),
                timeout=FIRST_REFRESH_TIMEOUT,
            )
        except asyncio.TimeoutError as err:
            raise ConfigEntryNotReady(
                f"Initial data load timeout ({FIRST_REFRESH_TIMEOUT}s)"
            ) from err

        LOGGER.info("[DHLottery] Initial data load successful")
        self._data_loaded = True
        self._schedule_next_update()

    def _get_next_draw_time(self) -> tuple[datetime, str]:
        """Calculate next draw result check time.

        Lotto 6/45: Saturday 21:10
        Pension 720+: Thursday 19:30

        Returns: (next_time, type) - type is "lotto" or "pension"
        """
        now = dt_util.now()

        # Lotto 6/45: Saturday (weekday=5) 21:10
        days_until_lotto = (5 - now.weekday()) % 7
        next_lotto = now.replace(
            hour=21, minute=10, second=0, microsecond=0,
        ) + timedelta(days=days_until_lotto)
        if next_lotto <= now:
            next_lotto += timedelta(weeks=1)

        # Pension 720+: Thursday (weekday=3) 19:30
        days_until_pension = (3 - now.weekday()) % 7
        next_pension = now.replace(
            hour=19, minute=30, second=0, microsecond=0,
        ) + timedelta(days=days_until_pension)
        if next_pension <= now:
            next_pension += timedelta(weeks=1)

        if next_lotto <= next_pension:
            return next_lotto, "lotto"
        return next_pension, "pension"

    def _schedule_next_update(self) -> None:
        """Schedule next update after draw."""
        if self._scheduled_update_unsub:
            self._scheduled_update_unsub()
            self._scheduled_update_unsub = None
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

        next_time, draw_type = self._get_next_draw_time()
        self._next_update_time = next_time
        LOGGER.info(
            "Next update scheduled: %s (%s)",
            next_time.strftime("%Y-%m-%d %H:%M:%S"),
            draw_type,
        )

        @callback
        def _scheduled_refresh(_now: datetime) -> None:
            """Execute scheduled update."""
            LOGGER.info("Starting auto-update after draw (%s)", draw_type)
            self.hass.async_create_task(self._async_draw_refresh(draw_type))

        self._scheduled_update_unsub = async_track_point_in_time(
            self.hass,
            _scheduled_refresh,
            next_time,
        )

    async def _async_draw_refresh(self, draw_type: str) -> None:
        """Update draw results with retry logic.

        Retries after 10 minutes if results are not yet available.
        """
        prev_round = self._get_current_round(draw_type)
        await self.async_request_refresh()
        new_round = self._get_current_round(draw_type)

        if new_round is not None and new_round != prev_round:
            LOGGER.info(
                "[DHLottery] %s draw results updated (round: %s -> %s)",
                draw_type, prev_round, new_round,
            )
            self._schedule_next_update()
        else:
            LOGGER.info(
                "[DHLottery] %s draw results not confirmed, retrying in 10 minutes",
                draw_type,
            )
            self._schedule_retry(draw_type)

    def _get_current_round(self, draw_type: str) -> int | None:
        """Return current round number from data."""
        data = self.data
        if not data:
            return None
        if draw_type == "lotto":
            result = data.lotto645_result or {}
            raw = result.get("_raw", result)
            val = raw.get("ltEpsd") or raw.get("drwNo")
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass
            return None
        else:
            return data.pension720_round

    def _schedule_retry(self, draw_type: str) -> None:
        """Schedule retry after 10 minutes."""
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

        retry_time = dt_util.now() + timedelta(minutes=10)
        self._next_update_time = retry_time
        LOGGER.info(
            "[DHLottery] %s 재시도 예정: %s",
            draw_type, retry_time.strftime("%H:%M:%S"),
        )

        @callback
        def _retry_refresh(_now: datetime) -> None:
            self._retry_unsub = None
            self.hass.async_create_task(self._async_draw_refresh(draw_type))

        self._retry_unsub = async_track_point_in_time(
            self.hass,
            _retry_refresh,
            retry_time,
        )

    @property
    def next_update_time(self) -> datetime | None:
        """Next scheduled update time."""
        return self._next_update_time

    @property
    def last_update_time(self) -> datetime | None:
        """Last successful data update time."""
        return self._last_update_time

    @property
    def last_error(self) -> str | None:
        """Last error message."""
        return self._last_error

    @property
    def data_source(self) -> str:
        """Data source: none, default, or api."""
        return self._data_source

    @property
    def debug_info(self) -> dict[str, Any]:
        """Diagnostic information exposed as sensor attributes."""
        info: dict[str, Any] = {
            "data_loaded": self._data_loaded,
            "data_source": self._data_source,
            "last_error": self._last_error,
        }
        try:
            info["circuit_breaker"] = self.client._circuit_state
            info["consecutive_failures"] = self.client._consecutive_failures
            info["logged_in"] = self.client._logged_in
        except Exception:
            pass
        return info

    def _find_nearest_physical_shop(
        self, items: list[dict[str, Any]], my_lat: float, my_lon: float,
        lottery_type: str = "",
    ) -> dict[str, Any] | None:
        """Find nearest physical shop excluding online retailers."""
        best: dict[str, Any] | None = None
        best_dist = float("inf")
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                shop_lat = float(item.get("shpLat", 0))
                shop_lon = float(item.get("shpLot", 0))
            except (TypeError, ValueError):
                continue
            # 온라인 판매점 제외
            if lottery_type == "lt645":
                # 로또: ltShpId가 "51100000"이면 온라인 판매점
                if str(item.get("ltShpId", "")) == "51100000":
                    continue
            else:
                # 연금복권: 좌표가 0이면 온라인 판매점
                if shop_lat == 0 and shop_lon == 0:
                    continue
            dist = self._haversine_km(my_lat, my_lon, shop_lat, shop_lon)
            if dist < best_dist:
                best_dist = dist
                best = {**item, "distance_km": round(dist, 2)}
        return best

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine 거리 계산 (km)."""
        R = 6371.0
        lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
        lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
        dlat = lat2_r - lat1_r
        dlon = lon2_r - lon1_r
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _get_last_draw_date(self, lotto_result, pension_result) -> str:
        """마지막 추첨일 반환 (YYYYMMDD). 로또/연금 중 더 이른 날짜."""
        dates = []

        # lotto result에서 추첨일 추출
        if lotto_result:
            raw = lotto_result.get("_raw", lotto_result)
            draw_date_str = raw.get("drwNoDate") or raw.get("drawDate")
            if draw_date_str:
                try:
                    d = datetime.strptime(draw_date_str, "%Y-%m-%d").date()
                    dates.append(d)
                except ValueError:
                    pass

        # pension result에서 추첨일 추출
        if pension_result:
            raw = pension_result.get("_raw", pension_result)
            draw_date_str = raw.get("drwNoDate") or raw.get("drawDate") or raw.get("epsdDt")
            if draw_date_str:
                try:
                    d = datetime.strptime(draw_date_str, "%Y-%m-%d").date()
                    dates.append(d)
                except ValueError:
                    pass

        if dates:
            return min(dates).strftime("%Y%m%d")

        # 폴백: 7일 전
        return (datetime.now().date() - timedelta(days=7)).strftime("%Y%m%d")

    def async_cancel_scheduled_update(self) -> None:
        """스케줄된 업데이트 취소."""
        if self._scheduled_update_unsub:
            self._scheduled_update_unsub()
            self._scheduled_update_unsub = None
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

    async def _async_update_data(self) -> "DonghangLotteryData":
        """Update lottery data.

        Error handling:
        - Initial load failure -> raises UpdateFailed -> ConfigEntryNotReady
        - Subsequent failures -> returns existing data (keeps entities available)
        - Partial success -> updates successful data, preserves rest
        """
        prev_data = self.data
        errors: list[str] = []

        # Fetch account summary
        try:
            account = await self.client.async_fetch_account_summary()
            LOGGER.info(
                "[DHLottery] [OK] Account data received - balance: %sw, unconfirmed: %s, high-value unclaimed: %s",
                account.total_amount, account.unconfirmed_count, account.unclaimed_high_value_count,
            )
        except DonghangLotteryError as err:
            LOGGER.warning("[DHLottery] [FAIL] Account info query failed: %s", err)
            self._last_error = f"Account query failed: {err}"
            if prev_data is None:
                raise UpdateFailed(f"Account query failed: {err}") from err
            LOGGER.info("[DHLottery] Preserving existing data (data_source=%s)", self._data_source)
            return prev_data

        self._data_loaded = True
        self._data_source = "api"
        self._last_update_time = dt_util.now()

        # Fetch Lotto 6/45 results
        lotto_result: dict[str, Any] | None = None
        try:
            lotto_result = await self.client.async_get_lotto645_result()
            if lotto_result:
                LOGGER.info(
                    "[DHLottery] [OK] Lotto 645 data received - keys: %s",
                    list(lotto_result.keys()) if isinstance(lotto_result, dict) else type(lotto_result).__name__,
                )
                LOGGER.debug("[DHLottery] 로또 645 원시 데이터: %s", lotto_result)
            else:
                LOGGER.info("[DHLottery] [OK] Lotto 645 query successful - no data (empty response)")
                errors.append("Lotto645: empty response")
        except DonghangLotteryError as err:
            LOGGER.warning("[DHLottery] [FAIL] Lotto 645 query failed: %s", err)
            errors.append(f"Lotto645: {err}")
            if prev_data is not None:
                lotto_result = prev_data.lotto645_result

        # Fetch Pension 720+ results
        pension_result: dict[str, Any] | None = None
        try:
            pension_result = await self.client.async_get_pension720_result()
            if pension_result:
                LOGGER.info(
                    "[DHLottery] [OK] Pension 720 data received - keys: %s",
                    list(pension_result.keys()) if isinstance(pension_result, dict) else type(pension_result).__name__,
                )
                LOGGER.debug("[DHLottery] 연금복권 720 원시 데이터: %s", pension_result)
            else:
                LOGGER.info("[DHLottery] [OK] Pension 720 query successful - no data (empty response)")
                errors.append("Pension720: empty response")
        except DonghangLotteryError as err:
            LOGGER.warning("[DHLottery] [FAIL] Pension 720 query failed: %s", err)
            errors.append(f"Pension720: {err}")
            if prev_data is not None:
                pension_result = prev_data.pension720_result

        # Fetch latest Pension 720+ round
        pension_round: int | None = None
        try:
            pension_round = await self.client.async_get_latest_pension720_round()
            LOGGER.info("[DHLottery] [OK] Pension 720 round: %s", pension_round)
        except DonghangLotteryError as err:
            LOGGER.warning("[DHLottery] [FAIL] Pension 720 round query failed: %s", err)
            errors.append(f"Pension720Round: {err}")
            if prev_data is not None:
                pension_round = prev_data.pension720_round

        # Find nearest winning shops
        nearest_lotto_shop: dict[str, Any] | None = None
        nearest_pension_shop: dict[str, Any] | None = None

        if self._location_entity:
            state = self.hass.states.get(self._location_entity)
            if state:
                my_lat = state.attributes.get("latitude")
                my_lon = state.attributes.get("longitude")
                if my_lat is not None and my_lon is not None:
                    # Lotto 6/45 winning shops
                    try:
                        lotto_round_no = None
                        if lotto_result:
                            raw = lotto_result.get("_raw", lotto_result)
                            lotto_round_no = raw.get("ltEpsd") or raw.get("drwNo")
                        if not lotto_round_no:
                            lotto_round_no = await self.client.async_get_latest_winning_shop_round("lt645")
                        shops_data = await self.client.async_get_winning_shops(
                            "lt645", "1", str(lotto_round_no),
                        )
                        items = (shops_data.get("data") or {}).get("list") or shops_data.get("list") or shops_data.get("result") or []
                        nearest_lotto_shop = self._find_nearest_physical_shop(items, float(my_lat), float(my_lon), lottery_type="lt645")
                        if nearest_lotto_shop:
                            LOGGER.info(
                                "[DHLottery] [OK] Lotto winning shop: %s (%.2fkm)",
                                nearest_lotto_shop.get("shpNm", "?"),
                                nearest_lotto_shop.get("distance_km", 0),
                            )
                        else:
                            LOGGER.info("[DHLottery] No lotto winning shop (physical stores only)")
                    except DonghangLotteryError as err:
                        LOGGER.warning("[DHLottery] [FAIL] Lotto winning shop query failed: %s", err)
                        errors.append(f"LottoShop: {err}")
                        if prev_data is not None:
                            nearest_lotto_shop = prev_data.nearest_lotto_shop

                    # Pension 720+ winning shops
                    try:
                        pension_round_no = pension_round
                        if not pension_round_no:
                            pension_round_no = await self.client.async_get_latest_winning_shop_round("pt720")
                        shops_data = await self.client.async_get_winning_shops(
                            "pt720", "1", str(pension_round_no),
                        )
                        items = (shops_data.get("data") or {}).get("list") or shops_data.get("list") or shops_data.get("result") or []
                        nearest_pension_shop = self._find_nearest_physical_shop(items, float(my_lat), float(my_lon), lottery_type="pt720")
                        if nearest_pension_shop:
                            LOGGER.info(
                                "[DHLottery] [OK] Pension winning shop: %s (%.2fkm)",
                                nearest_pension_shop.get("shpNm", "?"),
                                nearest_pension_shop.get("distance_km", 0),
                            )
                        else:
                            LOGGER.info("[DHLottery] No pension winning shop (physical stores only)")
                    except DonghangLotteryError as err:
                        LOGGER.warning("[DHLottery] [FAIL] Pension winning shop query failed: %s", err)
                        errors.append(f"PensionShop: {err}")
                        if prev_data is not None:
                            nearest_pension_shop = prev_data.nearest_pension_shop

        # Fetch purchase ledger
        purchase_ledger: list[dict[str, Any]] | None = None
        try:
            start_date = self._get_last_draw_date(lotto_result, pension_result)
            end_date = datetime.now().date().strftime("%Y%m%d")

            ledger_resp = await self.client.async_get_purchase_ledger(
                start_date=start_date,
                end_date=end_date,
                page_size=100,
            )
            raw_list = (
                ledger_resp.get("list")
                or (ledger_resp.get("data") or {}).get("list")
                or []
            )

            # 로또6/45 항목과 연금복권720+ 항목 분리
            purchase_ledger = []
            lotto_items = []
            for item in raw_list:
                gds_nm = item.get("ltGdsNm", "")
                barcode = item.get("barcd") or item.get("barCode") or ""
                if "로또" in gds_nm:
                    # 로또6/45
                    if barcode:
                        lotto_items.append(item)
                    else:
                        # 바코드 없는 로또 (상세 조회 불가)
                        purchase_ledger.append({**item, "_type": "lotto645_ticket"})
                elif "연금" in gds_nm:
                    # 연금복권720+
                    purchase_ledger.append({**item, "_type": "pension720"})
                else:
                    # 기타 복권 (스피또 등) - 일단 무시
                    LOGGER.debug("[DHLottery] Unknown lottery type ignored: %s", gds_nm)

            # 로또 티켓 상세 조회 (동시 3개씩)
            if lotto_items:
                sem = asyncio.Semaphore(3)

                async def _fetch_detail(item):
                    barcode = item.get("barcd") or item.get("barCode") or ""
                    async with sem:
                        try:
                            return item, await self.client.async_get_lotto645_ticket_detail(barcode)
                        except Exception:
                            LOGGER.warning("[DHLottery] Lotto ticket detail failed for barcode: %s", barcode)
                            return item, None

                results = await asyncio.gather(
                    *[_fetch_detail(it) for it in lotto_items],
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, Exception):
                        continue
                    item, games = result
                    if games:
                        for game in games:
                            purchase_ledger.append({**item, **game, "_type": "lotto645_game"})
                    else:
                        purchase_ledger.append({**item, "_type": "lotto645_ticket"})

            LOGGER.info("[DHLottery] [OK] Purchase ledger: %d items (range: %s ~ %s)", len(purchase_ledger), start_date, end_date)
        except DonghangLotteryError as err:
            LOGGER.warning("[DHLottery] [FAIL] Purchase ledger query failed: %s", err)
            errors.append(f"PurchaseLedger: {err}")
            if prev_data is not None:
                purchase_ledger = prev_data.purchase_ledger

        if errors:
            self._last_error = " | ".join(errors)
            LOGGER.info("[DHLottery] Partial failure: %s", self._last_error)
        else:
            self._last_error = None

        LOGGER.info(
            "[DHLottery] Data update complete - source=%s, lotto=%s, pension=%s, round=%s",
            self._data_source,
            "present" if lotto_result else "absent",
            "present" if pension_result else "absent",
            pension_round,
        )

        return DonghangLotteryData(
            account=account,
            lotto645_result=lotto_result,
            pension720_result=pension_result,
            pension720_round=pension_round,
            nearest_lotto_shop=nearest_lotto_shop,
            nearest_pension_shop=nearest_pension_shop,
            purchase_ledger=purchase_ledger,
        )


@dataclass
class DonghangLotteryData:
    account: AccountSummary
    lotto645_result: dict[str, Any] | None = None
    pension720_result: dict[str, Any] | None = None
    pension720_round: int | None = None
    nearest_lotto_shop: dict[str, Any] | None = None
    nearest_pension_shop: dict[str, Any] | None = None
    purchase_ledger: list[dict[str, Any]] | None = None
