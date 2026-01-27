# custom_components/donghang_lottery/const.py
"""동행복권 통합 상수 정의."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "donghang_lottery"

# 인증 설정
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_LOCATION_ENTITY: Final = "location_entity"

# 차단 우회 설정
CONF_MIN_REQUEST_INTERVAL: Final = "min_request_interval"
CONF_MAX_REQUEST_INTERVAL: Final = "max_request_interval"
CONF_RELAY_URL: Final = "relay_url"  # Cloudflare Worker 릴레이 URL
CONF_USE_RELAY: Final = "use_relay"  # 릴레이 서버 사용 여부 (config flow용)

# 기본값 (강화됨: 차단 우회를 위해 요청 간격 증가)
DEFAULT_MIN_REQUEST_INTERVAL: Final = 4.0  # 증가: 1.0 → 4.0
DEFAULT_MAX_REQUEST_INTERVAL: Final = 10.0  # 증가: 3.0 → 10.0
DEFAULT_RELAY_URL: Final = ""  # 빈값 = 직접 연결, URL 입력 시 릴레이 경유

ATTR_ENTRY_ID = "entry_id"
ATTR_DRAW_NO = "draw_no"
ATTR_COUNT = "count"
ATTR_MODE = "mode"
ATTR_NUMBERS = "numbers"
ATTR_LOTTERY_TYPE = "lottery_type"
ATTR_RANK = "rank"
ATTR_REGION = "region"
ATTR_MAX_DISTANCE = "max_distance_km"
ATTR_LIMIT = "limit"
ATTR_LOCATION_ENTITY = "location_entity"
ATTR_USE_MY_NUMBERS = "use_my_numbers"

LOTTERY_LOTTO645 = "lt645"
LOTTERY_PENSION720 = "pt720"

MODE_AUTO = "auto"
MODE_MANUAL = "manual"

SERVICE_REFRESH_ACCOUNT = "refresh_account"
SERVICE_BUY_LOTTO645 = "buy_lotto645"
SERVICE_BUY_PENSION720 = "buy_pension720"
SERVICE_FETCH_LOTTO645_RESULT = "fetch_lotto645_result"
SERVICE_FETCH_PENSION720_RESULT = "fetch_pension720_result"
SERVICE_FETCH_WINNING_SHOPS = "fetch_winning_shops"
SERVICE_SET_MY_NUMBERS = "set_my_numbers"
SERVICE_GET_MY_NUMBERS = "get_my_numbers"
SERVICE_CHECK_LOTTO645_NUMBERS = "check_lotto645_numbers"
SERVICE_CHECK_PENSION720_NUMBERS = "check_pension720_numbers"
SERVICE_FETCH_NEXT_DRAW_INFO = "fetch_next_draw_info"
SERVICE_FETCH_PURCHASE_LEDGER = "fetch_purchase_ledger"
SERVICE_SEARCH_LOTTERY_SHOPS = "search_lottery_shops"

ATTR_START_DATE = "start_date"
ATTR_END_DATE = "end_date"
ATTR_WIN_RESULT = "win_result"
ATTR_PAGE_NUM = "page_num"
ATTR_PAGE_SIZE = "page_size"
ATTR_CITY = "city"
ATTR_DISTRICT = "district"
ATTR_LOTTO645 = "lotto645"
ATTR_LOTTO520 = "lotto520"
ATTR_SPEETTO5 = "speetto5"
ATTR_SPEETTO10 = "speetto10"
ATTR_SPEETTO20 = "speetto20"
ATTR_PENSION720 = "pension720"
