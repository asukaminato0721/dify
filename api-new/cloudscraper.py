"""Minimal cloudscraper compatibility shim."""

from __future__ import annotations

import httpx


class _Scraper:
    def __init__(self) -> None:
        self.perform_request = None

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        if callable(self.perform_request):
            return self.perform_request("GET", url, **kwargs)
        with httpx.Client(follow_redirects=True) as client:
            response = client.get(url, **kwargs)
            response.raise_for_status()
            return response


def create_scraper() -> _Scraper:
    return _Scraper()
