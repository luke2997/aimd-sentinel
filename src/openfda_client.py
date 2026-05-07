from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import settings


class OpenFDAError(RuntimeError):
    pass


class OpenFDAClient:
    """Tiny openFDA client with pagination and optional API key support."""

    BASE = "https://api.fda.gov"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or settings.openfda_api_key
        self.client = httpx.Client(timeout=timeout, headers={"User-Agent": "aimd-sentinel-mvp/0.1"})

    def close(self) -> None:
        self.client.close()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, OpenFDAError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    def get(self, endpoint: str, *, search: str | None = None, limit: int = 100, skip: int = 0) -> dict[str, Any]:
        endpoint = endpoint.strip("/")
        url = f"{self.BASE}/{endpoint}.json"
        params: dict[str, Any] = {"limit": min(limit, 1000), "skip": skip}
        if search:
            params["search"] = search
        if self.api_key:
            params["api_key"] = self.api_key

        response = self.client.get(url, params=params)
        if response.status_code in {400, 404}:
            # 400 usually means a single malformed/unsupported search expression.
            # For best-effort ingestion, skip that query instead of killing the run.
            return {"meta": {"warning": f"openFDA returned {response.status_code}"}, "results": []}
        if response.status_code in {429, 500, 502, 503, 504}:
            raise OpenFDAError(f"openFDA transient error {response.status_code}: {response.text[:300]}")
        response.raise_for_status()
        return response.json()

    def iter_search(
        self,
        endpoint: str,
        *,
        search: str | None = None,
        per_page: int = 100,
        max_records: int = 1000,
    ) -> Iterator[dict[str, Any]]:
        seen = 0
        skip = 0
        while seen < max_records:
            payload = self.get(endpoint, search=search, limit=min(per_page, max_records - seen), skip=skip)
            results = payload.get("results") or []
            if not results:
                break
            for record in results:
                yield record
                seen += 1
                if seen >= max_records:
                    break
            if len(results) < per_page:
                break
            skip += len(results)
