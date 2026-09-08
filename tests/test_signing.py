from datetime import datetime, timezone

import pytest

from aliexpress_affiliate.errors import ConfigurationError
from aliexpress_affiliate.signing import (
    build_sign_source,
    normalize_params,
    normalize_value,
    sign,
    timestamp_datetime,
    timestamp_ms,
)


def test_params_are_sorted_and_concatenated_without_separators():
    source = build_sign_source(normalize_params({"b": "2", "a": "1", "c": "3"}))
    assert source == "a1b2c3"


def test_api_path_is_prepended_for_path_style_gateways():
    source = build_sign_source(normalize_params({"b": "2", "a": "1"}), "/router/rest")
    assert source == "/router/resta1b2"


def test_empty_values_and_sign_itself_are_excluded():
    normalized = normalize_params({"a": "1", "b": None, "c": "", "sign": "OLD"})
    assert normalized == {"a": "1"}


def test_values_are_rendered_the_way_they_go_on_the_wire():
    assert normalize_value(True) == "true"
    assert normalize_value(False) == "false"
    assert normalize_value(12) == "12"
    assert normalize_value({"b": 1, "a": 2}) == '{"b":1,"a":2}'
    assert normalize_value(["x", "y"]) == '["x","y"]'


def test_sha256_signature_is_hmac_over_the_sorted_source():
    import hashlib
    import hmac

    params = {"app_key": "123456", "method": "aliexpress.affiliate.category.get"}
    expected = hmac.new(
        b"top-secret",
        build_sign_source(normalize_params(params)).encode(),
        hashlib.sha256,
    ).hexdigest().upper()
    assert sign(params, "top-secret") == expected


def test_md5_signature_wraps_the_source_in_the_secret():
    import hashlib

    params = {"app_key": "123456"}
    source = build_sign_source(normalize_params(params))
    expected = hashlib.md5(f"top-secret{source}top-secret".encode()).hexdigest().upper()
    assert sign(params, "top-secret", sign_method="md5") == expected


def test_signature_is_uppercase_hex():
    signature = sign({"a": "1"}, "top-secret")
    assert signature == signature.upper()
    assert len(signature) == 64


def test_signature_ignores_a_previously_computed_sign_field():
    params = {"a": "1", "b": "2"}
    assert sign(params, "s") == sign({**params, "sign": "STALE"}, "s")


def test_unknown_sign_method_and_missing_secret_are_configuration_errors():
    with pytest.raises(ConfigurationError):
        sign({"a": "1"}, "secret", sign_method="sha1")
    with pytest.raises(ConfigurationError):
        sign({"a": "1"}, "")


def test_timestamps_use_milliseconds_and_beijing_time():
    moment = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert timestamp_ms(moment) == "1704067200000"
    # GMT+8, so midnight UTC is 08:00 the same day.
    assert timestamp_datetime(moment) == "2024-01-01 08:00:00"
