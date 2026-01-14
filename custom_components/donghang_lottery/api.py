# custom_components/donghang_lottery/api.py

from __future__ import annotations

import asyncio
import base64
import binascii
import datetime as dt
import json
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


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ko,en-US;q=0.9,en;q=0.8,ko-KR;q=0.7",
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


class DonghangLotteryClient:
    def __init__(self, session: ClientSession, username: str, password: str) -> None:
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
        if draw_no is None:
            draw_no = await self._get_latest_lotto645_round()
        params = {"drwNo": str(draw_no)}
        data = await self._get_json(
            "https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do",
            params=params,
        )
        return data

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
        rounds = []
        for item in data.get("result", []) or []:
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
        rounds = [_safe_int(item.get(epsd_key)) for item in data.get("list", []) or []]
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
            if "JSESSIONID" in cookies:
                self._session_id = cookies["JSESSIONID"].value
            if "WMONID" in cookies:
                self._wmonid = cookies["WMONID"].value

    def _get_cookie_header(self) -> str:
        parts = []
        if self._session_id:
            parts.append(f"JSESSIONID={self._session_id}")
        if self._wmonid:
            parts.append(f"WMONID={self._wmonid}")
        return "; ".join(parts)

    async def _get_latest_lotto645_round(self) -> int:
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
    ) -> ClientResponse:
        request_headers = {**BASE_HEADERS}
        if headers:
            request_headers.update(headers)
        try:
            return await self._session.request(
                method,
                url,
                headers=request_headers,
                data=data,
                params=params,
                timeout=self._timeout,
            )
        except Exception as err:
            raise DonghangLotteryError(f"Request failed: {url}") from err

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
