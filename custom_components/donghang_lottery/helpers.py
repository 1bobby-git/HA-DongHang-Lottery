# custom_components/donghang_lottery/helpers.py
"""공용 헬퍼 함수."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .coordinator import DonghangLotteryData


def get_lotto645_item(data: DonghangLotteryData) -> dict[str, Any]:
    """로또6/45 결과에서 단일 회차 항목 추출.

    api.py returns {drwNo, drwtNo1, ..., _raw: {ltEpsd, tm1WnNo, ...}}
    센서는 원본 API 키(ltEpsd, tm1WnNo, rnk1WnNope 등)를 사용하므로 _raw 반환.
    """
    result = data.lotto645_result or {}
    if "_raw" in result:
        return result["_raw"]
    # 폴백: 중첩된 응답 구조 탐색
    payload = result.get("data", result)
    if isinstance(payload, dict):
        items = payload.get("list") or payload.get("result") or payload.get("data")
        if isinstance(items, list) and items:
            return items[0]
        if isinstance(items, dict):
            return items
        return payload
    if isinstance(payload, list) and payload:
        return payload[0]
    return {}
