"""Exception hierarchy for the AliExpress Affiliate client."""

from __future__ import annotations

from typing import Any, Mapping


class AliExpressError(Exception):
    """Base class for every error raised by this package."""


class ConfigurationError(AliExpressError):
    """Raised when credentials or settings are missing or malformed."""


class TransportError(AliExpressError):
    """Raised when the HTTP call itself fails (DNS, TLS, timeout, proxy)."""


class ApiError(AliExpressError):
    """Raised when the gateway returns an ``error_response`` envelope.

    These are platform-level failures: bad signature, unknown method, throttling,
    missing permission for the API package, and so on.
    """

    def __init__(
        self,
        code: str | int | None,
        message: str | None,
        *,
        sub_code: str | None = None,
        sub_message: str | None = None,
        request_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.sub_code = sub_code
        self.sub_message = sub_message
        self.request_id = request_id
        self.payload = dict(payload or {})
        super().__init__(self._describe())

    def _describe(self) -> str:
        parts = [f"[{self.code}] {self.message}"]
        if self.sub_code or self.sub_message:
            parts.append(f"({self.sub_code}: {self.sub_message})")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " ".join(parts)


class BusinessError(AliExpressError):
    """Raised when the call succeeds but the business result is not ``200``.

    Affiliate methods wrap their payload in ``resp_result`` with its own
    ``resp_code``/``resp_msg`` pair; anything other than 200 lands here.
    """

    def __init__(
        self,
        code: int | None,
        message: str | None,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.payload = dict(payload or {})
        super().__init__(f"[{code}] {message}")


class RateLimitError(ApiError):
    """Raised when the gateway reports that the app exceeded its call quota."""
