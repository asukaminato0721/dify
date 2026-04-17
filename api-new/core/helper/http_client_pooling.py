"""HTTP client pooling utilities."""

from __future__ import annotations

import atexit
import asyncio
import threading
from collections.abc import Callable

import httpx

ClientBuilder = Callable[[], httpx.Client]
AsyncClientBuilder = Callable[[], httpx.AsyncClient]


class HttpClientPoolFactory:
    """Thread-safe factory that maintains reusable HTTP client instances."""

    def __init__(self) -> None:
        self._clients: dict[str, httpx.Client] = {}
        self._lock = threading.Lock()

    def get_or_create(self, key: str, builder: ClientBuilder) -> httpx.Client:
        """Return a pooled client associated with ``key`` creating it on demand."""
        client = self._clients.get(key)
        if client is not None:
            return client

        with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = builder()
                self._clients[key] = client
        return client

    def close_all(self) -> None:
        """Close all pooled clients and clear the pool."""
        with self._lock:
            for client in self._clients.values():
                client.close()
            self._clients.clear()


_factory = HttpClientPoolFactory()


class AsyncHttpClientPoolFactory:
    """Async-client pool with best-effort shutdown semantics."""

    def __init__(self) -> None:
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._lock = threading.Lock()

    def get_or_create(self, key: str, builder: AsyncClientBuilder) -> httpx.AsyncClient:
        client = self._clients.get(key)
        if client is not None:
            return client

        with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = builder()
                self._clients[key] = client
        return client

    async def aclose_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            await client.aclose()


_async_factory = AsyncHttpClientPoolFactory()


def get_pooled_http_client(key: str, builder: ClientBuilder) -> httpx.Client:
    """Return a pooled client for the given ``key`` using ``builder`` when missing."""
    return _factory.get_or_create(key, builder)


def get_pooled_async_http_client(key: str, builder: AsyncClientBuilder) -> httpx.AsyncClient:
    """Return a pooled async client for the given ``key`` using ``builder`` when missing."""
    return _async_factory.get_or_create(key, builder)


def close_all_pooled_clients() -> None:
    """Close every client created through the pooling factory."""
    _factory.close_all()


def close_all_pooled_async_clients() -> None:
    """Best-effort close of pooled async clients on process shutdown."""
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_async_factory.aclose_all())
        loop.close()
    except Exception:
        pass


def _register_shutdown_hook() -> None:
    atexit.register(close_all_pooled_clients)
    atexit.register(close_all_pooled_async_clients)


_register_shutdown_hook()
