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
    CONF_USE_PROXY,
    DEFAULT_LOTTO_UPDATE_HOUR,
    DEFAULT_PENSION_UPDATE_HOUR,
    DEFAULT_USE_PROXY,
    DOMAIN,
)


class DonghangLotteryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=f"동행복권 ({user_input[CONF_USERNAME]})",
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_LOCATION_ENTITY, default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DonghangLotteryOptionsFlowHandler(config_entry)


class DonghangLotteryOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LOCATION_ENTITY,
                    default=self._entry.options.get(
                        CONF_LOCATION_ENTITY,
                        self._entry.data.get(CONF_LOCATION_ENTITY, ""),
                    ),
                ): str,
                vol.Optional(
                    CONF_USERNAME,
                    default=self._entry.options.get(CONF_USERNAME, self._entry.data.get(CONF_USERNAME, "")),
                ): str,
                vol.Optional(
                    CONF_PASSWORD,
                    default=self._entry.options.get(CONF_PASSWORD, self._entry.data.get(CONF_PASSWORD, "")),
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
                    CONF_USE_PROXY,
                    default=self._entry.options.get(
                        CONF_USE_PROXY,
                        self._entry.data.get(CONF_USE_PROXY, DEFAULT_USE_PROXY),
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
