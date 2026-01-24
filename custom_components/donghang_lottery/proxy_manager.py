# custom_components/donghang_lottery/proxy_manager.py
"""프록시 관리자 - 무료 프록시 자동 수집 및 로테이션 (강화 버전)."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# 무료 프록시 목록 제공 URL들 (확장)
PROXY_LIST_URLS = [
    # 대용량 프록시 목록
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    # 추가 소스
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt",
    "https://raw.githubusercontent.com/prxchk/proxy-list/main/http.txt",
    # API 기반
    "https://www.proxy-list.download/api/v1/get?type=http",
    "https://api.openproxylist.xyz/http.txt",
]

# SOCKS5 프록시 소스 (HTTPS 터널링에 더 적합)
SOCKS5_PROXY_URLS = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all",
]


@dataclass
class ProxyInfo:
    """프록시 정보."""
    host: str
    port: int
    protocol: str = "http"  # http, https, socks5
    country: str | None = None
    response_time: float = 0.0  # ms
    last_used: float = 0.0
    fail_count: int = 0
    success_count: int = 0

    @property
    def url(self) -> str:
        """프록시 URL 반환."""
        return f"{self.protocol}://{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        """성공률 반환."""
        total = self.success_count + self.fail_count
        if total == 0:
            return 0.5  # 미테스트 프록시는 50%
        return self.success_count / total


class ProxyManager:
    """프록시 관리자 (강화 버전).

    기능:
    - 무료 HTTP/SOCKS5 프록시 자동 수집
    - 2단계 검증 (연결성 + 대상 사이트)
    - 성공률 기반 프록시 로테이션
    - 실패한 프록시 자동 제외
    - 프록시 실패 시 직접 연결 폴백
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        test_url: str = "https://www.dhlottery.co.kr/",
        max_proxies: int = 100,  # 증가: 50 → 100
        proxy_timeout: float = 15.0,  # 증가: 10 → 15
        refresh_interval: int = 1800,
    ) -> None:
        self._session = session
        self._test_url = test_url
        self._max_proxies = max_proxies
        self._proxy_timeout = proxy_timeout
        self._refresh_interval = refresh_interval

        self._proxies: list[ProxyInfo] = []
        self._current_proxy: ProxyInfo | None = None
        self._last_refresh: float = 0
        self._lock = asyncio.Lock()

        self._enabled = True
        self._direct_mode = False
        self._init_attempts = 0
        self._max_init_attempts = 3

        _LOGGER.info("[ProxyMgr] 프록시 관리자 초기화 (강화 버전)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        _LOGGER.info("[ProxyMgr] 프록시 %s", "활성화" if value else "비활성화")

    @property
    def current_proxy(self) -> ProxyInfo | None:
        return self._current_proxy

    @property
    def proxy_count(self) -> int:
        return len(self._proxies)

    async def initialize(self) -> bool:
        """프록시 목록 초기화 및 검증."""
        _LOGGER.info("[ProxyMgr] 프록시 초기화 시작 (시도 %d/%d)...",
                     self._init_attempts + 1, self._max_init_attempts)

        # HTTP 프록시 수집
        http_proxies = await self._fetch_proxy_lists(PROXY_LIST_URLS, "http")
        _LOGGER.info("[ProxyMgr] HTTP 프록시 %d개 수집", len(http_proxies))

        # SOCKS5 프록시 수집 (aiohttp-socks 없어도 일단 수집)
        socks_proxies = await self._fetch_proxy_lists(SOCKS5_PROXY_URLS, "socks5")
        _LOGGER.info("[ProxyMgr] SOCKS5 프록시 %d개 수집", len(socks_proxies))

        all_proxies = http_proxies + socks_proxies
        if not all_proxies:
            _LOGGER.warning("[ProxyMgr] 프록시 목록 수집 실패")
            self._init_attempts += 1
            return False

        _LOGGER.info("[ProxyMgr] 총 %d개 프록시 후보, 검증 시작...", len(all_proxies))

        # 1단계: 기본 연결성 검증 (httpbin으로 빠르게)
        connectable = await self._validate_connectivity(all_proxies)
        _LOGGER.info("[ProxyMgr] 1단계 연결 가능: %d개", len(connectable))

        if not connectable:
            _LOGGER.warning("[ProxyMgr] 연결 가능한 프록시 없음")
            self._init_attempts += 1
            return False

        # 2단계: 대상 사이트 접근 검증 (상위 프록시만)
        top_proxies = connectable[:min(50, len(connectable))]
        valid_proxies = await self._validate_target_access(top_proxies)
        _LOGGER.info("[ProxyMgr] 2단계 대상 접근 가능: %d개", len(valid_proxies))

        # 2단계 실패 시 1단계 통과한 프록시 사용
        if not valid_proxies:
            _LOGGER.warning("[ProxyMgr] 대상 사이트 접근 가능 프록시 없음, 연결 가능 프록시 사용")
            valid_proxies = connectable

        self._proxies = valid_proxies[:self._max_proxies]
        self._last_refresh = time.time()

        _LOGGER.info("[ProxyMgr] ✓ %d개 프록시 확보", len(self._proxies))

        self._current_proxy = self._select_best_proxy()
        self._init_attempts = 0
        return True

    async def get_proxy(self) -> str | None:
        """현재 프록시 URL 반환."""
        if not self._enabled or self._direct_mode:
            return None

        # 갱신 필요 확인
        if time.time() - self._last_refresh > self._refresh_interval:
            _LOGGER.info("[ProxyMgr] 프록시 목록 갱신 필요")
            asyncio.create_task(self._refresh_proxies())

        if not self._current_proxy:
            if not self._proxies:
                return None
            self._current_proxy = self._select_best_proxy()

        if self._current_proxy:
            # SOCKS5는 aiohttp에서 직접 지원 안 함, HTTP만 반환
            if self._current_proxy.protocol == "socks5":
                # SOCKS5 프록시 건너뛰기 (aiohttp-socks 없이는 사용 불가)
                self._current_proxy = self._select_best_proxy(exclude_socks=True)

            if self._current_proxy:
                self._current_proxy.last_used = time.time()
                return self._current_proxy.url

        return None

    async def rotate_proxy(self, failed: bool = False) -> str | None:
        """다음 프록시로 로테이션."""
        async with self._lock:
            if self._current_proxy and failed:
                self._current_proxy.fail_count += 1
                _LOGGER.debug(
                    "[ProxyMgr] 프록시 실패: %s (실패 %d회)",
                    self._current_proxy.host,
                    self._current_proxy.fail_count,
                )

                # 2회 이상 실패 시 제거 (기준 완화)
                if self._current_proxy.fail_count >= 2:
                    self._proxies = [p for p in self._proxies if p != self._current_proxy]
                    _LOGGER.info("[ProxyMgr] 프록시 제거: %s", self._current_proxy.host)

            # 새 프록시 선택
            self._current_proxy = self._select_best_proxy(exclude_socks=True)

            if self._current_proxy:
                _LOGGER.info(
                    "[ProxyMgr] 프록시 로테이션: %s:%d (남은 %d개)",
                    self._current_proxy.host,
                    self._current_proxy.port,
                    len(self._proxies),
                )
                return self._current_proxy.url

            # 프록시 소진 시 갱신
            _LOGGER.warning("[ProxyMgr] 프록시 소진, 목록 갱신 시도...")
            await self._refresh_proxies()

            if self._proxies:
                self._current_proxy = self._select_best_proxy(exclude_socks=True)
                if self._current_proxy:
                    return self._current_proxy.url

            # 모든 프록시 실패 시 직접 연결 모드
            _LOGGER.warning("[ProxyMgr] 모든 프록시 실패, 직접 연결 시도")
            self._direct_mode = True
            return None

    def record_success(self) -> None:
        if self._current_proxy:
            self._current_proxy.success_count += 1
            # 직접 연결 모드에서 성공하면 프록시 모드로 복귀
            if self._direct_mode:
                _LOGGER.info("[ProxyMgr] 직접 연결 성공, 프록시 모드 유지")

    def record_failure(self) -> None:
        if self._current_proxy:
            self._current_proxy.fail_count += 1

    async def _fetch_proxy_lists(self, urls: list[str], protocol: str) -> list[ProxyInfo]:
        """프록시 목록 수집."""
        all_proxies: list[ProxyInfo] = []
        seen: set[str] = set()

        async def fetch_one(url: str) -> list[ProxyInfo]:
            try:
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        return []
                    text = await resp.text()
                    return self._parse_proxy_list(text, protocol)
            except Exception as e:
                _LOGGER.debug("[ProxyMgr] 수집 실패 %s: %s", url[:50], e)
                return []

        # 병렬 수집
        tasks = [fetch_one(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                for proxy in result:
                    key = f"{proxy.host}:{proxy.port}"
                    if key not in seen:
                        seen.add(key)
                        all_proxies.append(proxy)

        return all_proxies

    def _parse_proxy_list(self, text: str, protocol: str) -> list[ProxyInfo]:
        """프록시 텍스트 파싱."""
        proxies: list[ProxyInfo] = []
        pattern = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{2,5})")

        for match in pattern.finditer(text):
            host = match.group(1)
            port = int(match.group(2))
            if 1 <= port <= 65535:
                proxies.append(ProxyInfo(host=host, port=port, protocol=protocol))

        return proxies

    async def _validate_connectivity(self, proxies: list[ProxyInfo]) -> list[ProxyInfo]:
        """1단계: 기본 연결성 검증 (빠른 테스트)."""
        valid: list[ProxyInfo] = []
        semaphore = asyncio.Semaphore(50)  # 병렬 50개

        # 간단한 테스트 URL (빠른 응답)
        test_url = "http://httpbin.org/ip"

        async def test(proxy: ProxyInfo) -> ProxyInfo | None:
            if proxy.protocol == "socks5":
                # SOCKS5는 별도 라이브러리 필요, 일단 스킵
                return None

            async with semaphore:
                try:
                    start = time.time()
                    connector = aiohttp.TCPConnector(ssl=False)
                    timeout = aiohttp.ClientTimeout(total=8)

                    async with aiohttp.ClientSession(connector=connector) as session:
                        async with session.get(
                            test_url,
                            proxy=proxy.url,
                            timeout=timeout,
                            headers={"User-Agent": "Mozilla/5.0"},
                        ) as resp:
                            if resp.status == 200:
                                proxy.response_time = (time.time() - start) * 1000
                                return proxy
                except Exception:
                    pass
                return None

        # 최대 300개 테스트
        sample = random.sample(proxies, min(300, len(proxies)))
        _LOGGER.info("[ProxyMgr] 연결성 검증: %d개 테스트 중...", len(sample))

        tasks = [test(p) for p in sample]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, ProxyInfo):
                valid.append(r)

        valid.sort(key=lambda p: p.response_time)
        return valid

    async def _validate_target_access(self, proxies: list[ProxyInfo]) -> list[ProxyInfo]:
        """2단계: 대상 사이트 접근 검증 (HTTPS 터널링 테스트 포함)."""
        valid: list[ProxyInfo] = []
        semaphore = asyncio.Semaphore(20)

        # SSL 컨텍스트 설정 (인증서 검증 완화 - 프록시 환경에서 필요)
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        async def test(proxy: ProxyInfo) -> ProxyInfo | None:
            async with semaphore:
                try:
                    start = time.time()
                    # HTTPS 터널링 테스트를 위해 SSL 컨텍스트 사용
                    connector = aiohttp.TCPConnector(ssl=ssl_context)
                    timeout = aiohttp.ClientTimeout(total=self._proxy_timeout)

                    async with aiohttp.ClientSession(connector=connector) as session:
                        async with session.get(
                            self._test_url,
                            proxy=proxy.url,
                            timeout=timeout,
                            headers={
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                                "Accept-Encoding": "gzip, deflate",
                                "Connection": "keep-alive",
                            },
                        ) as resp:
                            # 200, 403, 302도 연결은 됨 (HTTPS 터널링 성공)
                            if resp.status in (200, 302, 403):
                                proxy.response_time = (time.time() - start) * 1000
                                if resp.status == 200:
                                    proxy.success_count = 1  # 완전 성공
                                _LOGGER.debug("[ProxyMgr] ✓ HTTPS 검증 성공: %s:%d (status=%d)",
                                             proxy.host, proxy.port, resp.status)
                                return proxy
                except asyncio.TimeoutError:
                    _LOGGER.debug("[ProxyMgr] 타임아웃: %s:%d", proxy.host, proxy.port)
                except Exception as e:
                    _LOGGER.debug("[ProxyMgr] 검증 실패: %s:%d - %s", proxy.host, proxy.port, str(e)[:50])
                return None

        _LOGGER.info("[ProxyMgr] 대상 사이트 HTTPS 검증: %d개 테스트 중...", len(proxies))

        tasks = [test(p) for p in proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, ProxyInfo):
                valid.append(r)

        # 200 성공한 것 우선, 그 다음 응답 시간 순
        valid.sort(key=lambda p: (-p.success_count, p.response_time))
        return valid

    def _select_best_proxy(self, exclude_socks: bool = False) -> ProxyInfo | None:
        """최적의 프록시 선택."""
        if not self._proxies:
            return None

        available = [p for p in self._proxies if p != self._current_proxy]
        if exclude_socks:
            available = [p for p in available if p.protocol != "socks5"]

        if not available:
            available = [p for p in self._proxies if p.protocol != "socks5"] if exclude_socks else self._proxies

        if not available:
            return None

        # 성공률 기반 가중치
        weights = [p.success_rate + 0.1 for p in available]
        total = sum(weights)
        weights = [w / total for w in weights]

        return random.choices(available, weights=weights, k=1)[0]

    async def _refresh_proxies(self) -> None:
        """프록시 목록 갱신."""
        async with self._lock:
            _LOGGER.info("[ProxyMgr] 프록시 목록 갱신...")

            http_proxies = await self._fetch_proxy_lists(PROXY_LIST_URLS, "http")
            if http_proxies:
                connectable = await self._validate_connectivity(http_proxies)
                if connectable:
                    # 기존 좋은 프록시 유지
                    good = [p for p in self._proxies if p.success_rate > 0.3]
                    combined = good + connectable

                    seen: set[str] = set()
                    unique: list[ProxyInfo] = []
                    for p in combined:
                        key = f"{p.host}:{p.port}"
                        if key not in seen:
                            seen.add(key)
                            unique.append(p)

                    self._proxies = unique[:self._max_proxies]
                    self._last_refresh = time.time()
                    self._direct_mode = False
                    _LOGGER.info("[ProxyMgr] ✓ 프록시 갱신 완료: %d개", len(self._proxies))

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "direct_mode": self._direct_mode,
            "total_proxies": len(self._proxies),
            "current_proxy": self._current_proxy.url if self._current_proxy else None,
            "last_refresh": self._last_refresh,
        }
