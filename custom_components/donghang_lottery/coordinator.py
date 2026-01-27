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

# 최초 데이터 로드 타임아웃 (초) - HA setup timeout(60초)보다 짧아야 함
# v0.7.6: 30→45초 (워밍업에 시간이 소모되어 실제 로그인에 시간 부족했음)
FIRST_REFRESH_TIMEOUT = 45

LOGGER = logging.getLogger(__name__)


class DonghangLotteryCoordinator(DataUpdateCoordinator["DonghangLotteryData"]):
    """동행복권 데이터 코디네이터.

    v0.7.8 - 연결 실패 시 명확한 실패 처리:
    - 최초 로드 실패 시 UpdateFailed → ConfigEntryNotReady (센서 미등록)
    - _set_default_data / 백그라운드 재시도 제거 (HA 자동 재시도 활용)
    - 이후 업데이트 실패 시 기존 데이터 보존 (현행 유지)

    v0.7.7 - 센서 데이터 파싱 버그 수정 (테스트 결과 기반):
    - 로또645: api.py가 변환한 키 대신 원본 API 키(_raw) 사용하도록 수정
    - 연금복권720: 중첩 구조 {data: {result: [...]}} 올바르게 탐색하도록 수정
    - 연금복권720: 실제 API 키 폴백 추가 (wnAmt, wnTotalCnt, wnBndNo)

    v0.7.6 - 진단 속성 모든 센서 확장 + 타임아웃 예산 최적화:
    - 모든 센서에 data_source/data_loaded/last_error 속성 추가
    - 워밍업 타임아웃 10초→5초 (총 예산 24초→12초)
    - 첫 로드 타임아웃 30초→45초 (실제 로그인 시간 확보)

    v0.7.5 - 진단 기능 강화:
    - 모든 API 호출 결과를 INFO 로그에 기록
    - "최근 업데이트" 센서에 전체 원시 데이터 속성 노출
    - data_source / last_error / circuit_breaker 상태 추적
    - 부분 실패 시 에러 요약 기록

    v0.7.4 - last_update_success_time 호환성 수정:
    - HA 버전별 last_update_success_time 미지원 문제 해결
    - 자체 last_update_time 프로퍼티로 마지막 업데이트 시간 관리

    v0.7.3 - 무중단 데이터 보존:
    - 업데이트 실패 시 기존 데이터 보존 (UpdateFailed 미발생)
    - 엔티티가 항상 available 상태 유지
    - 점진적 백그라운드 재시도 (5분 → 10분 → 20분 → 30분)
    - 추첨 시간 기반 스마트 업데이트
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
        """최초 데이터 로드 및 스케줄 설정.

        HA setup timeout(60초) 내에 완료되도록 타임아웃 적용.
        실패 시 ConfigEntryNotReady 전파 → HA가 자동 재시도.
        """
        try:
            await asyncio.wait_for(
                super().async_config_entry_first_refresh(),
                timeout=FIRST_REFRESH_TIMEOUT,
            )
        except asyncio.TimeoutError as err:
            raise ConfigEntryNotReady(
                f"초기 데이터 로드 타임아웃 ({FIRST_REFRESH_TIMEOUT}초)"
            ) from err
        # UpdateFailed → 부모가 ConfigEntryNotReady로 자동 변환
        # CancelledError → 그대로 전파 (HA setup timeout)

        LOGGER.info("[DHLottery] 최초 데이터 로드 성공")
        self._data_loaded = True
        self._schedule_next_update()

    def _get_next_draw_time(self) -> tuple[datetime, str]:
        """다음 당첨발표 확인 시간 계산.

        로또 6/45: 토요일 21:10
        연금복권 720+: 목요일 19:30

        Returns: (다음 시간, 타입) - 타입은 "lotto" 또는 "pension"
        """
        now = dt_util.now()

        # 로또 6/45: 토요일 (weekday=5) 21:10
        days_until_lotto = (5 - now.weekday()) % 7
        next_lotto = now.replace(
            hour=21, minute=10, second=0, microsecond=0,
        ) + timedelta(days=days_until_lotto)
        if next_lotto <= now:
            next_lotto += timedelta(weeks=1)

        # 연금복권 720+: 목요일 (weekday=3) 19:30
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
        """다음 추첨 후 업데이트 스케줄."""
        if self._scheduled_update_unsub:
            self._scheduled_update_unsub()
            self._scheduled_update_unsub = None
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

        next_time, draw_type = self._get_next_draw_time()
        self._next_update_time = next_time
        LOGGER.info(
            "다음 업데이트 예정: %s (%s)",
            next_time.strftime("%Y-%m-%d %H:%M:%S"),
            draw_type,
        )

        @callback
        def _scheduled_refresh(_now: datetime) -> None:
            """스케줄된 업데이트 실행."""
            LOGGER.info("추첨 후 자동 업데이트 시작 (%s)", draw_type)
            self.hass.async_create_task(self._async_draw_refresh(draw_type))

        self._scheduled_update_unsub = async_track_point_in_time(
            self.hass,
            _scheduled_refresh,
            next_time,
        )

    async def _async_draw_refresh(self, draw_type: str) -> None:
        """추첨 결과 업데이트 및 재시도 로직.

        결과가 아직 갱신되지 않은 경우 10분 후 재시도.
        """
        prev_round = self._get_current_round(draw_type)
        await self.async_request_refresh()
        new_round = self._get_current_round(draw_type)

        if new_round is not None and new_round != prev_round:
            LOGGER.info(
                "[DHLottery] %s 추첨 결과 업데이트 완료 (회차: %s → %s)",
                draw_type, prev_round, new_round,
            )
            self._schedule_next_update()
        else:
            LOGGER.info(
                "[DHLottery] %s 추첨 결과 미확인, 10분 후 재시도",
                draw_type,
            )
            self._schedule_retry(draw_type)

    def _get_current_round(self, draw_type: str) -> int | None:
        """현재 데이터의 회차 번호 반환."""
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
        """10분 후 재시도 스케줄."""
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
        """다음 업데이트 예정 시간."""
        return self._next_update_time

    @property
    def last_update_time(self) -> datetime | None:
        """마지막 성공적 데이터 업데이트 시간."""
        return self._last_update_time

    @property
    def last_error(self) -> str | None:
        """마지막 에러 메시지."""
        return self._last_error

    @property
    def data_source(self) -> str:
        """데이터 소스 ("none", "default", "api")."""
        return self._data_source

    @property
    def debug_info(self) -> dict[str, Any]:
        """진단 정보 (센서 속성으로 노출)."""
        info: dict[str, Any] = {
            "data_loaded": self._data_loaded,
            "data_source": self._data_source,
            "last_error": self._last_error,
        }
        # 클라이언트 상태
        try:
            info["circuit_breaker"] = self.client._circuit_state
            info["consecutive_failures"] = self.client._consecutive_failures
            info["logged_in"] = self.client._logged_in
        except Exception:
            pass
        return info

    def _find_nearest_physical_shop(
        self, items: list[dict[str, Any]], my_lat: float, my_lon: float
    ) -> dict[str, Any] | None:
        """온라인 판매점 제외, 가장 가까운 물리 판매점 찾기."""
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
            # 온라인 판매점 제외 (좌표가 0인 경우)
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

    def async_cancel_scheduled_update(self) -> None:
        """스케줄된 업데이트 취소."""
        if self._scheduled_update_unsub:
            self._scheduled_update_unsub()
            self._scheduled_update_unsub = None
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

    async def _async_update_data(self) -> "DonghangLotteryData":
        """데이터 업데이트.

        v0.7.8 핵심 원칙:
        - 최초 로드 실패 → UpdateFailed → ConfigEntryNotReady (센서 미등록)
        - 이후 실패 → 기존 데이터 반환 (엔티티 available 유지)
        - 부분 성공 시 성공한 데이터만 갱신, 나머지는 기존 데이터 보존
        """
        prev_data = self.data
        errors: list[str] = []

        # 1. 계정 정보 조회
        try:
            account = await self.client.async_fetch_account_summary()
            LOGGER.info(
                "[DHLottery] ✓ 계정 데이터 수신 - 잔액: %s원, 미확인: %s건, 고액미수령: %s건",
                account.total_amount, account.unconfirmed_count, account.unclaimed_high_value_count,
            )
        except DonghangLotteryError as err:
            LOGGER.warning("[DHLottery] ✗ 계정 정보 조회 실패: %s", err)
            self._last_error = f"계정 조회 실패: {err}"
            # 최초 로드 실패 → UpdateFailed → ConfigEntryNotReady
            if prev_data is None:
                raise UpdateFailed(f"계정 조회 실패: {err}") from err
            # 이후 실패 → 기존 데이터 보존 (엔티티 available 유지)
            LOGGER.info("[DHLottery] 기존 데이터 보존 (data_source=%s)", self._data_source)
            return prev_data

        # 계정 조회 성공 → 데이터 로드 플래그 및 타임스탬프 설정
        self._data_loaded = True
        self._data_source = "api"
        self._last_update_time = dt_util.now()

        # 2. 로또 6/45 결과 조회
        lotto_result: dict[str, Any] | None = None
        try:
            lotto_result = await self.client.async_get_lotto645_result()
            if lotto_result:
                LOGGER.info(
                    "[DHLottery] ✓ 로또 645 데이터 수신 - 키: %s",
                    list(lotto_result.keys()) if isinstance(lotto_result, dict) else type(lotto_result).__name__,
                )
                LOGGER.debug("[DHLottery] 로또 645 원시 데이터: %s", lotto_result)
            else:
                LOGGER.info("[DHLottery] ✓ 로또 645 조회 성공 - 데이터 없음 (빈 응답)")
                errors.append("로또645: 빈 응답")
        except DonghangLotteryError as err:
            LOGGER.warning("[DHLottery] ✗ 로또 645 조회 실패: %s", err)
            errors.append(f"로또645: {err}")
            if prev_data is not None:
                lotto_result = prev_data.lotto645_result

        # 3. 연금복권 720+ 결과 조회
        pension_result: dict[str, Any] | None = None
        try:
            pension_result = await self.client.async_get_pension720_result()
            if pension_result:
                LOGGER.info(
                    "[DHLottery] ✓ 연금복권 720 데이터 수신 - 키: %s",
                    list(pension_result.keys()) if isinstance(pension_result, dict) else type(pension_result).__name__,
                )
                LOGGER.debug("[DHLottery] 연금복권 720 원시 데이터: %s", pension_result)
            else:
                LOGGER.info("[DHLottery] ✓ 연금복권 720 조회 성공 - 데이터 없음 (빈 응답)")
                errors.append("연금720: 빈 응답")
        except DonghangLotteryError as err:
            LOGGER.warning("[DHLottery] ✗ 연금복권 720 조회 실패: %s", err)
            errors.append(f"연금720: {err}")
            if prev_data is not None:
                pension_result = prev_data.pension720_result

        # 4. 연금복권 720+ 최신 회차 조회
        pension_round: int | None = None
        try:
            pension_round = await self.client.async_get_latest_pension720_round()
            LOGGER.info("[DHLottery] ✓ 연금복권 720 회차: %s", pension_round)
        except DonghangLotteryError as err:
            LOGGER.warning("[DHLottery] ✗ 연금복권 720 회차 조회 실패: %s", err)
            errors.append(f"연금720회차: {err}")
            if prev_data is not None:
                pension_round = prev_data.pension720_round

        # 5. 가장 가까운 당첨 판매점 조회
        nearest_lotto_shop: dict[str, Any] | None = None
        nearest_pension_shop: dict[str, Any] | None = None

        if self._location_entity:
            state = self.hass.states.get(self._location_entity)
            if state:
                my_lat = state.attributes.get("latitude")
                my_lon = state.attributes.get("longitude")
                if my_lat is not None and my_lon is not None:
                    # 로또6/45 당첨 판매점
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
                        nearest_lotto_shop = self._find_nearest_physical_shop(items, float(my_lat), float(my_lon))
                        if nearest_lotto_shop:
                            LOGGER.info(
                                "[DHLottery] ✓ 로또 당첨 판매점: %s (%.2fkm)",
                                nearest_lotto_shop.get("shpNm", "?"),
                                nearest_lotto_shop.get("distance_km", 0),
                            )
                        else:
                            LOGGER.info("[DHLottery] 로또 당첨 판매점 없음 (물리 매장)")
                    except DonghangLotteryError as err:
                        LOGGER.warning("[DHLottery] ✗ 로또 당첨 판매점 조회 실패: %s", err)
                        errors.append(f"로또판매점: {err}")
                        if prev_data is not None:
                            nearest_lotto_shop = prev_data.nearest_lotto_shop

                    # 연금복권720+ 당첨 판매점
                    try:
                        pension_round_no = pension_round
                        if not pension_round_no:
                            pension_round_no = await self.client.async_get_latest_winning_shop_round("pt720")
                        shops_data = await self.client.async_get_winning_shops(
                            "pt720", "1", str(pension_round_no),
                        )
                        items = (shops_data.get("data") or {}).get("list") or shops_data.get("list") or shops_data.get("result") or []
                        nearest_pension_shop = self._find_nearest_physical_shop(items, float(my_lat), float(my_lon))
                        if nearest_pension_shop:
                            LOGGER.info(
                                "[DHLottery] ✓ 연금 당첨 판매점: %s (%.2fkm)",
                                nearest_pension_shop.get("shpNm", "?"),
                                nearest_pension_shop.get("distance_km", 0),
                            )
                        else:
                            LOGGER.info("[DHLottery] 연금 당첨 판매점 없음 (물리 매장)")
                    except DonghangLotteryError as err:
                        LOGGER.warning("[DHLottery] ✗ 연금 당첨 판매점 조회 실패: %s", err)
                        errors.append(f"연금판매점: {err}")
                        if prev_data is not None:
                            nearest_pension_shop = prev_data.nearest_pension_shop

        # 에러 요약
        if errors:
            self._last_error = " | ".join(errors)
            LOGGER.info("[DHLottery] 부분 실패: %s", self._last_error)
        else:
            self._last_error = None

        LOGGER.info(
            "[DHLottery] 데이터 업데이트 완료 - source=%s, 로또=%s, 연금=%s, 회차=%s",
            self._data_source,
            "있음" if lotto_result else "없음",
            "있음" if pension_result else "없음",
            pension_round,
        )

        return DonghangLotteryData(
            account=account,
            lotto645_result=lotto_result,
            pension720_result=pension_result,
            pension720_round=pension_round,
            nearest_lotto_shop=nearest_lotto_shop,
            nearest_pension_shop=nearest_pension_shop,
        )


@dataclass
class DonghangLotteryData:
    account: AccountSummary
    lotto645_result: dict[str, Any] | None = None
    pension720_result: dict[str, Any] | None = None
    pension720_round: int | None = None
    nearest_lotto_shop: dict[str, Any] | None = None
    nearest_pension_shop: dict[str, Any] | None = None
