# custom_components/donghang_lottery/coordinator.py

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from dataclasses import dataclass
from typing import Any

from .api import AccountSummary, DonghangLotteryClient, DonghangLotteryError
from .const import (
    DEFAULT_LOTTO_UPDATE_HOUR,
    DEFAULT_PENSION_UPDATE_HOUR,
    DOMAIN,
)

# 최초 데이터 로드 타임아웃 (초) - HA setup timeout(60초)보다 짧아야 함
# v0.7.6: 30→45초 (워밍업에 시간이 소모되어 실제 로그인에 시간 부족했음)
FIRST_REFRESH_TIMEOUT = 45

# 백그라운드 재시도 설정
RETRY_INTERVALS_MINUTES = [5, 10, 20, 30, 30]  # 점진적 간격 (최대 5회)

LOGGER = logging.getLogger(__name__)


class DonghangLotteryCoordinator(DataUpdateCoordinator["DonghangLotteryData"]):
    """동행복권 데이터 코디네이터.

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
        lotto_update_hour: int = DEFAULT_LOTTO_UPDATE_HOUR,
        pension_update_hour: int = DEFAULT_PENSION_UPDATE_HOUR,
    ) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=None,  # 수동/스케줄 업데이트
        )
        self.client = client
        self._lotto_update_hour = lotto_update_hour
        self._pension_update_hour = pension_update_hour
        self._scheduled_update_unsub = None
        self._retry_unsub = None
        self._next_update_time: datetime | None = None
        self._last_update_time: datetime | None = None
        self._data_loaded = False  # 실제 API 데이터 로드 여부
        self._last_error: str | None = None
        self._data_source: str = "none"  # "none", "default", "api"

    async def async_config_entry_first_refresh(self) -> None:
        """최초 데이터 로드 및 스케줄 설정.

        HA setup timeout(60초) 내에 반드시 완료되도록 30초 타임아웃 적용.
        실패 시에도 기본 데이터로 설정하고 setup을 중단하지 않음.
        """
        try:
            await asyncio.wait_for(
                super().async_config_entry_first_refresh(),
                timeout=FIRST_REFRESH_TIMEOUT,
            )
            LOGGER.info("[DHLottery] 최초 데이터 로드 성공")
            self._data_loaded = True
        except asyncio.TimeoutError:
            LOGGER.warning(
                "[DHLottery] 최초 데이터 로드 타임아웃 (%d초) - 기본 데이터로 시작",
                FIRST_REFRESH_TIMEOUT,
            )
            self._set_default_data()
        except asyncio.CancelledError:
            LOGGER.warning(
                "[DHLottery] 최초 데이터 로드 취소됨 (CancelledError) - 기본 데이터로 시작"
            )
            self._set_default_data()
        except Exception as err:
            LOGGER.warning(
                "[DHLottery] 최초 데이터 로드 실패: %s - 기본 데이터로 시작",
                err,
            )
            self._set_default_data()

        self._schedule_next_update()
        # 데이터 미로드 시 백그라운드 재시도
        if not self._data_loaded:
            self._schedule_background_retry(0)

    def _set_default_data(self) -> None:
        """기본 빈 데이터 설정 (연결 실패 시).

        async_set_updated_data()를 사용하여 last_update_success=True로 설정.
        이렇게 해야 엔티티가 'unavailable'이 아닌 기본값(0)으로 표시됨.
        """
        self._data_source = "default"
        self._last_error = "최초 데이터 로드 실패 - 기본값 사용 중"
        LOGGER.info("[DHLottery] 기본 데이터 설정 (data_source=default)")
        self.async_set_updated_data(DonghangLotteryData(
            account=AccountSummary(
                total_amount=0,
                unconfirmed_count=0,
                unclaimed_high_value_count=0,
            ),
        ))

    def _schedule_background_retry(self, attempt: int) -> None:
        """백그라운드 데이터 재시도 스케줄 (점진적 간격)."""
        # 기존 재시도 스케줄 취소
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

        if attempt >= len(RETRY_INTERVALS_MINUTES):
            LOGGER.info(
                "[DHLottery] 백그라운드 재시도 한도 초과 (%d회) - 다음 예정 업데이트까지 대기",
                attempt,
            )
            return

        delay_minutes = RETRY_INTERVALS_MINUTES[attempt]
        retry_time = dt_util.now() + timedelta(minutes=delay_minutes)
        LOGGER.info(
            "[DHLottery] 백그라운드 재시도 예정: %s (%d분 후, %d/%d회)",
            retry_time.strftime("%H:%M:%S"),
            delay_minutes,
            attempt + 1,
            len(RETRY_INTERVALS_MINUTES),
        )

        next_attempt = attempt + 1

        @callback
        def _retry_refresh(_now: datetime) -> None:
            self._retry_unsub = None
            LOGGER.info("[DHLottery] 백그라운드 재시도 시작 (%d/%d)", next_attempt, len(RETRY_INTERVALS_MINUTES))
            self.hass.async_create_task(self._async_background_retry(next_attempt))

        self._retry_unsub = async_track_point_in_time(
            self.hass, _retry_refresh, retry_time
        )

    async def _async_background_retry(self, next_attempt: int) -> None:
        """백그라운드 재시도 실행. 실패 시 다음 재시도 스케줄."""
        await self.async_request_refresh()
        if not self._data_loaded:
            self._schedule_background_retry(next_attempt)
        else:
            LOGGER.info("[DHLottery] 백그라운드 재시도 성공 - 데이터 로드 완료")

    def _get_next_draw_time(self) -> datetime:
        """다음 당첨발표 확인 시간 계산 (목요일 또는 토요일 중 빠른 것)."""
        now = dt_util.now()

        # 로또 6/45: 토요일 (weekday=5) 설정된 시간
        days_until_lotto = (5 - now.weekday()) % 7
        next_lotto = now.replace(
            hour=self._lotto_update_hour,
            minute=0,
            second=0,
            microsecond=0,
        ) + timedelta(days=days_until_lotto)

        if next_lotto <= now:
            next_lotto += timedelta(weeks=1)

        # 연금복권 720+: 목요일 (weekday=3) 설정된 시간
        days_until_pension = (3 - now.weekday()) % 7
        next_pension = now.replace(
            hour=self._pension_update_hour,
            minute=0,
            second=0,
            microsecond=0,
        ) + timedelta(days=days_until_pension)

        if next_pension <= now:
            next_pension += timedelta(weeks=1)

        return min(next_lotto, next_pension)

    def _schedule_next_update(self) -> None:
        """다음 추첨 후 업데이트 스케줄."""
        # 기존 스케줄 취소
        if self._scheduled_update_unsub:
            self._scheduled_update_unsub()
            self._scheduled_update_unsub = None

        self._next_update_time = self._get_next_draw_time()
        LOGGER.info(
            "다음 업데이트 예정: %s",
            self._next_update_time.strftime("%Y-%m-%d %H:%M:%S"),
        )

        @callback
        def _scheduled_refresh(_now: datetime) -> None:
            """스케줄된 업데이트 실행."""
            LOGGER.info("추첨 후 자동 업데이트 시작")
            self.hass.async_create_task(self._async_scheduled_refresh())

        self._scheduled_update_unsub = async_track_point_in_time(
            self.hass,
            _scheduled_refresh,
            self._next_update_time,
        )

    async def _async_scheduled_refresh(self) -> None:
        """스케줄된 업데이트 실행 및 다음 스케줄 설정."""
        await self.async_request_refresh()
        self._schedule_next_update()

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

    def async_cancel_scheduled_update(self) -> None:
        """스케줄된 업데이트 취소."""
        if self._scheduled_update_unsub:
            self._scheduled_update_unsub()
            self._scheduled_update_unsub = None
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

    async def _async_update_data(self) -> "DonghangLotteryData":
        """데이터 업데이트 (실패 시 기존 데이터 보존 - UpdateFailed 미발생).

        핵심 원칙: 절대 UpdateFailed를 발생시키지 않음.
        - 실패 시 기존 데이터 반환 → 엔티티 항상 available 유지
        - 부분 성공 시 성공한 데이터만 갱신, 나머지는 기존 데이터 보존
        - 모든 API 응답을 INFO 로그에 기록 (진단용)
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
            # 기존 데이터 반환 (엔티티 available 유지)
            if prev_data is not None:
                LOGGER.info("[DHLottery] 기존 데이터 보존 (data_source=%s)", self._data_source)
                return prev_data
            # 최초 실패 시 기본 데이터
            self._data_source = "default"
            LOGGER.info("[DHLottery] 기본 데이터 반환 (data_source=default)")
            return DonghangLotteryData(
                account=AccountSummary(
                    total_amount=0,
                    unconfirmed_count=0,
                    unclaimed_high_value_count=0,
                ),
            )

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
        )


@dataclass
class DonghangLotteryData:
    account: AccountSummary
    lotto645_result: dict[str, Any] | None = None
    pension720_result: dict[str, Any] | None = None
    pension720_round: int | None = None
