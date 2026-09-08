import json

import pytest

from aliexpress_affiliate.client import ClientConfig, TopClient, unwrap_result
from aliexpress_affiliate.errors import (
    ApiError,
    BusinessError,
    ConfigurationError,
    RateLimitError,
    TransportError,
)
from aliexpress_affiliate.signing import build_sign_source, normalize_params, sign


def test_payload_carries_the_system_params_and_a_matching_signature(top_client):
    payload = top_client.build_payload("aliexpress.affiliate.category.get", {"foo": "bar"})

    assert payload["app_key"] == "123456"
    assert payload["method"] == "aliexpress.affiliate.category.get"
    assert payload["sign_method"] == "sha256"
    assert payload["format"] == "json"
    assert payload["foo"] == "bar"
    assert payload["timestamp"].isdigit()

    without_sign = {k: v for k, v in payload.items() if k != "sign"}
    assert payload["sign"] == sign(without_sign, "top-secret")


def test_signature_covers_every_business_param(top_client):
    payload = top_client.build_payload("m", {"keywords": "phone", "page_no": 2})
    source = build_sign_source(normalize_params({k: v for k, v in payload.items() if k != "sign"}))
    assert "keywordsphone" in source
    assert "page_no2" in source


def test_none_values_never_reach_the_wire(top_client):
    payload = top_client.build_payload("m", {"keywords": None, "page_no": 1})
    assert "keywords" not in payload


def test_successful_call_unwraps_the_method_envelope(top_client, transport):
    transport.queue({"aliexpress_affiliate_category_get_response": {"resp_result": {"resp_code": 200}}})
    body = top_client.call("aliexpress.affiliate.category.get")
    assert body == {"resp_result": {"resp_code": 200}}


def test_simplified_responses_without_the_envelope_pass_through(top_client, transport):
    transport.queue({"resp_result": {"resp_code": 200, "result": {"total_record_count": 1}}})
    assert unwrap_result(top_client.call("m")) == {"total_record_count": 1}


def test_error_response_becomes_an_api_error(top_client, transport):
    transport.queue(
        {
            "error_response": {
                "code": 25,
                "msg": "Invalid signature",
                "sub_code": "isv.sign-check-failure",
                "sub_msg": "signature does not match",
                "request_id": "abc123",
            }
        }
    )
    with pytest.raises(ApiError) as excinfo:
        top_client.call("m")
    error = excinfo.value
    assert error.code == "25"
    assert error.sub_code == "isv.sign-check-failure"
    assert error.request_id == "abc123"
    assert "isv.sign-check-failure" in str(error)


def test_throttling_is_retried_then_surfaces_as_rate_limit_error(top_client, transport):
    throttled = {"error_response": {"code": 7, "msg": "App Call Limited"}}
    for _ in range(3):
        transport.queue(throttled)
    with pytest.raises(RateLimitError):
        top_client.call("m")
    assert len(transport.requests) == 3  # initial call + max_retries


def test_a_retry_succeeds_after_a_transient_failure(top_client, transport):
    transport.queue({"error_response": {"code": 7, "msg": "App Call Limited"}})
    transport.queue({"resp_result": {"resp_code": 200, "result": {"ok": True}}})
    assert unwrap_result(top_client.call("m")) == {"ok": True}
    assert len(transport.requests) == 2


def test_each_retry_is_signed_afresh(top_client, transport):
    transport.queue({"error_response": {"code": 7, "msg": "App Call Limited"}})
    transport.queue({"resp_result": {"resp_code": 200}})
    top_client.call("m")
    first, second = transport.requests
    for payload in (first, second):
        without_sign = {k: v for k, v in payload.items() if k != "sign"}
        assert payload["sign"] == sign(without_sign, "top-secret")


def test_server_errors_are_retried_as_transport_errors(top_client, transport):
    for _ in range(3):
        transport.queue("gateway down", status=502)
    with pytest.raises(TransportError):
        top_client.call("m")
    assert len(transport.requests) == 3


def test_non_json_body_is_a_transport_error(top_client, transport):
    for _ in range(3):
        transport.queue("<html>blocked</html>")
    with pytest.raises(TransportError):
        top_client.call("m")


def test_business_failures_raise_business_error():
    with pytest.raises(BusinessError) as excinfo:
        unwrap_result({"resp_result": {"resp_code": 4001, "resp_msg": "tracking id not found"}})
    assert excinfo.value.code == 4001
    assert "tracking id not found" in str(excinfo.value)


def test_config_requires_credentials_and_known_options():
    with pytest.raises(ConfigurationError):
        ClientConfig(app_key="", app_secret="s")
    with pytest.raises(ConfigurationError):
        ClientConfig(app_key="k", app_secret="")
    with pytest.raises(ConfigurationError):
        ClientConfig(app_key="k", app_secret="s", sign_method="sha1")
    with pytest.raises(ConfigurationError):
        ClientConfig(app_key="k", app_secret="s", timestamp_style="unix")


def test_config_from_env_reads_aliexpress_variables():
    config = ClientConfig.from_env(
        {"ALIEXPRESS_APP_KEY": "k", "ALIEXPRESS_APP_SECRET": "s", "ALIEXPRESS_TIMEOUT": "5"}
    )
    assert (config.app_key, config.app_secret, config.timeout) == ("k", "s", 5.0)


def test_config_from_env_names_the_missing_variables():
    with pytest.raises(ConfigurationError) as excinfo:
        ClientConfig.from_env({})
    assert "ALIEXPRESS_APP_KEY" in str(excinfo.value)
    assert "ALIEXPRESS_APP_SECRET" in str(excinfo.value)


def test_legacy_gateway_style_signs_with_the_api_path_and_a_datetime(transport):
    config = ClientConfig(
        app_key="k",
        app_secret="s",
        gateway="https://gw.api.taobao.com/router/rest",
        timestamp_style="datetime",
        api_path="/router/rest",
    )
    payload = TopClient(config, transport).build_payload("m")
    assert " " in payload["timestamp"]  # yyyy-MM-dd HH:mm:ss
    without_sign = {k: v for k, v in payload.items() if k != "sign"}
    assert payload["sign"] == sign(without_sign, "s", api_path="/router/rest")


def test_caller_side_errors_are_not_retried_even_under_a_retryable_code(top_client, transport):
    # isv.permission-deny arrives as code 15, which is otherwise retryable.
    transport.queue(
        {"error_response": {"code": 15, "msg": "denied", "sub_code": "isv.permission-deny"}}
    )
    with pytest.raises(ApiError) as excinfo:
        top_client.call("m")
    assert not isinstance(excinfo.value, RateLimitError)
    assert len(transport.requests) == 1


def test_platform_side_sub_codes_are_still_retried(top_client, transport):
    transport.queue(
        {
            "error_response": {
                "code": 15,
                "msg": "upstream timeout",
                "sub_code": "isp.top-remote-connection-timeout",
            }
        }
    )
    transport.queue({"resp_result": {"resp_code": 200, "result": {"ok": True}}})
    assert unwrap_result(top_client.call("m")) == {"ok": True}
    assert len(transport.requests) == 2
