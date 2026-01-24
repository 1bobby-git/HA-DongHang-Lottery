# custom_components/donghang_lottery/proxy_manager.py
"""프록시 관리자 - 무료 프록시 자동 수집 및 로테이션."""

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

# 무료 프록시 목록 제공 URL들
PROXY_LIST_URLS = [
    # Free Proxy List (JSON API)
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
]

# 한국 프록시 우선 (동행복권은 한국 서비스)
KOREA_PROXY_URLS = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",  # 전체에서 KR 필터링
]


@dataclass
class ProxyInfo:
    """프록시 정보."""
    host: str
    port: int
    protocol: str = "http"  # http, https, socks4, socks5
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
    """프록시 관리자.

    기능:
    - 무료 프록시 목록 자동 수집
    - 프록시 유효성 검증
    - 성공률 기반 프록시 로테이션
    - 실패한 프록시 자동 제외
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        test_url: str = "https://www.dhlottery.co.kr/",
        max_proxies: int = 50,
        proxy_timeout: float = 10.0,
        refresh_interval: int = 1800,  # 30분마다 갱신
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

        # 프록시 비활성화 옵션 (직접 연결 시도용)
        self._enabled = True
        self._direct_mode = False  # 프록시 없이 직접 연결

        _LOGGER.info("[ProxyMgr] 프록시 관리자 초기화 완료")

    @property
    def enabled(self) -> bool:
        """프록시 활성화 여부."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """프록시 활성화 설정."""
        self._enabled = value
        _LOGGER.info("[ProxyMgr] 프록시 %s", "활성화" if value else "비활성화")

    @property
    def current_proxy(self) -> ProxyInfo | None:
        """현재 사용 중인 프록시."""
        return self._current_proxy

    @property
    def proxy_count(self) -> int:
        """사용 가능한 프록시 수."""
        return len(self._proxies)

    async def initialize(self) -> bool:
        """프록시 목록 초기화 및 검증.

        Returns:
            성공 여부
        """
        _LOGGER.info("[ProxyMgr] 프록시 목록 초기화 시작...")

        # 프록시 목록 수집
        raw_proxies = await self._fetch_proxy_lists()
        if not raw_proxies:
            _LOGGER.warning("[ProxyMgr] 프록시 목록 수집 실패")
            return False

        _LOGGER.info("[ProxyMgr] %d개 프록시 후보 수집됨", len(raw_proxies))

        # 프록시 검증 (병렬 처리)
        valid_proxies = await self._validate_proxies(raw_proxies)
        if not valid_proxies:
            _LOGGER.warning("[ProxyMgr] 유효한 프록시 없음")
            return False

        self._proxies = valid_proxies[:self._max_proxies]
        self._last_refresh = time.time()

        _LOGGER.info("[ProxyMgr] ✓ %d개 유효 프록시 확보", len(self._proxies))

        # 첫 번째 프록시 선택
        self._current_proxy = self._select_best_proxy()
        return True

    async def get_proxy(self) -> str | None:
        """현재 프록시 URL 반환. 필요 시 갱신.

        Returns:
            프록시 URL (예: "http://1.2.3.4:8080") 또는 None (직접 연결)
        """
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
            self._current_proxy.last_used = time.time()
            return self._current_proxy.url

        return None

    async def rotate_proxy(self, failed: bool = False) -> str | None:
        """다음 프록시로 로테이션.

        Args:
            failed: 현재 프록시 실패 여부

        Returns:
            새 프록시 URL 또는 None
        """
        async with self._lock:
            if self._current_proxy and failed:
                self._current_proxy.fail_count += 1
                _LOGGER.debug(
                    "[ProxyMgr] 프록시 실패 기록: %s (실패 %d회)",
                    self._current_proxy.host,
                    self._current_proxy.fail_count,
                )

                # 실패율 높은 프록시 제거
                if self._current_proxy.fail_count >= 3:
                    self._proxies = [p for p in self._proxies if p != self._current_proxy]
                    _LOGGER.info(
                        "[ProxyMgr] 프록시 제거: %s (3회 이상 실패)",
                        self._current_proxy.host,
                    )

            # 새 프록시 선택
            self._current_proxy = self._select_best_proxy()

            if self._current_proxy:
                _LOGGER.info(
                    "[ProxyMgr] 프록시 로테이션: %s:%d",
                    self._current_proxy.host,
                    self._current_proxy.port,
                )
                return self._current_proxy.url

            # 프록시 소진 시 갱신 시도
            _LOGGER.warning("[ProxyMgr] 사용 가능한 프록시 없음, 목록 갱신 시도")
            await self._refresh_proxies()

            if self._proxies:
                self._current_proxy = self._select_best_proxy()
                if self._current_proxy:
                    return self._current_proxy.url

            return None

    def record_success(self) -> None:
        """현재 프록시 성공 기록."""
        if self._current_proxy:
            self._current_proxy.success_count += 1

    def record_failure(self) -> None:
        """현재 프록시 실패 기록."""
        if self._current_proxy:
            self._current_proxy.fail_count += 1

    async def _fetch_proxy_lists(self) -> list[ProxyInfo]:
        """여러 소스에서 프록시 목록 수집."""
        all_proxies: list[ProxyInfo] = []
        seen_hosts: set[str] = set()

        for url in PROXY_LIST_URLS:
            try:
                async with self._session.get(url, timeout=15) as resp:
                    if resp.status != 200:
                        continue

                    text = await resp.text()
                    proxies = self._parse_proxy_list(text)

                    for proxy in proxies:
                        key = f"{proxy.host}:{proxy.port}"
                        if key not in seen_hosts:
                            seen_hosts.add(key)
                            all_proxies.append(proxy)

                    _LOGGER.debug("[ProxyMgr] %s: %d개 수집", url.split("/")[-1][:30], len(proxies))

            except Exception as err:
                _LOGGER.debug("[ProxyMgr] 프록시 목록 수집 실패 (%s): %s", url[:50], err)
                continue

        return all_proxies

    def _parse_proxy_list(self, text: str) -> list[ProxyInfo]:
        """프록시 텍스트 파싱."""
        proxies: list[ProxyInfo] = []

        # IP:PORT 패턴
        pattern = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{2,5})")

        for match in pattern.finditer(text):
            host = match.group(1)
            port = int(match.group(2))

            # 유효한 포트 범위 확인
            if 1 <= port <= 65535:
                proxies.append(ProxyInfo(host=host, port=port))

        return proxies

    async def _validate_proxies(
        self,
        proxies: list[ProxyInfo],
        max_concurrent: int = 20,
    ) -> list[ProxyInfo]:
        """프록시 유효성 검증 (병렬 처리)."""
        valid_proxies: list[ProxyInfo] = []
        semaphore = asyncio.Semaphore(max_concurrent)

        async def test_proxy(proxy: ProxyInfo) -> ProxyInfo | None:
            async with semaphore:
                try:
                    start = time.time()
                    connector = aiohttp.TCPConnector(ssl=False)

                    async with aiohttp.ClientSession(connector=connector) as session:
                        async with session.get(
                            self._test_url,
                            proxy=proxy.url,
                            timeout=aiohttp.ClientTimeout(total=self._proxy_timeout),
                            headers={"User-Agent": "Mozilla/5.0"},
                        ) as resp:
                            if resp.status == 200:
                                proxy.response_time = (time.time() - start) * 1000
                                return proxy

                except Exception:
                    pass

                return None

        # 최대 100개만 테스트 (시간 절약)
        test_proxies = random.sample(proxies, min(100, len(proxies)))

        _LOGGER.info("[ProxyMgr] %d개 프록시 검증 중...", len(test_proxies))

        tasks = [test_proxy(p) for p in test_proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, ProxyInfo):
                valid_proxies.append(result)

        # 응답 시간 순 정렬
        valid_proxies.sort(key=lambda p: p.response_time)

        return valid_proxies

    def _select_best_proxy(self) -> ProxyInfo | None:
        """최적의 프록시 선택 (성공률 + 응답시간 기반)."""
        if not self._proxies:
            return None

        # 현재 프록시 제외
        available = [p for p in self._proxies if p != self._current_proxy]
        if not available:
            available = self._proxies

        # 성공률 기반 가중치 랜덤 선택
        weights = [p.success_rate + 0.1 for p in available]
        total = sum(weights)
        weights = [w / total for w in weights]

        return random.choices(available, weights=weights, k=1)[0]

    async def _refresh_proxies(self) -> None:
        """프록시 목록 갱신."""
        async with self._lock:
            _LOGGER.info("[ProxyMgr] 프록시 목록 갱신 시작...")

            raw_proxies = await self._fetch_proxy_lists()
            if raw_proxies:
                valid_proxies = await self._validate_proxies(raw_proxies)
                if valid_proxies:
                    # 기존 성공률 높은 프록시 유지
                    good_existing = [p for p in self._proxies if p.success_rate > 0.5]
                    combined = good_existing + valid_proxies

                    # 중복 제거
                    seen: set[str] = set()
                    unique: list[ProxyInfo] = []
                    for p in combined:
                        key = f"{p.host}:{p.port}"
                        if key not in seen:
                            seen.add(key)
                            unique.append(p)

                    self._proxies = unique[:self._max_proxies]
                    self._last_refresh = time.time()
                    _LOGGER.info("[ProxyMgr] ✓ 프록시 목록 갱신 완료: %d개", len(self._proxies))

    def get_status(self) -> dict[str, Any]:
        """프록시 상태 정보 반환."""
        return {
            "enabled": self._enabled,
            "direct_mode": self._direct_mode,
            "total_proxies": len(self._proxies),
            "current_proxy": self._current_proxy.url if self._current_proxy else None,
            "last_refresh": self._last_refresh,
        }
