# custom_components/donghang_lottery/coordinator.py

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from dataclasses import dataclass
from typing import Any

from .api import AccountSummary, DonghangLotteryClient, DonghangLotteryError
from .const import DOMAIN


LOGGER = logging.getLogger(__name__)


class DonghangLotteryCoordinator(DataUpdateCoordinator["DonghangLotteryData"]):
    def __init__(
        self,
        hass: HomeAssistant,
        client: DonghangLotteryClient,
    ) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.client = client

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
