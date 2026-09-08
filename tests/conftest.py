"""Shared fixtures: a fake transport that records requests and replays bodies."""

from __future__ import annotations

import json
from typing import Any, Mapping

import pytest

from aliexpress_affiliate.affiliate import AffiliateClient
from aliexpress_affiliate.client import ClientConfig, TopClient


class FakeTransport:
    """Stand-in for the HTTP layer: replays queued responses, records payloads."""

    def __init__(self, responses: list[tuple[int, Any]] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[dict[str, str]] = []

    def queue(self, body: Any, status: int = 200) -> "FakeTransport":
        self.responses.append((status, body))
        return self

    @property
    def last_request(self) -> dict[str, str]:
        return self.requests[-1]

    def __call__(self, url: str, data: Mapping[str, str], *, timeout: float) -> tuple[int, str]:
        self.requests.append(dict(data))
        if not self.responses:
            raise AssertionError("FakeTransport ran out of queued responses")
        status, body = self.responses.pop(0)
        return status, body if isinstance(body, str) else json.dumps(body)


@pytest.fixture
def config() -> ClientConfig:
    return ClientConfig(
        app_key="123456",
        app_secret="top-secret",
        max_retries=2,
        backoff_base=0.0,
    )


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def top_client(config: ClientConfig, transport: FakeTransport) -> TopClient:
    return TopClient(config, transport, sleep=lambda _seconds: None)


@pytest.fixture
def affiliate(config: ClientConfig, top_client: TopClient) -> AffiliateClient:
    return AffiliateClient(config, tracking_id="demo-tracking", client=top_client)
