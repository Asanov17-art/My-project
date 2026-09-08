from aliexpress_affiliate.diagnostics import (
    FAILED,
    OK,
    SKIPPED,
    Check,
    check_credentials,
    check_tracking_id,
    diagnostics_exit_code,
    explain,
    format_report,
    mask,
    run_diagnostics,
)
from aliexpress_affiliate.affiliate import AffiliateClient
from aliexpress_affiliate.errors import ApiError

CATEGORIES = {
    "resp_result": {
        "resp_code": 200,
        "result": {"categories": {"category": [{"category_id": 3, "category_name": "Apparel"}]}},
    }
}
SEARCH = {
    "resp_result": {
        "resp_code": 200,
        "result": {
            "total_record_count": 12,
            "products": {"product": [{"product_id": "1", "product_title": "USB cable"}]},
        },
    }
}
LINK = {
    "resp_result": {
        "resp_code": 200,
        "result": {
            "promotion_links": {
                "promotion_link": [{"promotion_link": "https://s.click.aliexpress.com/e/_ok"}]
            }
        },
    }
}


def test_a_healthy_setup_passes_every_check(affiliate, transport):
    transport.queue(CATEGORIES).queue(SEARCH).queue(LINK)

    checks = run_diagnostics(affiliate)

    assert [check.status for check in checks] == [OK, OK, OK]
    assert diagnostics_exit_code(checks) == 0
    assert "1 categories returned" in checks[0].detail
    assert "USB cable" in checks[1].detail


def test_a_rejected_signature_is_explained_not_just_reported(affiliate, transport):
    transport.queue(
        {
            "error_response": {
                "code": 25,
                "msg": "Invalid signature",
                "sub_code": "isv.sign-check-failure",
            }
        }
    )
    check = check_credentials(affiliate)
    assert check.status == FAILED
    assert "ALIEXPRESS_APP_SECRET" in (check.hint or "")


def test_a_missing_api_package_points_at_the_subscription(affiliate, transport):
    transport.queue(
        {"error_response": {"code": 15, "msg": "denied", "sub_code": "isv.permission-deny"}}
    )
    check = check_credentials(affiliate)
    assert "Affiliate API package" in (check.hint or "")


def test_later_checks_are_skipped_once_credentials_fail(affiliate, transport):
    transport.queue({"error_response": {"code": 27, "msg": "Invalid session"}})
    checks = run_diagnostics(affiliate)
    assert [check.status for check in checks] == [FAILED, SKIPPED, SKIPPED]
    assert diagnostics_exit_code(checks) == 1
    # One failed call, and no wasted quota on the probes behind it.
    assert len(transport.requests) == 1


def test_a_missing_tracking_id_is_a_skip_not_a_failure(config, top_client, transport):
    client = AffiliateClient(config, client=top_client)
    transport.queue(CATEGORIES).queue(SEARCH)

    checks = run_diagnostics(client)

    assert [check.status for check in checks] == [OK, OK, SKIPPED]
    assert diagnostics_exit_code(checks) == 0


def test_an_unusable_tracking_id_fails_the_link_probe(affiliate, transport):
    transport.queue(CATEGORIES).queue(SEARCH)
    transport.queue(
        {
            "error_response": {
                "code": 43,
                "msg": "bad tracking id",
                "sub_code": "isv.tracking-id-not-exist",
            }
        }
    )
    checks = run_diagnostics(affiliate)
    assert checks[2].status == FAILED
    assert "affiliate console" in (checks[2].hint or "")


def test_an_empty_link_response_is_treated_as_a_failure(affiliate, transport):
    transport.queue(CATEGORIES).queue(SEARCH)
    transport.queue({"resp_result": {"resp_code": 200, "result": {}}})
    assert check_tracking_id(affiliate).status == FAILED


def test_unknown_errors_fall_back_to_the_gateway_message():
    error = ApiError("999", "Something new broke", sub_code="isv.brand-new-code")
    assert explain(error) == "Something new broke"


def test_secrets_are_masked_in_the_report(affiliate, transport):
    transport.queue(CATEGORIES).queue(SEARCH).queue(LINK)
    report = format_report(affiliate, run_diagnostics(affiliate))
    assert "top-secret" not in report
    assert mask("top-secret") in report


def test_a_failed_check_renders_its_hint_under_the_failure():
    rendered = Check("tracking id", FAILED, "boom", "do the thing").format()
    assert "[FAIL] tracking id: boom" in rendered
    assert "-> do the thing" in rendered
