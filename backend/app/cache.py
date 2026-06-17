import json
import time
from typing import Any, Protocol


class JsonCache(Protocol):
    def get_json(self, key: str) -> Any | None:
        ...

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        ...


class InMemoryJsonCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, Any]] = {}

    def get_json(self, key: str) -> Any | None:
        cached = self._values.get(key)
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= time.monotonic():
            self._values.pop(key, None)
            return None
        return value

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._values[key] = (time.monotonic() + ttl_seconds, value)


class RedisJsonCache:
    def __init__(
        self,
        url: str,
        prefix: str = "market-monitor",
        socket_timeout: float = 0.25,
    ) -> None:
        import redis

        self.prefix = prefix
        self.client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
        )

    def get_json(self, key: str) -> Any | None:
        try:
            raw = self.client.get(self._key(key))
        except Exception:
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            self.client.setex(self._key(key), ttl_seconds, json.dumps(value, ensure_ascii=False))
        except Exception:
            return

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"
