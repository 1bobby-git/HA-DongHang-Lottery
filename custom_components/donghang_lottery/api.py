# custom_components/donghang_lottery/api.py

from __future__ import annotations

import asyncio
import base64
import binascii
import datetime as dt
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from aiohttp import ClientResponse, ClientSession
from bs4 import BeautifulSoup
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from yarl import URL

_LOGGER = logging.getLogger(__name__)

# User-Agent 목록 (차단 우회용 로테이션)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]

USER_AGENT = USER_AGENTS[0]


def _get_random_user_agent() -> str:
    """랜덤 User-Agent 반환."""
    return random.choice(USER_AGENTS)


BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ko,en-US;q=0.9,en;q=0.8,ko-KR;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


class DonghangLotteryError(Exception):
    """Base error for DHLottery integration."""


class DonghangLotteryAuthError(DonghangLotteryError):
    """Authentication error."""


class DonghangLotteryResponseError(DonghangLotteryError):
    """Unexpected response error."""


@dataclass
class AccountSummary:
    total_amount: int
    unconfirmed_count: int
    unclaimed_high_value_count: int


@dataclass
class PurchaseRecord:
    """구매 내역 레코드."""

    lottery_type: str
    round_no: int
    purchase_date: str
    numbers: list[str]
    amount: int
    result: str | None = None
    prize: int = 0


@dataclass
class WinningRecord:
    """당첨 내역 레코드."""

    lottery_type: str
    round_no: int
    draw_date: str
    rank: int
    prize: int
    numbers: str
    status: str  # claimed, unclaimed


class DonghangLotteryClient:
    """동행복권 API 클라이언트.

    차단 방지 기능:
    - 요청 간 랜덤 딜레이 (1~3초)
    - User-Agent 로테이션
    - 자동 재시도 (exponential backoff)
    - 세션 자동 복구
    """

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        min_request_interval: float = 1.0,
        max_request_interval: float = 3.0,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._timeout = 30
        self._logged_in = False
        self._session_id: str | None = None
        self._wmonid: str | None = None
        self._login_lock = asyncio.Lock()
        self._key_code: str | None = None
        self._iteration_count = 1000
        self._block_size = 16

        # 차단 방지 설정
        self._min_request_interval = min_request_interval
        self._max_request_interval = max_request_interval
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._last_request_time: float = 0
        self._request_lock = asyncio.Lock()
        self._current_user_agent = _get_random_user_agent()
        self._consecutive_failures = 0

    async def _throttle_request(self) -> None:
        """요청 간 랜덤 딜레이 적용 (차단 방지)."""
        async with self._request_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            min_interval = random.uniform(
                self._min_request_interval, self._max_request_interval
            )
            if elapsed < min_interval:
                delay = min_interval - elapsed
                _LOGGER.debug("Rate limiting: waiting %.2f seconds", delay)
                await asyncio.sleep(delay)
            self._last_request_time = time.time()

    def _rotate_user_agent(self) -> None:
        """User-Agent 로테이션."""
        self._current_user_agent = _get_random_user_agent()

    def _get_headers(self, base_headers: dict[str, str] | None = None) -> dict[str, str]:
        """현재 User-Agent가 적용된 헤더 반환."""
        headers = {**(base_headers or BASE_HEADERS)}
        headers["User-Agent"] = self._current_user_agent
        return headers

    async def async_login(self, force: bool = False) -> None:
        if self._logged_in and not force:
            return

        async with self._login_lock:
            if self._logged_in and not force:
                return

            await self._warmup_login_pages()
            modulus, exponent = await self._get_rsa_key()

            enc_user_id = self._rsa_encrypt(self._username, modulus, exponent)
            enc_password = self._rsa_encrypt(self._password, modulus, exponent)

            headers = {
                **BASE_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.dhlottery.co.kr",
                "Referer": "https://www.dhlottery.co.kr/user.do?method=login",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

            data = {
                "userId": enc_user_id,
                "userPswdEncn": enc_password,
                "inpUserId": self._username,
            }

            await self._request(
                "POST",
                "https://www.dhlottery.co.kr/login/securityLoginCheck.do",
                headers=headers,
                data=data,
            )
            self._update_session_ids()

            if not self._session_id:
                raise DonghangLotteryAuthError("Login failed: session id missing")

            self._logged_in = True

            try:
                await self._request("GET", "https://www.dhlottery.co.kr/common.do?method=main")
            except DonghangLotteryError:
                pass

    async def async_keepalive(self) -> None:
        if not self._logged_in:
            await self.async_login()
            return

        resp = await self._request("GET", "https://www.dhlottery.co.kr/common.do?method=main")
        await self._read_text(resp)
        self._update_session_ids()

    async def async_fetch_account_summary(self) -> AccountSummary:
        await self.async_login()
        mndp = await self._get_user_mndp()
        tooltip = await self._get_mypage_tooltip()

        total_amount = _safe_int(mndp.get("totalAmt"))
        if total_amount == 0:
            total_amount = _safe_int(mndp.get("pntDpstAmt")) - _safe_int(mndp.get("pntTkmnyAmt"))
            total_amount += _safe_int(mndp.get("ncsblDpstAmt")) - _safe_int(mndp.get("ncsblTkmnyAmt"))
            total_amount += _safe_int(mndp.get("csblDpstAmt")) - _safe_int(mndp.get("csblTkmnyAmt"))

        unconfirmed = 0
        high_value = 0
        if tooltip:
            unconfirmed = _safe_int(tooltip.get("ncfmLtInfo", {}).get("cnt"))
            high_value = len(tooltip.get("nrcvmtLramWnCntList", []) or [])

        return AccountSummary(
            total_amount=total_amount,
            unconfirmed_count=unconfirmed,
            unclaimed_high_value_count=high_value,
        )

    async def async_get_lotto645_result(self, draw_no: int | None = None) -> dict[str, Any]:
        # 새 API는 drwNo 파라미터를 무시하고 최신 회차를 반환함
        # draw_no가 필요한 경우 다른 API 엔드포인트를 사용해야 할 수 있음
        data = await self._get_json(
            "https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do",
        )

        # 새 응답 형식 파싱: data.list[0]
        result_list = (data.get("data") or {}).get("list") or []
        if not result_list:
            return {}

        item = result_list[0]

        # 기존 형식과 호환되는 반환값으로 변환
        return {
            "drwNo": item.get("ltEpsd"),
            "drwtNo1": item.get("tm1WnNo"),
            "drwtNo2": item.get("tm2WnNo"),
            "drwtNo3": item.get("tm3WnNo"),
            "drwtNo4": item.get("tm4WnNo"),
            "drwtNo5": item.get("tm5WnNo"),
            "drwtNo6": item.get("tm6WnNo"),
            "bnusNo": item.get("bnsWnNo"),
            "firstPrzwnerCo": item.get("rnk1WnNope"),
            "firstWinamnt": item.get("rnk1WnAmt"),
            "totSellamnt": item.get("wholEpsdSumNtslAmt"),
            "drwNoDate": item.get("ltRflYmd"),
            # 원본 데이터도 포함
            "_raw": item,
        }

    async def async_get_pension720_result(self, draw_no: int | None = None) -> dict[str, Any]:
        if draw_no is None:
            draw_no = await self._get_latest_pension720_round()
        params = {"srchPsltEpsd": str(draw_no)}
        data = await self._get_json(
            "https://www.dhlottery.co.kr/pt720/selectPstPt720Info.do",
            params=params,
        )
        return data

    async def async_get_pension720_rounds(self) -> list[int]:
        data = await self._get_json("https://www.dhlottery.co.kr/pt720/selectPstPt720WnList.do")
        # 새 API 형식: data.data.result
        result_list = (data.get("data") or {}).get("result") or data.get("result") or []
        rounds = []
        for item in result_list:
            epsd = item.get("psltEpsd")
            if epsd is None:
                continue
            rounds.append(_safe_int(epsd))
        return sorted([r for r in rounds if r > 0])

    async def async_get_latest_pension720_round(self) -> int:
        return await self._get_latest_pension720_round()

    async def async_check_pension720_numbers(self, draw_no: int, my_numbers: list[str]) -> dict[str, Any]:
        params = {"srchPsltEpsd": str(draw_no), "myNoList": my_numbers}
        return await self._get_json(
            "https://www.dhlottery.co.kr/pt720/selectPt720WnResult.do",
            params=params,
        )

    async def async_get_winning_shops(
        self,
        lottery_type: str,
        rank: str,
        round_no: str,
        region: str | None = None,
    ) -> dict[str, Any]:
        api_url = "https://www.dhlottery.co.kr/wnprchsplcsrch/selectLtWnShp.do"
        if lottery_type == "pt720":
            api_url = "https://www.dhlottery.co.kr/wnprchsplcsrch/selectPtWnShp.do"
        elif lottery_type != "lt645":
            api_url = "https://www.dhlottery.co.kr/wnprchsplcsrch/selectStWnShp.do"

        params = {
            "srchWnShpRnk": rank,
            "srchLtEpsd": round_no,
            "srchShpLctn": region or "",
        }

        return await self._get_json(api_url, params=params)

    async def async_get_latest_winning_shop_round(self, lottery_type: str) -> int:
        if lottery_type == "pt720":
            data = await self._get_json("https://www.dhlottery.co.kr/pt720/selectPtEpsdInfo.do")
            epsd_key = "psltEpsd"
        else:
            data = await self._get_json("https://www.dhlottery.co.kr/lt645/selectLtEpsdInfo.do")
            epsd_key = "ltEpsd"
        # 새 API 형식: data.data.list
        item_list = (data.get("data") or {}).get("list") or data.get("list") or []
        rounds = [_safe_int(item.get(epsd_key)) for item in item_list]
        rounds = [r for r in rounds if r > 0]
        if not rounds:
            raise DonghangLotteryResponseError("No rounds available for winning shops")
        return max(rounds)

    async def async_buy_lotto645_auto(self, count: int) -> dict[str, Any]:
        return await self._buy_lotto645(count, mode="auto")

    async def async_buy_lotto645_manual(self, numbers: list[list[int]]) -> dict[str, Any]:
        return await self._buy_lotto645(len(numbers), mode="manual", numbers=numbers)

    async def async_buy_pension720_auto(self) -> dict[str, Any]:
        await self.async_login()
        self._key_code = self._session_id or ""
        win720_round = await self._get_latest_pension720_round_for_buy()
        enc_numbers = await self._make_auto_numbers(win720_round)
        order_no, order_date = await self._make_order(win720_round, enc_numbers)
        result = await self._conn_pro(win720_round, enc_numbers, self._username, order_no, order_date)
        return result

    async def async_buy_pension720_auto_result(self) -> dict[str, Any]:
        result = await self.async_buy_pension720_auto()
        result["round"] = result.get("round") or await self._get_latest_pension720_round_for_buy()
        return result

    async def async_get_unclaimed_prizes(self) -> list[dict[str, Any]]:
        """미수령 당첨금 조회.

        Returns:
            미수령 당첨금 목록
        """
        await self.async_login()
        tooltip = await self._get_mypage_tooltip()
        return tooltip.get("nrcvmtLramWnCntList") or []

    async def async_get_unconfirmed_games(self) -> list[dict[str, Any]]:
        """미확인 복권 목록 조회.

        Returns:
            미확인 복권 목록
        """
        await self.async_login()
        tooltip = await self._get_mypage_tooltip()
        ncfm_info = tooltip.get("ncfmLtInfo") or {}
        return ncfm_info.get("list") or []

    async def async_get_purchase_ledger(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        lottery_type: str | None = None,
        win_result: str | None = None,
        page_num: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """구매 내역 조회.

        Args:
            start_date: 조회 시작일 (YYYYMMDD 형식, 기본값: 오늘)
            end_date: 조회 종료일 (YYYYMMDD 형식, 기본값: 오늘)
            lottery_type: 복권 종류 (빈값: 전체)
            win_result: 당첨 결과 필터 (빈값: 전체)
            page_num: 페이지 번호 (기본값: 1)
            page_size: 페이지당 항목 수 (기본값: 10)

        Returns:
            구매 내역 목록
        """
        await self.async_login()

        # 기본값: 오늘 날짜
        today = dt.date.today().strftime("%Y%m%d")
        if not start_date:
            start_date = today
        if not end_date:
            end_date = today

        timestamp = int(time.time() * 1000)
        params = {
            "srchStrDt": start_date,
            "srchEndDt": end_date,
            "sort": "",
            "ltGdsCd": lottery_type or "",
            "winResult": win_result or "",
            "pageNum": str(page_num),
            "recordCountPerPage": str(page_size),
            "_": str(timestamp),
        }

        headers = {
            **BASE_HEADERS,
            "Referer": "https://www.dhlottery.co.kr/mypage/home",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "AJAX": "true",
        }
        cookie_header = self._get_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header

        return await self._get_json(
            "https://www.dhlottery.co.kr/mypage/selectMyLotteryledger.do",
            headers=headers,
            params=params,
        )

    async def async_search_lottery_shops(
        self,
        city: str,
        district: str,
        lotto645: bool = False,
        lotto520: bool = False,
        speetto5: bool = False,
        speetto10: bool = False,
        speetto20: bool = False,
        pension720: bool = False,
        page_num: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """복권 판매점 검색.

        Args:
            city: 시/도 이름 (예: 서울, 경기)
            district: 구/군 이름 (예: 강남구, 수원시)
            lotto645: 로또6/45 판매점 필터
            lotto520: 로또5/20 판매점 필터
            speetto5: 스피또500 판매점 필터
            speetto10: 스피또1000 판매점 필터
            speetto20: 스피또2000 판매점 필터
            pension720: 연금복권720+ 판매점 필터
            page_num: 페이지 번호 (기본값: 1)
            page_size: 페이지당 항목 수 (기본값: 10)

        Returns:
            판매점 목록
        """
        timestamp = int(time.time() * 1000)
        params = {
            "l645LtNtslYn": "Y" if lotto645 else "N",
            "l520LtNtslYn": "Y" if lotto520 else "N",
            "st5LtNtslYn": "Y" if speetto5 else "N",
            "st10LtNtslYn": "Y" if speetto10 else "N",
            "st20LtNtslYn": "Y" if speetto20 else "N",
            "cpexUsePsbltyYn": "Y" if pension720 else "N",
            "pageNum": str(page_num),
            "recordCountPerPage": str(page_size),
            "pageCount": "5",
            "srchCtpvNm": city,
            "srchSggNm": district,
            "_": str(timestamp),
        }

        headers = {
            **BASE_HEADERS,
            "Referer": "https://www.dhlottery.co.kr/store.do?method=topStoreLocation",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        return await self._get_json(
            "https://www.dhlottery.co.kr/prchsplcsrch/selectLtShp.do",
            headers=headers,
            params=params,
        )

    async def async_get_next_draw_info(self, lottery_type: str = "lt645") -> dict[str, Any]:
        """다음 회차 추첨 정보 조회.

        Args:
            lottery_type: lt645 (로또), pt720 (연금복권)

        Returns:
            다음 회차 정보 (회차, 추첨일, 마감일 등)
        """
        if lottery_type == "pt720":
            url = "https://www.dhlottery.co.kr/pt720/selectPtEpsdInfo.do"
            epsd_key = "psltEpsd"
        else:
            url = "https://www.dhlottery.co.kr/lt645/selectLtEpsdInfo.do"
            epsd_key = "ltEpsd"

        data = await self._get_json(url)
        result = self._parse_nested_response(data)
        item_list = result.get("list") or []

        if not item_list:
            return {}

        # 가장 최근 회차 정보 반환
        latest = max(item_list, key=lambda x: _safe_int(x.get(epsd_key)) or 0)
        return latest

    async def async_check_lotto645_numbers(
        self,
        draw_no: int,
        numbers: list[list[int]],
    ) -> list[dict[str, Any]]:
        """로또 6/45 번호 당첨 확인.

        Args:
            draw_no: 회차 번호
            numbers: 확인할 번호 목록 [[1,2,3,4,5,6], ...]

        Returns:
            당첨 결과 목록
        """
        result = await self.async_get_lotto645_result(draw_no)

        # 당첨 번호 추출
        win_numbers = set()
        for key in ("drwtNo1", "drwtNo2", "drwtNo3", "drwtNo4", "drwtNo5", "drwtNo6"):
            num = result.get(key)
            if num:
                win_numbers.add(int(num))

        bonus = result.get("bnusNo")
        if bonus:
            bonus = int(bonus)

        checked = []
        for entry in numbers:
            entry_set = set(entry)
            match_count = len(win_numbers & entry_set)
            bonus_match = bonus in entry_set if bonus else False

            # 등수 계산
            rank = None
            if match_count == 6:
                rank = 1
            elif match_count == 5 and bonus_match:
                rank = 2
            elif match_count == 5:
                rank = 3
            elif match_count == 4:
                rank = 4
            elif match_count == 3:
                rank = 5

            checked.append({
                "numbers": sorted(entry),
                "match_count": match_count,
                "bonus_match": bonus_match,
                "rank": rank,
                "win_numbers": sorted(win_numbers),
                "bonus_number": bonus,
            })

        return checked

    def _parse_nested_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """중첩된 API 응답 파싱.

        동행복권 API는 data.data 또는 data 형태로 응답을 반환함.
        """
        if "data" in data and isinstance(data["data"], dict):
            return data["data"]
        return data

    async def _get_user_mndp(self) -> dict[str, Any]:
        timestamp = int(time.time() * 1000)
        url = f"https://www.dhlottery.co.kr/mypage/selectUserMndp.do?_={timestamp}"
        headers = {
            **BASE_HEADERS,
            "Referer": "https://www.dhlottery.co.kr/mypage/home",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "AJAX": "true",
            "requestMenuUri": "/mypage/home",
        }
        cookie_header = self._get_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        data = await self._get_json(url, headers=headers)
        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        if "userMndp" in data and isinstance(data["userMndp"], dict):
            data = data["userMndp"]
        return data

    async def _get_mypage_tooltip(self) -> dict[str, Any]:
        headers = {
            **BASE_HEADERS,
            "Referer": "https://www.dhlottery.co.kr/mypage/home",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "AJAX": "true",
        }
        cookie_header = self._get_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        data = await self._get_json(
            "https://www.dhlottery.co.kr/mypage/selectMypageTooltip.do",
            headers=headers,
        )
        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        return data

    async def _get_rsa_key(self) -> tuple[str, str]:
        headers = {
            **BASE_HEADERS,
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.dhlottery.co.kr/user.do?method=login",
        }
        data = await self._get_json("https://www.dhlottery.co.kr/login/selectRsaModulus.do", headers=headers)
        if "data" in data and "rsaModulus" in data["data"]:
            return data["data"]["rsaModulus"], data["data"]["publicExponent"]
        if "rsaModulus" in data:
            return data["rsaModulus"], data["publicExponent"]
        raise DonghangLotteryResponseError("RSA modulus not found")

    async def _warmup_login_pages(self) -> None:
        await self._request("GET", "https://www.dhlottery.co.kr/", headers=BASE_HEADERS)
        await self._request("GET", "https://www.dhlottery.co.kr/user.do?method=login", headers=BASE_HEADERS)
        await self._request("GET", "https://www.dhlottery.co.kr/", headers=BASE_HEADERS)
        await self._request("GET", "https://www.dhlottery.co.kr/user.do?method=login", headers=BASE_HEADERS)

    def _rsa_encrypt(self, text: str, modulus: str, exponent: str) -> str:
        key_spec = RSA.construct((int(modulus, 16), int(exponent, 16)))
        cipher = PKCS1_v1_5.new(key_spec)
        ciphertext = cipher.encrypt(text.encode("utf-8"))
        return binascii.hexlify(ciphertext).decode("utf-8")

    def _update_session_ids(self) -> None:
        for base in ("https://www.dhlottery.co.kr/",):
            cookies = self._session.cookie_jar.filter_cookies(URL(base))
            # 동행복권은 DHJSESSIONID를 사용함
            if "DHJSESSIONID" in cookies:
                self._session_id = cookies["DHJSESSIONID"].value
            elif "JSESSIONID" in cookies:
                self._session_id = cookies["JSESSIONID"].value
            if "WMONID" in cookies:
                self._wmonid = cookies["WMONID"].value

    def _get_cookie_header(self) -> str:
        parts = []
        if self._session_id:
            parts.append(f"DHJSESSIONID={self._session_id}")
        if self._wmonid:
            parts.append(f"WMONID={self._wmonid}")
        return "; ".join(parts)

    async def _get_latest_lotto645_round(self) -> int:
        # 새 API에서 직접 최신 회차 조회
        data = await self._get_json(
            "https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do",
        )
        result_list = (data.get("data") or {}).get("list") or []
        if result_list:
            round_no = result_list[0].get("ltEpsd")
            if round_no:
                return int(round_no)

        # 폴백: 메인 페이지에서 시도
        resp = await self._request("GET", "https://www.dhlottery.co.kr/common.do?method=main")
        html = await self._read_text(resp)
        soup = BeautifulSoup(html, "html5lib")
        found = soup.find("strong", id="lottoDrwNo")
        if found and found.text.isdigit():
            return int(found.text)
        raise DonghangLotteryResponseError("Failed to detect latest lotto645 round")

    async def _get_latest_pension720_round(self) -> int:
        rounds = await self.async_get_pension720_rounds()
        if rounds:
            return rounds[-1]
        raise DonghangLotteryResponseError("Failed to detect latest pension720 round")

    async def _get_latest_pension720_round_for_buy(self) -> str:
        resp = await self._request("GET", "https://www.dhlottery.co.kr/common.do?method=main")
        html = await self._read_text(resp)
        soup = BeautifulSoup(html, "html5lib")
        found = soup.find("strong", id="drwNo720")
        if found and found.text.isdigit():
            return str(int(found.text) - 1)
        base_date = dt.date(2024, 12, 26)
        base_round = 244
        today = dt.date.today()
        days_ahead = (3 - today.weekday()) % 7
        next_thursday = today + dt.timedelta(days=days_ahead)
        weeks = (next_thursday - base_date).days // 7
        return str(base_round + weeks - 1)

    async def _buy_lotto645(
        self, count: int, mode: str, numbers: list[list[int]] | None = None
    ) -> dict[str, Any]:
        await self.async_login()
        if count < 1 or count > 5:
            raise DonghangLotteryResponseError("Count must be between 1 and 5")

        headers = {
            **BASE_HEADERS,
            "Origin": "https://ol.dhlottery.co.kr",
            "Referer": "https://ol.dhlottery.co.kr/olotto/game/game645.do",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        cookie_header = self._get_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header

        requirements = await self._get_lotto645_requirements(headers)

        if mode == "auto":
            param = [
                {"genType": "0", "arrGameChoiceNum": None, "alpabet": slot}
                for slot in _slots()[:count]
            ]
        else:
            if not numbers or len(numbers) != count:
                raise DonghangLotteryResponseError("Manual numbers must match count")
            param = []
            for idx, item in enumerate(numbers):
                if len(item) != 6:
                    raise DonghangLotteryResponseError("Each manual line must have 6 numbers")
                choices = ",".join(str(num) for num in sorted(item))
                param.append(
                    {
                        "genType": "1",
                        "arrGameChoiceNum": choices,
                        "alpabet": _slots()[idx],
                    }
                )

        data = {
            "round": requirements.round_no,
            "direct": requirements.direct,
            "nBuyAmount": str(1000 * count),
            "param": json.dumps(param),
            "ROUND_DRAW_DATE": requirements.draw_date,
            "WAMT_PAY_TLMT_END_DT": requirements.tlmt_date,
            "gameCnt": count,
            "saleMdaDcd": "10",
        }

        resp = await self._request(
            "POST",
            "https://ol.dhlottery.co.kr/olotto/game/execBuy.do",
            headers=headers,
            data=data,
        )
        return await self._read_json(resp)

    async def _get_lotto645_requirements(self, headers: dict[str, str]) -> Any:
        req_headers = {
            **headers,
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Dest": "empty",
        }
        resp = await self._request(
            "POST",
            "https://ol.dhlottery.co.kr/olotto/game/egovUserReadySocket.json",
            headers=req_headers,
        )
        ready_data = await self._read_json(resp)
        direct = ready_data.get("ready_ip", "")

        html_headers = {
            **BASE_HEADERS,
            "Referer": "https://www.dhlottery.co.kr/common.do?method=main",
        }
        cookie_header = self._get_cookie_header()
        if cookie_header:
            html_headers["Cookie"] = cookie_header

        html_resp = await self._request(
            "GET",
            "https://ol.dhlottery.co.kr/olotto/game/game645.do",
            headers=html_headers,
        )
        html = await self._read_text(html_resp)
        soup = BeautifulSoup(html, "html5lib")

        draw_date = _get_input_value(soup, "ROUND_DRAW_DATE")
        tlmt_date = _get_input_value(soup, "WAMT_PAY_TLMT_END_DT")
        round_no = _get_input_value(soup, "curRound")

        if not draw_date or not tlmt_date:
            today = dt.date.today()
            days_ahead = (5 - today.weekday()) % 7
            next_saturday = today + dt.timedelta(days=days_ahead)
            draw_date = next_saturday.isoformat()
            tlmt_date = (next_saturday + dt.timedelta(days=366)).isoformat()

        if not round_no:
            round_no = str((await self._get_latest_lotto645_round()) + 1)

        return Lotto645Requirements(
            direct=direct,
            draw_date=draw_date,
            tlmt_date=tlmt_date,
            round_no=round_no,
        )

    async def _make_auto_numbers(self, win720_round: str) -> str:
        payload = (
            "ROUND={round}&round={round}&LT_EPSD={round}"
            "&SEL_NO=&BUY_CNT=&AUTO_SEL_SET=SA&SEL_CLASS=&BUY_TYPE=A&ACCS_TYPE=01"
        ).format(round=win720_round)
        data = {"q": quote(self._enc_text(payload))}
        headers = self._win720_headers()
        resp = await self._request(
            "POST",
            "https://el.dhlottery.co.kr/makeAutoNo.do",
            headers=headers,
            data=data,
        )
        body = await self._read_json(resp)
        decrypted = self._dec_text(body.get("q", ""))
        parsed = json.loads(decrypted)
        sel_no = parsed.get("selLotNo")
        if not sel_no:
            raise DonghangLotteryResponseError("Failed to extract pension720 numbers")
        return sel_no

    async def _make_order(self, win720_round: str, sel_numbers: str) -> tuple[str, str]:
        payload = (
            "ROUND={round}&round={round}&LT_EPSD={round}&AUTO_SEL_SET=SA&SEL_CLASS="
            "&SEL_NO={sel}&BUY_TYPE=M&BUY_CNT=5"
        ).format(round=win720_round, sel=sel_numbers)
        data = {"q": quote(self._enc_text(payload))}
        headers = self._win720_headers()
        resp = await self._request(
            "POST",
            "https://el.dhlottery.co.kr/makeOrderNo.do",
            headers=headers,
            data=data,
        )
        body = await self._read_json(resp)
        decrypted = self._dec_text(body.get("q", ""))
        parsed = json.loads(decrypted)
        return parsed["orderNo"], parsed["orderDate"]

    async def _conn_pro(
        self, win720_round: str, sel_numbers: str, username: str, order_no: str, order_date: str
    ) -> dict[str, Any]:
        buy_no = "".join([f"{idx}{sel_numbers}%2C" for idx in range(1, 6)])[:-3]
        payload = (
            "ROUND={round}&FLAG=&BUY_KIND=01&BUY_NO={buy_no}&BUY_CNT=5"
            "&BUY_SET_TYPE=SA%2CSA%2CSA%2CSA%2CSA&BUY_TYPE=A%2CA%2CA%2CA%2CA%2C"
            "&CS_TYPE=01&orderNo={order_no}&orderDate={order_date}&TRANSACTION_ID=&WIN_DATE="
            "&USER_ID={username}&PAY_TYPE=&resultErrorCode=&resultErrorMsg=&resultOrderNo="
            "&WORKING_FLAG=true&NUM_CHANGE_TYPE=&auto_process=N&set_type=SA&classnum=&selnum="
            "&buytype=M&num1=&num2=&num3=&num4=&num5=&num6=&DSEC=34&CLOSE_DATE="
            "&verifyYN=N&curdeposit=&curpay=5000&DROUND={round}&DSEC=0&CLOSE_DATE=&verifyYN=N"
            "&lotto720_radio_group=on"
        ).format(
            round=win720_round,
            buy_no=buy_no,
            order_no=order_no,
            order_date=order_date,
            username=username,
        )
        data = {"q": quote(self._enc_text(payload))}
        headers = self._win720_headers()
        resp = await self._request(
            "POST",
            "https://el.dhlottery.co.kr/connPro.do",
            headers=headers,
            data=data,
        )
        body = await self._read_json(resp)
        decrypted = self._dec_text(body.get("q", ""))
        return json.loads(decrypted)

    def _enc_text(self, plain_text: str) -> str:
        salt = get_random_bytes(32)
        iv = get_random_bytes(16)
        passphrase = (self._key_code or "")[:32].ljust(32, "0")
        key = PBKDF2(passphrase, salt, self._block_size, count=self._iteration_count, hmac_hash_module=SHA256)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded = _pad_bytes(plain_text.encode("utf-8"), self._block_size)
        return f"{salt.hex()}{iv.hex()}{base64.b64encode(cipher.encrypt(padded)).decode('utf-8')}"

    def _dec_text(self, enc_text: str) -> str:
        if len(enc_text) < 96:
            raise DonghangLotteryResponseError("Invalid encrypted payload")
        salt = bytes.fromhex(enc_text[0:64])
        iv = bytes.fromhex(enc_text[64:96])
        crypt_text = enc_text[96:]
        passphrase = (self._key_code or "")[:32].ljust(32, "0")
        key = PBKDF2(passphrase, salt, self._block_size, count=self._iteration_count, hmac_hash_module=SHA256)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(base64.b64decode(crypt_text))
        return _unpad_bytes(decrypted).decode("utf-8", errors="ignore")

    def _win720_headers(self) -> dict[str, str]:
        headers = {
            **BASE_HEADERS,
            "Origin": "https://el.dhlottery.co.kr",
            "Referer": "https://el.dhlottery.co.kr/game/pension720/game.jsp",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "*/*",
        }
        cookie_header = self._get_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        data: Any = None,
        params: dict[str, Any] | None = None,
        skip_throttle: bool = False,
    ) -> ClientResponse:
        """HTTP 요청 (차단 방지 기능 포함).

        - 요청 간 랜덤 딜레이
        - 실패 시 자동 재시도 (exponential backoff)
        - 401 시 자동 재로그인
        - 403/429 시 User-Agent 로테이션
        """
        # 스로틀링 적용
        if not skip_throttle:
            await self._throttle_request()

        request_headers = self._get_headers(BASE_HEADERS)
        if headers:
            request_headers.update(headers)
            # headers에 User-Agent가 없으면 현재 UA 사용
            if "User-Agent" not in headers:
                request_headers["User-Agent"] = self._current_user_agent

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._session.request(
                    method,
                    url,
                    headers=request_headers,
                    data=data,
                    params=params,
                    timeout=self._timeout,
                )

                # 성공적인 응답
                if resp.status == 200:
                    self._consecutive_failures = 0
                    return resp

                # 인증 실패 - 재로그인 시도
                if resp.status == 401:
                    _LOGGER.warning("401 Unauthorized - attempting re-login")
                    self._logged_in = False
                    if attempt < self._max_retries:
                        await self.async_login(force=True)
                        # 쿠키 헤더 갱신
                        cookie_header = self._get_cookie_header()
                        if cookie_header:
                            request_headers["Cookie"] = cookie_header
                        continue

                # 차단됨 - User-Agent 교체 후 재시도
                if resp.status in (403, 429):
                    self._consecutive_failures += 1
                    self._rotate_user_agent()
                    request_headers["User-Agent"] = self._current_user_agent
                    _LOGGER.warning(
                        "Blocked (status=%s) - rotating User-Agent, attempt %d/%d",
                        resp.status,
                        attempt + 1,
                        self._max_retries + 1,
                    )
                    if attempt < self._max_retries:
                        # Exponential backoff
                        delay = self._retry_delay * (2 ** attempt) + random.uniform(0, 1)
                        _LOGGER.debug("Waiting %.2f seconds before retry", delay)
                        await asyncio.sleep(delay)
                        continue

                # 기타 에러
                if resp.status >= 400:
                    _LOGGER.warning("HTTP error %s for %s", resp.status, url)

                return resp

            except asyncio.TimeoutError as err:
                last_error = err
                _LOGGER.warning("Request timeout for %s, attempt %d/%d", url, attempt + 1, self._max_retries + 1)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay * (attempt + 1))
                    continue

            except Exception as err:
                last_error = err
                _LOGGER.warning("Request error for %s: %s", url, err)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay)
                    continue

        raise DonghangLotteryError(f"Request failed after {self._max_retries + 1} attempts: {url}") from last_error

    async def _get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resp = await self._request("GET", url, headers=headers, params=params)
        return await self._read_json(resp)

    async def _read_json(self, resp: ClientResponse) -> dict[str, Any]:
        raw = await resp.read()
        for enc in (resp.charset, "utf-8", "euc-kr"):
            if not enc:
                continue
            try:
                return json.loads(raw.decode(enc))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        try:
            return json.loads(raw.decode("utf-8", errors="ignore"))
        except json.JSONDecodeError as err:
            raise DonghangLotteryResponseError("Failed to parse JSON response") from err

    async def _read_text(self, resp: ClientResponse) -> str:
        raw = await resp.read()
        for enc in (resp.charset, "utf-8", "euc-kr"):
            if not enc:
                continue
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")


@dataclass
class Lotto645Requirements:
    direct: str
    draw_date: str
    tlmt_date: str
    round_no: str


def _safe_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _slots() -> list[str]:
    return ["A", "B", "C", "D", "E"]


def _get_input_value(soup: BeautifulSoup, element_id: str) -> str:
    found = soup.find("input", id=element_id)
    if found:
        value = found.get("value")
        if isinstance(value, str):
            return value
    return ""


def _pad_bytes(data: bytes, block_size: int) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def _unpad_bytes(data: bytes) -> bytes:
    if not data:
        return data
    pad_len = data[-1]
    if pad_len < 1 or pad_len > len(data):
        return data
    return data[:-pad_len]
