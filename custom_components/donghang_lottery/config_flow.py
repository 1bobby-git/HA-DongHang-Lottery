# custom_components/donghang_lottery/config_flow.py

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

from .const import (
    CONF_LOCATION_ENTITY,
    CONF_LOTTO_UPDATE_HOUR,
    CONF_PENSION_UPDATE_HOUR,
    CONF_RELAY_URL,
    CONF_USE_RELAY,
    DEFAULT_LOTTO_UPDATE_HOUR,
    DEFAULT_PENSION_UPDATE_HOUR,
    DEFAULT_RELAY_URL,
    DOMAIN,
)


class DonghangLotteryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._user_data: dict = {}

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            # use_relay 값을 분리 저장
            use_relay = user_input.pop(CONF_USE_RELAY, False)
            self._user_data = user_input

            if use_relay:
                # 릴레이 설정 화면으로 이동
                return await self.async_step_relay()

            # 릴레이 미사용 → 바로 설정 완료
            return self.async_create_entry(
                title=f"동행복권 ({user_input[CONF_USERNAME]})",
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_LOCATION_ENTITY, default=""): str,
                vol.Optional(
                    CONF_LOTTO_UPDATE_HOUR, default=DEFAULT_LOTTO_UPDATE_HOUR
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
                vol.Optional(
                    CONF_PENSION_UPDATE_HOUR, default=DEFAULT_PENSION_UPDATE_HOUR
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
                vol.Optional(CONF_USE_RELAY, default=False): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_relay(self, user_input=None):
        if user_input is not None:
            # 릴레이 URL을 기존 데이터에 병합
            self._user_data[CONF_RELAY_URL] = user_input[CONF_RELAY_URL]
            return self.async_create_entry(
                title=f"동행복권 ({self._user_data[CONF_USERNAME]})",
                data=self._user_data,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_RELAY_URL): str,
            }
        )
        return self.async_show_form(step_id="relay", data_schema=schema)

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
                    CONF_LOTTO_UPDATE_HOUR,
                    default=self._entry.options.get(
                        CONF_LOTTO_UPDATE_HOUR,
                        self._entry.data.get(CONF_LOTTO_UPDATE_HOUR, DEFAULT_LOTTO_UPDATE_HOUR),
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
                vol.Optional(
                    CONF_PENSION_UPDATE_HOUR,
                    default=self._entry.options.get(
                        CONF_PENSION_UPDATE_HOUR,
                        self._entry.data.get(CONF_PENSION_UPDATE_HOUR, DEFAULT_PENSION_UPDATE_HOUR),
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
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
