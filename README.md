# HA-DongHang-Lottery

Home Assistant custom integration for DHLottery (Lotto 6/45 and Pension 720+).

## Features
- Login with username/password (RSA flow).
- Account summary sensors: balance, unconfirmed games, unclaimed high-value wins.
- Lotto 6/45 and Pension 720+ result lookup.
- Winning shop lookup with optional distance filtering by a location entity.
- Purchase services (Lotto 6/45 auto/manual, Pension 720+ auto).
- Local "my numbers" storage for quick reuse.

## Installation (HACS)
1. HACS > Integrations > Custom repositories.
2. Add `https://github.com/1bobby-git/HA-DongHang-Lottery`.
3. Category: Integration.
4. Install and restart Home Assistant.

## Configuration
Add the integration from Home Assistant UI and enter:
- Username
- Password
- Optional location entity (for nearby winning shops)

## Services
Examples (Developer Tools > Services):

```yaml
service: donghang_lottery.buy_lotto645
data:
  mode: manual
  numbers:
    - [1, 2, 3, 4, 5, 6]
```

```yaml
service: donghang_lottery.buy_pension720
data: {}
```

```yaml
service: donghang_lottery.fetch_winning_shops
data:
  lottery_type: lt645
  rank: "1"
  draw_no: "1206"
  location_entity: person.home
  max_distance_km: 10
  limit: 20
```

```yaml
service: donghang_lottery.set_my_numbers
data:
  lottery_type: lt645
  numbers:
    - [8, 12, 19, 28, 33, 41]
```

```yaml
service: donghang_lottery.check_lotto645_numbers
data:
  use_my_numbers: true
```

## Notes
- "My numbers" are stored locally in Home Assistant storage.
- The integration relies on DHLottery endpoints and may require updates if the site changes.
- Updates are triggered by service calls; a 30-minute keepalive maintains the login session.
