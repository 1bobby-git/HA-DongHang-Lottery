# custom_components/donghang_lottery/coordinator.py

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
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
FIRST_REFRESH_TIMEOUT = 30


LOGGER = logging.getLogger(__name__)


class DonghangLotteryCoordinator(DataUpdateCoordinator["DonghangLotteryData"]):
    """동행복권 데이터 코디네이터.

    추첨 시간 기반 스마트 업데이트:
    - 초기 로드 후 다음 추첨 시간까지 대기
    - 추첨 후 자동 업데이트
    - 불필요한 API 호출 최소화
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
        self._next_update_time: datetime | None = None

    async def async_config_entry_first_refresh(self) -> None:
        """최초 데이터 로드 및 스케줄 설정 (v0.6.0 강력한 우회 정책).

        HA setup timeout(60초) 내에 반드시 완료되도록 30초 타임아웃 적용.
        실패 시에도 기본 데이터로 설정하고 setup을 중단하지 않음.
        백그라운드에서 자동 재시도.
        """
        try:
            await asyncio.wait_for(
                super().async_config_entry_first_refresh(),
                timeout=FIRST_REFRESH_TIMEOUT,
            )
            LOGGER.info("[DHLottery] 최초 데이터 로드 성공")
        except asyncio.TimeoutError:
            LOGGER.warning(
                "[DHLottery] 최초 데이터 로드 타임아웃 (%d초) - 기본 데이터로 시작, 백그라운드 재시도 예정",
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
                "[DHLottery] 최초 데이터 로드 실패: %s - 기본 데이터로 시작, 백그라운드 재시도 예정",
                err,
            )
            self._set_default_data()

        self._schedule_next_update()
        # 최초 로드 실패 시 5분 후 백그라운드 재시도
        if self.data is None or (
            self.data and self.data.account.total_amount == 0
            and self.data.lotto645_result is None
        ):
            self._schedule_background_retry()

    def _set_default_data(self) -> None:
        """기본 빈 데이터 설정 (연결 실패 시).

        async_set_updated_data()를 사용하여 last_update_success=True로 설정.
        이렇게 해야 엔티티가 'unavailable'이 아닌 기본값(0)으로 표시됨.
        """
        self.async_set_updated_data(DonghangLotteryData(
            account=AccountSummary(
                total_amount=0,
                unconfirmed_count=0,
                unclaimed_high_value_count=0,
            ),
        ))

    def _schedule_background_retry(self) -> None:
        """백그라운드 데이터 재시도 스케줄 (5분 후)."""
        retry_time = dt_util.now() + timedelta(minutes=5)
        LOGGER.info(
            "[DHLottery] 백그라운드 재시도 예정: %s",
            retry_time.strftime("%H:%M:%S"),
        )

        @callback
        def _retry_refresh(_now: datetime) -> None:
            LOGGER.info("[DHLottery] 백그라운드 데이터 재시도 시작")
            self.hass.async_create_task(self.async_request_refresh())

        async_track_point_in_time(self.hass, _retry_refresh, retry_time)

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

    def async_cancel_scheduled_update(self) -> None:
        """스케줄된 업데이트 취소."""
        if self._scheduled_update_unsub:
            self._scheduled_update_unsub()
            self._scheduled_update_unsub = None

    async def _async_update_data(self) -> "DonghangLotteryData":
        try:
            account = await self.client.async_fetch_account_summary()
        except DonghangLotteryError as err:
            raise UpdateFailed(str(err)) from err

        lotto_result: dict[str, Any] | None = None
        pension_result: dict[str, Any] | None = None
        pension_round: int | None = None

        try:
            lotto_result = await self.client.async_get_lotto645_result()
        except DonghangLotteryError as err:
            LOGGER.debug("Failed to load lotto645 result: %s", err)

        try:
            pension_result = await self.client.async_get_pension720_result()
        except DonghangLotteryError as err:
            LOGGER.debug("Failed to load pension720 result: %s", err)

        try:
            pension_round = await self.client.async_get_latest_pension720_round()
        except DonghangLotteryError as err:
            LOGGER.debug("Failed to load pension720 round: %s", err)

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
