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
# 직접 연결 모드에서 요청 간 딜레이가 길 수 있으므로 여유 확보
FIRST_REFRESH_TIMEOUT = 55

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

        # 그룹 1: 독립적인 API 호출 병렬 실행
        async def _fetch_account():
            return await self.client.async_fetch_account_summary()

        async def _fetch_lotto():
            return await self.client.async_get_lotto645_result()

        async def _fetch_pension():
            return await self.client.async_get_pension720_result()

        async def _fetch_pension_round():
            return await self.client.async_get_latest_pension720_round()

        results = await asyncio.gather(
            _fetch_account(),
            _fetch_lotto(),
            _fetch_pension(),
            _fetch_pension_round(),
            return_exceptions=True,
        )

        account_result, lotto_raw, pension_raw, pension_round_raw = results

        # Account 처리 (필수)
        if isinstance(account_result, Exception):
            LOGGER.warning("[DHLottery] [FAIL] Account info query failed: %s", account_result)
            self._last_error = f"Account query failed: {account_result}"
            if prev_data is None:
                raise UpdateFailed(f"Account query failed: {account_result}") from account_result
            LOGGER.info("[DHLottery] Preserving existing data (data_source=%s)", self._data_source)
            return prev_data

        account = account_result
        LOGGER.info(
            "[DHLottery] [OK] Account data received - balance: %sw, unconfirmed: %s, high-value unclaimed: %s",
            account.total_amount, account.unconfirmed_count, account.unclaimed_high_value_count,
        )

        self._data_loaded = True
        self._data_source = "api"
        self._last_update_time = dt_util.now()

        # Lotto 645 처리
        lotto_result: dict[str, Any] | None = None
        if isinstance(lotto_raw, Exception):
            LOGGER.warning("[DHLottery] [FAIL] Lotto 645 query failed: %s", lotto_raw)
            errors.append(f"Lotto645: {lotto_raw}")
            if prev_data is not None:
                lotto_result = prev_data.lotto645_result
        elif lotto_raw:
            lotto_result = lotto_raw
            LOGGER.info(
                "[DHLottery] [OK] Lotto 645 data received - keys: %s",
                list(lotto_result.keys()) if isinstance(lotto_result, dict) else type(lotto_result).__name__,
            )
            LOGGER.debug("[DHLottery] 로또 645 원시 데이터: %s", lotto_result)
        else:
            LOGGER.info("[DHLottery] [OK] Lotto 645 query successful - no data (empty response)")
            errors.append("Lotto645: empty response")

        # Pension 720 처리
        pension_result: dict[str, Any] | None = None
        if isinstance(pension_raw, Exception):
            LOGGER.warning("[DHLottery] [FAIL] Pension 720 query failed: %s", pension_raw)
            errors.append(f"Pension720: {pension_raw}")
            if prev_data is not None:
                pension_result = prev_data.pension720_result
        elif pension_raw:
            pension_result = pension_raw
            LOGGER.info(
                "[DHLottery] [OK] Pension 720 data received - keys: %s",
                list(pension_result.keys()) if isinstance(pension_result, dict) else type(pension_result).__name__,
            )
            LOGGER.debug("[DHLottery] 연금복권 720 원시 데이터: %s", pension_result)
        else:
            LOGGER.info("[DHLottery] [OK] Pension 720 query successful - no data (empty response)")
            errors.append("Pension720: empty response")

        # Pension 720 round 처리
        pension_round: int | None = None
        if isinstance(pension_round_raw, Exception):
            LOGGER.warning("[DHLottery] [FAIL] Pension 720 round query failed: %s", pension_round_raw)
            errors.append(f"Pension720Round: {pension_round_raw}")
            if prev_data is not None:
                pension_round = prev_data.pension720_round
        else:
            pension_round = pension_round_raw
            LOGGER.info("[DHLottery] [OK] Pension 720 round: %s", pension_round)

        # Find nearest winning shops (병렬 조회)
        nearest_lotto_shop: dict[str, Any] | None = None
        nearest_pension_shop: dict[str, Any] | None = None

        if self._location_entity:
            state = self.hass.states.get(self._location_entity)
            if state:
                my_lat = state.attributes.get("latitude")
                my_lon = state.attributes.get("longitude")
                if my_lat is not None and my_lon is not None:
                    # 회차 정보 준비
                    lotto_round_no = None
                    if lotto_result:
                        raw = lotto_result.get("_raw", lotto_result)
                        lotto_round_no = raw.get("ltEpsd") or raw.get("drwNo")
                    pension_round_no = pension_round

                    async def _fetch_lotto_shops():
                        nonlocal lotto_round_no
                        if not lotto_round_no:
                            lotto_round_no = await self.client.async_get_latest_winning_shop_round("lt645")
                        return await self.client.async_get_winning_shops("lt645", "1", str(lotto_round_no))

                    async def _fetch_pension_shops():
                        nonlocal pension_round_no
                        if not pension_round_no:
                            pension_round_no = await self.client.async_get_latest_winning_shop_round("pt720")
                        return await self.client.async_get_winning_shops("pt720", "1", str(pension_round_no))

                    shop_results = await asyncio.gather(
                        _fetch_lotto_shops(),
                        _fetch_pension_shops(),
                        return_exceptions=True,
                    )

                    # 로또 판매점 처리
                    if isinstance(shop_results[0], Exception):
                        LOGGER.warning("[DHLottery] [FAIL] Lotto winning shop query failed: %s", shop_results[0])
                        errors.append(f"LottoShop: {shop_results[0]}")
                        if prev_data is not None:
                            nearest_lotto_shop = prev_data.nearest_lotto_shop
                    else:
                        shops_data = shop_results[0]
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

                    # 연금복권 판매점 처리
                    if isinstance(shop_results[1], Exception):
                        LOGGER.warning("[DHLottery] [FAIL] Pension winning shop query failed: %s", shop_results[1])
                        errors.append(f"PensionShop: {shop_results[1]}")
                        if prev_data is not None:
                            nearest_pension_shop = prev_data.nearest_pension_shop
                    else:
                        shops_data = shop_results[1]
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
            # 로또: gmInfo에 바코드 저장됨
            # 연금: gmInfo에 "조번호:숫자" 형식 저장됨
            purchase_ledger = []
            lotto_items = []
            for item in raw_list:
                gds_nm = item.get("ltGdsNm", "")
                gm_info = item.get("gmInfo", "")
                if "로또" in gds_nm:
                    # 로또6/45 - gmInfo가 바코드
                    if gm_info:
                        # barcd 필드에 gmInfo 값 복사 (상세 조회용)
                        item_with_barcode = {**item, "barcd": gm_info}
                        lotto_items.append(item_with_barcode)
                    else:
                        LOGGER.warning("[DHLottery] Lotto without gmInfo: %s", item)
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

    def _parse_lotto645_game_choice(self, choice_str: str) -> dict[str, Any]:
        """arrGameChoiceNum 항목 파싱.

        형식: "A|06|10|20|31|32|441"
        - A: 슬롯 (A~E)
        - 06|10|20|31|32: 5개 번호 (2자리)
        - 441: 6번째 번호(44) + genType(1)
        """
        parts = choice_str.split("|")
        if len(parts) != 7:
            return {"raw": choice_str, "numbers": [], "slot": "", "mode": "unknown"}

        slot = parts[0]
        numbers = []
        for i in range(1, 6):
            try:
                numbers.append(int(parts[i]))
            except ValueError:
                pass

        # 마지막 부분: 번호 + genType
        last_part = parts[6]
        if len(last_part) >= 2:
            try:
                last_num = int(last_part[:-1])
                gen_type = int(last_part[-1])
                numbers.append(last_num)
            except ValueError:
                gen_type = 0
        else:
            gen_type = 0

        mode_map = {0: "auto", 1: "manual", 2: "semi_auto"}
        return {
            "slot": slot,
            "numbers": numbers,
            "mode": mode_map.get(gen_type, "unknown"),
            "raw": choice_str,
        }

    def add_lotto645_purchase(self, buy_result: dict[str, Any]) -> None:
        """로또 구매 결과를 purchase_ledger에 즉시 추가.

        API 응답 예시:
        {
            "loginYn": "Y",
            "result": {
                "buyRound": "1211",
                "arrGameChoiceNum": ["A|06|10|20|31|32|441"],
                "barCode1": "68455", ..., "barCode6": "63942",
                "issueDay": "2026/02/10",
                "issueTime": "10:09:40",
                "drawDate": "2026/02/14",
                "payLimitDate": "2027/02/15",
                "nBuyAmount": 1000,
                ...
            }
        }
        """
        result = buy_result.get("result", {})
        if not result or result.get("resultCode") != "100":
            LOGGER.warning("[DHLottery] Cannot add purchase - invalid result: %s", buy_result)
            return

        # 바코드 조합
        barcode_parts = [
            result.get(f"barCode{i}", "") for i in range(1, 7)
        ]
        full_barcode = " ".join(barcode_parts)

        # 날짜/시간 파싱
        issue_day = result.get("issueDay", "").replace("/", "-")
        issue_time = result.get("issueTime", "")
        draw_date = result.get("drawDate", "").replace("/", "-")
        buy_round = result.get("buyRound", "")

        # 게임 번호 파싱
        game_choices = result.get("arrGameChoiceNum", [])
        new_items = []

        for choice_str in game_choices:
            parsed = self._parse_lotto645_game_choice(choice_str)
            item = {
                "_type": "lotto645_game",
                "_source": "purchase",  # 구매 직후 추가됨을 표시
                "ltGdsNm": "로또6/45",
                "barcd": full_barcode,
                "buyDt": f"{issue_day} {issue_time}",
                "drawDt": draw_date,
                "ltEpsd": buy_round,
                "buyAmt": result.get("nBuyAmount", 0),
                "slot": parsed.get("slot", ""),
                "numbers": parsed.get("numbers", []),
                "mode": parsed.get("mode", ""),
                "payLimitDate": result.get("payLimitDate", "").replace("/", "-"),
                # 추가 정보
                "weekDay": result.get("weekDay", ""),
            }
            new_items.append(item)
            LOGGER.info(
                "[DHLottery] [OK] Purchase added to ledger: round=%s, slot=%s, numbers=%s",
                buy_round, parsed.get("slot"), parsed.get("numbers"),
            )

        # 현재 데이터에 추가
        if self.data and new_items:
            current_ledger = list(self.data.purchase_ledger or [])
            # 중복 방지: 같은 바코드가 있으면 추가하지 않음
            existing_barcodes = {item.get("barcd") for item in current_ledger}
            for item in new_items:
                if item.get("barcd") not in existing_barcodes:
                    current_ledger.insert(0, item)  # 최신 항목을 앞에 추가

            # 데이터 업데이트 (immutable dataclass이므로 새로 생성)
            self.async_set_updated_data(
                DonghangLotteryData(
                    account=self.data.account,
                    lotto645_result=self.data.lotto645_result,
                    pension720_result=self.data.pension720_result,
                    pension720_round=self.data.pension720_round,
                    nearest_lotto_shop=self.data.nearest_lotto_shop,
                    nearest_pension_shop=self.data.nearest_pension_shop,
                    purchase_ledger=current_ledger,
                )
            )

    def add_pension720_purchase(self, buy_result: dict[str, Any]) -> None:
        """연금복권 구매 결과를 purchase_ledger에 즉시 추가."""
        result = buy_result.get("result", {})
        if not result:
            LOGGER.warning("[DHLottery] Cannot add pension purchase - invalid result: %s", buy_result)
            return

        # 연금복권 응답 구조에 맞게 파싱 (추후 테스트 후 보완)
        LOGGER.info("[DHLottery] Pension 720 purchase result received: %s", result)
        # TODO: 연금복권 구매 결과 파싱 및 추가


@dataclass
class DonghangLotteryData:
    account: AccountSummary
    lotto645_result: dict[str, Any] | None = None
    pension720_result: dict[str, Any] | None = None
    pension720_round: int | None = None
    nearest_lotto_shop: dict[str, Any] | None = None
    nearest_pension_shop: dict[str, Any] | None = None
    purchase_ledger: list[dict[str, Any]] | None = None
