# custom_components/donghang_lottery/storage.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1


@dataclass
class MyNumbers:
    lotto645: list[list[int]] = field(default_factory=list)
    pension720: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"lotto645": self.lotto645, "pension720": self.pension720}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MyNumbers":
        return cls(
            lotto645=[list(map(int, items)) for items in data.get("lotto645", []) or []],
            pension720=[str(item) for item in data.get("pension720", []) or []],
        )


class MyNumberStore:
    def __init__(self, hass, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self.data = MyNumbers()

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.data = MyNumbers.from_dict(data)

    async def async_save(self) -> None:
        await self._store.async_save(self.data.to_dict())
