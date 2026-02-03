# custom_components/donghang_lottery/config_flow.py

from __future__ import annotations

import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

from .api import (
    DonghangLotteryAuthError,
    DonghangLotteryClient,
    DonghangLotteryError,
)
from .const import (
    CONF_LOCATION_ENTITY,
    CONF_RELAY_URL,
    CONF_USE_RELAY,
    DEFAULT_RELAY_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class DonghangLotteryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._user_data: dict = {}

    async def _validate_credentials(
        self, username: str, password: str, relay_url: str = ""
    ) -> dict[str, str]:
        """로그인 검증 및 건전서약 확인.

        Returns:
            오류가 있으면 {"base": "error_key"}, 없으면 빈 딕셔너리
        """
        errors: dict[str, str] = {}

        # aiohttp 세션 생성
        connector = aiohttp.TCPConnector(
            limit=5,
            limit_per_host=2,
            ttl_dns_cache=300,
        )
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=60, connect=20),
            cookie_jar=aiohttp.CookieJar(unsafe=bool(relay_url)),
        )

        try:
            client = DonghangLotteryClient(
                session, username, password, relay_url=relay_url
            )

            # 1. 로그인 시도
            try:
                await client.async_login()
            except DonghangLotteryAuthError:
                _LOGGER.warning("[DHLottery] 로그인 실패: 잘못된 아이디 또는 비밀번호")
                errors["base"] = "invalid_auth"
                return errors
            except DonghangLotteryError as err:
                _LOGGER.warning("[DHLottery] 로그인 실패: %s", err)
                errors["base"] = "cannot_connect"
                return errors

            # 2. 건전서약 확인
            try:
                pledge_info = await client.async_check_soundness_pledge()
                if not pledge_info.get("pledged"):
                    _LOGGER.warning("[DHLottery] 건전서약 미완료")
                    errors["base"] = "soundness_pledge_required"
                    return errors
            except Exception as err:
                _LOGGER.warning("[DHLottery] 건전서약 확인 실패: %s", err)
                # 건전서약 확인 실패 시 일단 통과 (API 오류일 수 있음)

        finally:
            await session.close()

        return errors

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            # use_relay 값을 분리 저장
            use_relay = user_input.pop(CONF_USE_RELAY, False)
            self._user_data = user_input

            if use_relay:
                # 릴레이 설정 화면으로 이동
                return await self.async_step_relay()

            # 릴레이 미사용 → 자격 증명 검증
            errors = await self._validate_credentials(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                relay_url="",
            )

            if not errors:
                return self.async_create_entry(
                    title=f"동행복권 ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_LOCATION_ENTITY, default=""): str,
                vol.Optional(CONF_USE_RELAY, default=False): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_relay(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            # 릴레이 URL을 기존 데이터에 병합
            self._user_data[CONF_RELAY_URL] = user_input[CONF_RELAY_URL]

            # 릴레이 사용 시에도 자격 증명 검증
            errors = await self._validate_credentials(
                self._user_data[CONF_USERNAME],
                self._user_data[CONF_PASSWORD],
                relay_url=user_input[CONF_RELAY_URL],
            )

            if not errors:
                return self.async_create_entry(
                    title=f"동행복권 ({self._user_data[CONF_USERNAME]})",
                    data=self._user_data,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_RELAY_URL): str,
            }
        )
        return self.async_show_form(step_id="relay", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DonghangLotteryOptionsFlowHandler(config_entry)


class DonghangLotteryOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._options_data: dict = {}

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            use_relay = user_input.pop(CONF_USE_RELAY, False)
            self._options_data = user_input

            if use_relay:
                return await self.async_step_relay()

            # 릴레이 미사용 → relay_url 비우기
            self._options_data[CONF_RELAY_URL] = ""
            return self.async_create_entry(title="", data=self._options_data)

        # 현재 릴레이 URL이 있으면 use_relay 기본값 True
        current_relay = self._entry.options.get(
            CONF_RELAY_URL,
            self._entry.data.get(CONF_RELAY_URL, DEFAULT_RELAY_URL),
        )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_USERNAME,
                    default=self._entry.options.get(CONF_USERNAME, self._entry.data.get(CONF_USERNAME, "")),
                ): str,
                vol.Optional(
                    CONF_PASSWORD,
                    default=self._entry.options.get(CONF_PASSWORD, self._entry.data.get(CONF_PASSWORD, "")),
                ): str,
                vol.Optional(
                    CONF_LOCATION_ENTITY,
                    default=self._entry.options.get(
                        CONF_LOCATION_ENTITY,
                        self._entry.data.get(CONF_LOCATION_ENTITY, ""),
                    ),
                ): str,
                vol.Optional(
                    CONF_USE_RELAY,
                    default=bool(current_relay),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_relay(self, user_input=None):
        if user_input is not None:
            self._options_data[CONF_RELAY_URL] = user_input[CONF_RELAY_URL]
            return self.async_create_entry(title="", data=self._options_data)

        current_relay = self._entry.options.get(
            CONF_RELAY_URL,
            self._entry.data.get(CONF_RELAY_URL, DEFAULT_RELAY_URL),
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_RELAY_URL, default=current_relay): str,
            }
        )
        return self.async_show_form(step_id="relay", data_schema=schema)
