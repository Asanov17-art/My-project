"""Self-check for a fresh set of credentials.

The affiliate API fails in a handful of predictable ways, and the gateway
reports all of them the same way: an ``error_response`` with a numeric code and
a ``sub_code``. This module runs the smallest possible call for each layer of
the setup — credentials, API package permission, tracking id — and translates
whatever comes back into a concrete next step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .affiliate import AffiliateClient
from .errors import (
    ApiError,
    BusinessError,
    ConfigurationError,
    RateLimitError,
    TransportError,
)

#: A real, long-lived listing used only to prove that link generation works.
PROBE_URL = "https://www.aliexpress.com/item/1005006284925019.html"

OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"

#: sub_code -> what the operator should actually do about it.
SUB_CODE_HINTS = {
    "isv.sign-check-failure": (
        "ALIEXPRESS_APP_SECRET is wrong, or this machine's clock is off by more "
        "than a few minutes (the signature covers the timestamp)."
    ),
    "isv.invalid-signature": "ALIEXPRESS_APP_SECRET does not match ALIEXPRESS_APP_KEY.",
    "isv.permission-deny": (
        "The app is not allowed to call this method: subscribe to the Affiliate "
        "API package on openservice.aliexpress.com and wait for approval."
    ),
    "isv.permission-api-package-not-exist": (
        "The Affiliate API package is not attached to this app yet."
    ),
    "isv.invalid-parameter": "The gateway rejected a parameter value.",
    "isv.tracking-id-not-exist": (
        "ALIEXPRESS_TRACKING_ID does not exist for this account; create one in "
        "the AliExpress affiliate console and copy it exactly."
    ),
}

CODE_HINTS = {
    "7": "The app is over its call quota — wait and retry.",
    "15": "The platform's own backend failed; usually transient.",
    "25": "The signature was rejected — check ALIEXPRESS_APP_SECRET.",
    "27": "Invalid or expired app credentials.",
    "40": "Missing a required parameter.",
    "41": "A parameter has the wrong type.",
    "43": "A parameter failed the gateway's validation.",
}


@dataclass(slots=True)
class Check:
    """One diagnostic step and what it proved (or failed to prove)."""

    name: str
    status: str
    detail: str
    hint: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == OK

    def format(self) -> str:
        marker = {OK: "PASS", FAILED: "FAIL", SKIPPED: "SKIP"}[self.status]
        lines = [f"[{marker}] {self.name}: {self.detail}"]
        if self.hint:
            lines.append(f"       -> {self.hint}")
        return "\n".join(lines)


def explain(error: ApiError) -> str:
    """Turn a gateway error into an instruction, falling back to its own text."""
    if error.sub_code and error.sub_code in SUB_CODE_HINTS:
        return SUB_CODE_HINTS[error.sub_code]
    if error.code is not None and str(error.code) in CODE_HINTS:
        return CODE_HINTS[str(error.code)]
    return error.sub_message or error.message or "See the gateway's message above."


def mask(value: str | None) -> str:
    """Show enough of a secret to recognise it, never enough to leak it."""
    if not value:
        return "(not set)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def _run_step(name: str, action: Callable[[], str]) -> Check:
    """Run one probe, mapping every known failure onto an actionable hint."""
    try:
        return Check(name, OK, action())
    except RateLimitError as exc:
        return Check(name, FAILED, str(exc), "Quota exceeded — wait a minute and run doctor again.")
    except ApiError as exc:
        return Check(name, FAILED, str(exc), explain(exc))
    except BusinessError as exc:
        return Check(name, FAILED, str(exc), "The call went through but the API refused the request.")
    except TransportError as exc:
        return Check(
            name,
            FAILED,
            str(exc),
            "The gateway was unreachable: check connectivity, proxy rules and firewall.",
        )
    except ConfigurationError as exc:
        return Check(name, FAILED, str(exc), "Fix the configuration and run doctor again.")


def check_credentials(client: AffiliateClient) -> Check:
    """Credentials and Affiliate permission, proven by the cheapest real call."""

    def action() -> str:
        categories = client.categories()
        return f"gateway accepted the signature, {len(categories)} categories returned"

    return _run_step("credentials + affiliate permission", action)


def check_search(client: AffiliateClient) -> Check:
    """Product search — the endpoint most integrations actually live on."""

    def action() -> str:
        page = client.search_products("usb cable", page_size=1)
        found = page.total_record_count or 0
        sample = page.products[0].title if page.products else "no sample returned"
        return f"{found} matches for 'usb cable' ({sample})"

    return _run_step("product search", action)


def check_tracking_id(client: AffiliateClient) -> Check:
    """Tracking id, proven by generating one real affiliate link."""
    if not client.tracking_id:
        return Check(
            "tracking id",
            SKIPPED,
            "ALIEXPRESS_TRACKING_ID is not set",
            "Link generation needs it; search and categories work without it.",
        )

    def action() -> str:
        link = client.generate_link(PROBE_URL)
        if not link or not link.promotion_link:
            raise BusinessError(None, "the gateway returned no promotion link")
        return f"generated {link.promotion_link}"

    return _run_step("tracking id", action)


def run_diagnostics(client: AffiliateClient) -> list[Check]:
    """Run every probe in dependency order and collect the results.

    Later probes are skipped once an earlier one fails, because their failure
    would only repeat the same root cause in a less obvious way.
    """
    checks = [check_credentials(client)]
    if checks[0].ok:
        checks.append(check_search(client))
        checks.append(check_tracking_id(client))
    else:
        for name in ("product search", "tracking id"):
            checks.append(
                Check(name, SKIPPED, "skipped", "Fix the failure above first.")
            )
    return checks


def describe_config(client: AffiliateClient) -> list[str]:
    """Human-readable summary of what the client is about to use."""
    config = client.config
    return [
        f"gateway:     {config.gateway}",
        f"app_key:     {mask(config.app_key)}",
        f"app_secret:  {mask(config.app_secret)}",
        f"tracking_id: {client.tracking_id or '(not set)'}",
        f"sign_method: {config.sign_method}",
    ]


def format_report(client: AffiliateClient, checks: list[Check]) -> str:
    """Render the full doctor report."""
    lines = ["Configuration", *(f"  {line}" for line in describe_config(client)), "", "Checks"]
    lines.extend(check.format() for check in checks)
    lines.append("")
    if all(check.ok for check in checks):
        lines.append("All checks passed — the credentials are ready to use.")
    elif any(check.status == FAILED for check in checks):
        lines.append("Some checks failed; fix the items marked -> above.")
    else:
        lines.append("Core checks passed; the skipped ones are optional.")
    return "\n".join(lines)


def diagnostics_exit_code(checks: list[Check]) -> int:
    """``0`` when nothing failed — skipped probes are not failures."""
    return 1 if any(check.status == FAILED for check in checks) else 0
