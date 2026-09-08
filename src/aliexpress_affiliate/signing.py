"""Request signing for the AliExpress Open Platform (TOP) gateway.

The gateway accepts two signature algorithms:

``sha256``
    ``HMAC-SHA256(app_secret, concatenated_params)`` — the default and the one
    AliExpress recommends for new integrations.
``md5``
    ``MD5(app_secret + concatenated_params + app_secret)`` — legacy, kept here
    because a few older app registrations are still pinned to it.

In both cases ``concatenated_params`` is built the same way: every parameter
that is actually sent (system parameters and business parameters together,
minus ``sign`` itself and minus empty values) is sorted by key and rendered as
``key + value`` with no separators. When the API name travels in the URL path
instead of a ``method`` parameter — the ``/router/rest`` style gateway — that
path is prepended to the string before hashing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .errors import ConfigurationError

SIGN_METHOD_SHA256 = "sha256"
SIGN_METHOD_MD5 = "md5"

#: AliExpress renders human-readable timestamps in Beijing time (GMT+8).
GATEWAY_TZ = timezone(timedelta(hours=8))


def normalize_value(value: Any) -> str:
    """Render a single parameter the way the gateway expects to receive it.

    Booleans become ``true``/``false`` (not Python's ``True``/``False``), and
    nested structures become compact JSON, because the signature is computed
    over exactly the bytes that are put on the wire.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def normalize_params(params: Mapping[str, Any]) -> dict[str, str]:
    """Drop the values the gateway ignores and stringify the rest.

    ``None`` and empty strings are removed: sending them but signing without
    them (or the reverse) is the most common source of ``isv.sign-check-failure``.
    """
    normalized: dict[str, str] = {}
    for key, value in params.items():
        if key == "sign" or value is None:
            continue
        rendered = normalize_value(value)
        if rendered == "":
            continue
        normalized[key] = rendered
    return normalized


def build_sign_source(params: Mapping[str, str], api_path: str | None = None) -> str:
    """Concatenate sorted ``key + value`` pairs, optionally after an API path."""
    concatenated = "".join(f"{key}{params[key]}" for key in sorted(params))
    if api_path:
        return f"{api_path}{concatenated}"
    return concatenated


def sign(
    params: Mapping[str, Any],
    app_secret: str,
    *,
    sign_method: str = SIGN_METHOD_SHA256,
    api_path: str | None = None,
) -> str:
    """Return the uppercase hex signature for ``params``."""
    if not app_secret:
        raise ConfigurationError("app_secret is required to sign a request")

    source = build_sign_source(normalize_params(params), api_path)
    secret_bytes = app_secret.encode("utf-8")
    source_bytes = source.encode("utf-8")

    if sign_method == SIGN_METHOD_SHA256:
        digest = hmac.new(secret_bytes, source_bytes, hashlib.sha256).hexdigest()
    elif sign_method == SIGN_METHOD_MD5:
        digest = hashlib.md5(secret_bytes + source_bytes + secret_bytes).hexdigest()
    else:
        raise ConfigurationError(
            f"unsupported sign_method {sign_method!r}; "
            f"use {SIGN_METHOD_SHA256!r} or {SIGN_METHOD_MD5!r}"
        )
    return digest.upper()


def timestamp_ms(now: datetime | None = None) -> str:
    """Milliseconds since the epoch — what the ``/sync`` gateway expects."""
    moment = now or datetime.now(timezone.utc)
    return str(int(moment.timestamp() * 1000))


def timestamp_datetime(now: datetime | None = None) -> str:
    """``yyyy-MM-dd HH:mm:ss`` in GMT+8 — what the legacy gateway expects."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(GATEWAY_TZ).strftime("%Y-%m-%d %H:%M:%S")
