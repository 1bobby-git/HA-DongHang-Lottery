# custom_components/donghang_lottery/coordinator.py

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from dataclasses import dataclass
from typing import Any

from .api import AccountSummary, DonghangLotteryClient, DonghangLotteryError
from .const import DOMAIN


LOGGER = logging.getLogger(__name__)

# 추첨 시간 (KST)
LOTTO645_DRAW_WEEKDAY = 5  # 토요일 (0=월, 5=토)
LOTTO645_DRAW_HOUR = 20
LOTTO645_DRAW_MINUTE = 45

PENSION720_DRAW_WEEKDAY = 3  # 목요일
PENSION720_DRAW_HOUR = 19
PENSION720_DRAW_MINUTE = 5

# 추첨 후 결과 반영 대기 시간 (분)
DRAW_RESULT_DELAY = 30


def _get_next_draw_time() -> datetime:
    """다음 추첨 시간 계산 (로또 또는 연금복권 중 빠른 것)."""
    now = dt_util.now()

    # 로또 6/45: 토요일 20:45
    days_until_lotto = (LOTTO645_DRAW_WEEKDAY - now.weekday()) % 7
    next_lotto = now.replace(
        hour=LOTTO645_DRAW_HOUR,
        minute=LOTTO645_DRAW_MINUTE,
        second=0,
        microsecond=0,
    ) + timedelta(days=days_until_lotto)

    # 이미 지났으면 다음 주
    if next_lotto <= now:
        next_lotto += timedelta(weeks=1)

    # 연금복권 720+: 목요일 19:05
    days_until_pension = (PENSION720_DRAW_WEEKDAY - now.weekday()) % 7
    next_pension = now.replace(
        hour=PENSION720_DRAW_HOUR,
        minute=PENSION720_DRAW_MINUTE,
        second=0,
        microsecond=0,
    ) + timedelta(days=days_until_pension)

    if next_pension <= now:
        next_pension += timedelta(weeks=1)

    # 더 빠른 추첨 시간 + 결과 반영 대기 시간
    next_draw = min(next_lotto, next_pension)
    return next_draw + timedelta(minutes=DRAW_RESULT_DELAY)


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
    ) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=None,  # 수동/스케줄 업데이트
        )
        self.client = client
        self._scheduled_update_unsub = None
        self._next_update_time: datetime | None = None

    async def async_config_entry_first_refresh(self) -> None:
        """최초 데이터 로드 및 스케줄 설정."""
        await super().async_config_entry_first_refresh()
        self._schedule_next_update()

    def _schedule_next_update(self) -> None:
        """다음 추첨 후 업데이트 스케줄."""
        # 기존 스케줄 취소
        if self._scheduled_update_unsub:
            self._scheduled_update_unsub()
            self._scheduled_update_unsub = None

        self._next_update_time = _get_next_draw_time()
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
