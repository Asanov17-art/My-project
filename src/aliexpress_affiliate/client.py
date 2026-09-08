"""Low-level client for the AliExpress Open Platform gateway."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .errors import (
    ApiError,
    BusinessError,
    ConfigurationError,
    RateLimitError,
    TransportError,
)
from .signing import (
    SIGN_METHOD_MD5,
    SIGN_METHOD_SHA256,
    normalize_params,
    sign,
    timestamp_datetime,
    timestamp_ms,
)

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY = "https://api-sg.aliexpress.com/sync"

#: Platform error codes worth retrying: the app is over its per-second quota
#: (7 / ApiCallLimit) or the backend hiccuped (15 / remote service error).
RETRYABLE_ERROR_CODES = {"7", "15", "22", "23"}
RETRYABLE_SUB_CODES = {"isp.top-remote-connection-timeout", "isp.top-remote-service-unavailable"}

#: ``isv.*`` sub-codes blame the caller — a bad signature, a missing API
#: package, an unknown tracking id. They arrive under retryable top-level codes
#: (``isv.permission-deny`` comes back as code 15) but will never succeed on a
#: retry, so the sub-code decides.
PERMANENT_SUB_CODE_PREFIX = "isv."


class Transport(Protocol):
    """Anything that can turn a signed form POST into ``(status, body)``."""

    def __call__(
        self,
        url: str,
        data: Mapping[str, str],
        *,
        timeout: float,
    ) -> tuple[int, str]:  # pragma: no cover - protocol definition
        ...


class RequestsTransport:
    """Default transport, backed by :mod:`requests` with a pooled session."""

    def __init__(self, session: Any = None) -> None:
        if session is None:
            import requests  # imported lazily so tests need no HTTP stack

            session = requests.Session()
        self._session = session

    def __call__(self, url: str, data: Mapping[str, str], *, timeout: float) -> tuple[int, str]:
        import requests

        try:
            response = self._session.post(
                url,
                data=dict(data),
                timeout=timeout,
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
            )
        except requests.RequestException as exc:
            raise TransportError(f"request to {url} failed: {exc}") from exc
        return response.status_code, response.text


@dataclass(slots=True)
class ClientConfig:
    """Everything the client needs to talk to the gateway."""

    app_key: str
    app_secret: str
    gateway: str = DEFAULT_GATEWAY
    sign_method: str = SIGN_METHOD_SHA256
    timeout: float = 20.0
    max_retries: int = 3
    backoff_base: float = 0.5
    #: The ``/sync`` gateway wants epoch milliseconds; the legacy
    #: ``/router/rest`` gateway wants ``yyyy-MM-dd HH:mm:ss`` in GMT+8.
    timestamp_style: str = "ms"
    #: Set for path-style gateways so the API path joins the signature source.
    api_path: str | None = None
    #: ``simplify=true`` asks the gateway to drop the redundant single-child
    #: wrappers from its JSON. The parsers here accept both shapes.
    simplify: bool = True
    extra_params: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.app_key:
            raise ConfigurationError("app_key is required")
        if not self.app_secret:
            raise ConfigurationError("app_secret is required")
        if self.sign_method not in (SIGN_METHOD_SHA256, SIGN_METHOD_MD5):
            raise ConfigurationError(f"unsupported sign_method {self.sign_method!r}")
        if self.timestamp_style not in ("ms", "datetime"):
            raise ConfigurationError(f"unsupported timestamp_style {self.timestamp_style!r}")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **overrides: Any) -> "ClientConfig":
        """Build a config from ``ALIEXPRESS_*`` environment variables."""
        source = os.environ if env is None else env
        values: dict[str, Any] = {
            "app_key": source.get("ALIEXPRESS_APP_KEY", ""),
            "app_secret": source.get("ALIEXPRESS_APP_SECRET", ""),
            "gateway": source.get("ALIEXPRESS_GATEWAY", DEFAULT_GATEWAY),
            "sign_method": source.get("ALIEXPRESS_SIGN_METHOD", SIGN_METHOD_SHA256),
        }
        if "ALIEXPRESS_TIMEOUT" in source:
            values["timeout"] = float(source["ALIEXPRESS_TIMEOUT"])
        values.update(overrides)
        missing = [k for k in ("app_key", "app_secret") if not values.get(k)]
        if missing:
            raise ConfigurationError(
                "missing credentials: "
                + ", ".join(f"ALIEXPRESS_{k.upper()}" for k in missing)
                + " (copy .env.example to .env and fill it in)"
            )
        return cls(**values)


class TopClient:
    """Signs, sends and unwraps a single gateway call.

    The class deliberately knows nothing about affiliate semantics — it handles
    signatures, retries and the two error envelopes the platform can return.
    :class:`~aliexpress_affiliate.affiliate.AffiliateClient` builds on top of it.
    """

    def __init__(
        self,
        config: ClientConfig,
        transport: Transport | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._transport = transport or RequestsTransport()
        self._sleep = sleep

    # -- request building -------------------------------------------------

    def build_payload(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, str]:
        """Return the fully signed form body for ``method``."""
        payload: dict[str, Any] = {
            "app_key": self.config.app_key,
            "method": method,
            "sign_method": self.config.sign_method,
            "format": "json",
            "v": "2.0",
            "simplify": "true" if self.config.simplify else "false",
            "timestamp": (
                timestamp_ms() if self.config.timestamp_style == "ms" else timestamp_datetime()
            ),
        }
        payload.update(self.config.extra_params)
        payload.update(params or {})
        normalized = normalize_params(payload)
        normalized["sign"] = sign(
            normalized,
            self.config.app_secret,
            sign_method=self.config.sign_method,
            api_path=self.config.api_path,
        )
        return normalized

    # -- request execution ------------------------------------------------

    def call(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Call ``method`` and return the unwrapped response body.

        Retries transport failures, 5xx responses and the platform's own
        throttling codes with exponential backoff plus jitter.
        """
        attempt = 0
        while True:
            attempt += 1
            payload = self.build_payload(method, params)
            try:
                status, text = self._transport(
                    self.config.gateway, payload, timeout=self.config.timeout
                )
                if status >= 500:
                    raise TransportError(f"gateway returned HTTP {status}: {text[:200]}")
                return self._parse(method, status, text)
            except (TransportError, RateLimitError) as exc:
                if attempt > self.config.max_retries:
                    raise
                delay = self.config.backoff_base * (2 ** (attempt - 1))
                delay += random.uniform(0, self.config.backoff_base)
                logger.warning(
                    "%s failed (attempt %d/%d): %s — retrying in %.2fs",
                    method,
                    attempt,
                    self.config.max_retries,
                    exc,
                    delay,
                )
                self._sleep(delay)

    # -- response handling ------------------------------------------------

    def _parse(self, method: str, status: int, text: str) -> dict[str, Any]:
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TransportError(
                f"{method} returned non-JSON body (HTTP {status}): {text[:200]}"
            ) from exc
        if not isinstance(body, dict):
            raise TransportError(f"{method} returned unexpected JSON payload: {type(body).__name__}")

        if "error_response" in body:
            raise self._build_api_error(body["error_response"])

        # Success envelopes are keyed by the method name with dots replaced by
        # underscores, e.g. ``aliexpress_affiliate_link_generate_response``.
        for key, value in body.items():
            if key.endswith("_response") and isinstance(value, dict):
                return value
        return body

    @staticmethod
    def _build_api_error(error: Mapping[str, Any]) -> ApiError:
        code = str(error.get("code")) if error.get("code") is not None else None
        sub_code = error.get("sub_code")
        kwargs: dict[str, Any] = {
            "sub_code": sub_code,
            "sub_message": error.get("sub_msg"),
            "request_id": error.get("request_id"),
            "payload": error,
        }
        caller_fault = isinstance(sub_code, str) and sub_code.startswith(PERMANENT_SUB_CODE_PREFIX)
        retryable = code in RETRYABLE_ERROR_CODES or sub_code in RETRYABLE_SUB_CODES
        if retryable and not caller_fault:
            return RateLimitError(code, error.get("msg"), **kwargs)
        return ApiError(code, error.get("msg"), **kwargs)


def unwrap_result(body: Mapping[str, Any]) -> Any:
    """Return the payload inside an affiliate ``resp_result`` envelope.

    Affiliate methods answer with ``{"resp_result": {"resp_code": 200,
    "resp_msg": "...", "result": {...}}}``. Some methods (and the gateway's
    ``simplify`` mode) skip the wrapper entirely, so the plain body is passed
    through untouched.
    """
    result = body.get("resp_result", body)
    if isinstance(result, Mapping) and "resp_code" in result:
        code = result.get("resp_code")
        if code not in (200, "200"):
            raise BusinessError(code, result.get("resp_msg"), payload=dict(result))
        return result.get("result", {})
    return result
