# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant custom integration for Korean lottery service "동행복권" (DongHang Lottery). Enables account info queries, lottery results checking, and ticket purchases from Home Assistant.

- **Domain**: `donghang_lottery`
- **Platforms**: `sensor`, `button`
- **IoT Class**: cloud_polling

## Development

No build system or tests currently exist. The integration is installed directly into Home Assistant's `custom_components` directory.

### Manual Testing
Copy `custom_components/donghang_lottery/` to your Home Assistant `config/custom_components/` directory and restart Home Assistant.

### Dependencies
Defined in `manifest.json`: `beautifulsoup4`, `html5lib`, `pycryptodome`

## Architecture

```
User → ConfigFlow → DonghangLotteryClient (api.py)
                           ↓
                    DonghangLotteryCoordinator
                           ↓
                    DonghangLotteryData (dataclass)
                           ↓
                    Sensors + Services
```

### Core Components

**`api.py`** - Web client handling all dhlottery.co.kr interactions
- RSA encryption for login credentials
- AES-CBC encryption for pension720 operations
- Session management with cookie persistence
- Key methods: `async_login()`, `async_fetch_account_summary()`, `async_get_lotto645_result()`, `async_buy_lotto645_auto/manual()`

**`coordinator.py`** - DataUpdateCoordinator aggregating:
- Account summary, lottery results, user info, deposit details
- Nearby winning shops (filtered by Haversine distance calculation)
- Location entity integration

**`sensor.py`** - 32 sensor entities across 3 device groups:
- Account: balance, unconfirmed games, unclaimed prizes
- Lotto: round, numbers, bonus, prizes, winners
- Pension: round, draw date, prizes, group info

**`__init__.py`** - Entry point with:
- 9 registered services for lottery operations
- 30-minute keepalive mechanism for session maintenance
- Service handlers for purchase, query, and number management

**`storage.py`** - MyNumberStore for persistent saved lottery numbers

### Services (domain: `donghang_lottery`)
- `buy_lotto645`, `buy_pension720` - Purchase tickets
- `fetch_lotto645_result`, `fetch_pension720_result` - Query specific draws
- `fetch_winning_shops` - Find winning shops with distance filtering
- `set_my_numbers`, `get_my_numbers` - Manage saved numbers
- `check_lotto645_numbers`, `check_pension720_numbers` - Validate against results
- `refresh_account` - Manual data refresh

## Code Conventions

- Python 3.10+ with `from __future__ import annotations`
- Fully async design with `aiohttp` sessions
- Dataclasses for data structures
- Custom exception hierarchy: `DonghangLotteryError`, `AuthError`, `ResponseError`
- Device groups: `account`, `lotto`, `pension` (defined in `device.py`)
- Constants centralized in `const.py`
- Korean UI strings in `strings.json` and `translations/ko.json`

## Key Files

| File | Purpose |
|------|---------|
| `api.py` | Web client, encryption, all API calls |
| `coordinator.py` | Data aggregation, update coordination |
| `sensor.py` | 32 sensor entity definitions |
| `const.py` | Constants, service names, attributes |
| `storage.py` | Persistent number storage |
| `device.py` | Device registry grouping |
