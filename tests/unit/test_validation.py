import base64
import json
import uuid

import pytest

from vpc_api.adapter import ApiError, parse_json_body
from vpc_api.validation import (
    decode_next_token,
    encode_next_token,
    validate_create_body,
    validate_id,
    validate_list_params,
)

VALID = {"name": "team-a", "cidr_block": "10.0.0.0/16", "subnet_count": 3}


def body(**overrides) -> dict:
    result = {**VALID, **overrides}
    return {key: value for key, value in result.items() if value is not ...}


def error_of(callable_, *args) -> ApiError:
    with pytest.raises(ApiError) as info:
        callable_(*args)
    return info.value


def fields(err: ApiError) -> list[str]:
    return [detail["field"] for detail in err.details]


# --- body -------------------------------------------------------------------


def test_minimal_valid_body_applies_default_subnet_prefix():
    assert validate_create_body(dict(VALID)) == {
        "name": "team-a",
        "cidr_block": "10.0.0.0/16",
        "subnet_count": 3,
        "subnet_prefix": 24,
    }


def test_explicit_subnet_prefix_is_kept():
    assert validate_create_body(body(subnet_prefix=20))["subnet_prefix"] == 20


@pytest.mark.parametrize("raw", ["{not json", "", "[1, 2"])
def test_invalid_json_is_rejected(raw):
    err = error_of(parse_json_body, {"body": raw})
    assert (err.status, err.code) == (400, "INVALID_JSON")


def test_missing_body_is_invalid_json():
    assert error_of(parse_json_body, {}).code == "INVALID_JSON"


@pytest.mark.parametrize("raw", ["[1, 2]", "null", '"text"', "42"])
def test_json_that_is_not_an_object_is_invalid_json(raw):
    err = error_of(validate_create_body, parse_json_body({"body": raw}))
    assert (err.status, err.code) == (400, "INVALID_JSON")


def test_base64_body_is_decoded():
    encoded = base64.b64encode(json.dumps(VALID).encode()).decode()
    assert parse_json_body({"body": encoded, "isBase64Encoded": True}) == VALID


def test_invalid_base64_body_is_invalid_json():
    err = error_of(parse_json_body, {"body": "not base64!", "isBase64Encoded": True})
    assert err.code == "INVALID_JSON"


@pytest.mark.parametrize("unknown", ["subnet_cout", "internet_access"])
def test_unknown_fields_are_rejected(unknown):
    err = error_of(validate_create_body, body(**{unknown: True}))
    assert (err.status, err.code) == (400, "VALIDATION_ERROR")
    assert {"field": unknown, "message": "Unknown field."} in err.details


@pytest.mark.parametrize("value", [True, "3", 3.0, 1, 7])
def test_invalid_subnet_count(value):
    err = error_of(validate_create_body, body(subnet_count=value))
    assert err.code == "VALIDATION_ERROR"
    assert fields(err) == ["subnet_count"]


@pytest.mark.parametrize("value", [16, 29, True])
def test_invalid_subnet_prefix(value):
    err = error_of(validate_create_body, body(subnet_prefix=value))
    assert err.code == "VALIDATION_ERROR"
    assert fields(err) == ["subnet_prefix"]


@pytest.mark.parametrize("value", ["", "a" * 65, "-team", "team a", 42])
def test_invalid_name(value):
    err = error_of(validate_create_body, body(name=value))
    assert err.code == "VALIDATION_ERROR"
    assert fields(err) == ["name"]


def test_name_with_64_characters_is_accepted():
    assert validate_create_body(body(name="a" * 64))["name"] == "a" * 64


@pytest.mark.parametrize(
    "value",
    [
        "10.0.0.1/16",  # host bits set: rejected, not corrected
        "10.0.0.0/15",
        "10.0.0.0/29",
        "8.8.8.0/24",
        "127.0.0.0/16",
        "169.254.0.0/16",
        "not-a-cidr",
        10,
    ],
)
def test_invalid_cidr_block(value):
    err = error_of(validate_create_body, body(cidr_block=value))
    assert err.code == "VALIDATION_ERROR"
    assert fields(err) == ["cidr_block"]


@pytest.mark.parametrize("value", ["172.16.0.0/16", "192.168.0.0/24"])
def test_private_cidr_blocks_are_accepted(value):
    result = validate_create_body(body(cidr_block=value, subnet_count=2, subnet_prefix=26))
    assert result["cidr_block"] == value


@pytest.mark.parametrize("missing", ["name", "cidr_block", "subnet_count"])
def test_required_fields(missing):
    err = error_of(validate_create_body, body(**{missing: ...}))
    assert fields(err) == [missing]


def test_all_errors_are_collected():
    err = error_of(
        validate_create_body,
        {"name": "", "cidr_block": "8.8.8.0/24", "subnet_count": "3", "extra": 1},
    )
    assert err.code == "VALIDATION_ERROR"
    assert sorted(fields(err)) == ["cidr_block", "extra", "name", "subnet_count"]


def test_default_prefix_does_not_fit_in_a_25():
    err = error_of(validate_create_body, body(cidr_block="10.0.0.0/25", subnet_count=2))
    assert (err.status, err.code) == (400, "SUBNETS_DO_NOT_FIT")


def test_too_many_subnets_do_not_fit():
    err = error_of(
        validate_create_body,
        body(cidr_block="10.0.0.0/24", subnet_prefix=26, subnet_count=5),
    )
    assert err.code == "SUBNETS_DO_NOT_FIT"


def test_exact_fit_is_accepted():
    result = validate_create_body(body(cidr_block="10.0.0.0/24", subnet_prefix=26, subnet_count=4))
    assert result["subnet_count"] == 4


# --- id ---------------------------------------------------------------------


def test_valid_id():
    value = str(uuid.uuid4())
    assert validate_id(value) == value


@pytest.mark.parametrize(
    "value",
    [None, "", "abc", str(uuid.uuid4()).upper(), uuid.uuid4().hex, "{" + str(uuid.uuid4()) + "}"],
)
def test_invalid_id(value):
    err = error_of(validate_id, value)
    assert (err.status, err.code) == (400, "INVALID_ID")


# --- list parameters --------------------------------------------------------


def test_list_defaults():
    assert validate_list_params({}) == (20, None, None)


def test_list_valid_values_and_unknown_parameters_ignored():
    assert validate_list_params({"limit": "100", "status": "FAILED", "foo": "bar"}) == (
        100,
        "FAILED",
        None,
    )


@pytest.mark.parametrize("value", ["0", "101", "abc", "-1", "1.5", ""])
def test_invalid_limit(value):
    err = error_of(validate_list_params, {"limit": value})
    assert err.code == "VALIDATION_ERROR"
    assert fields(err) == ["limit"]


def test_invalid_status():
    err = error_of(validate_list_params, {"status": "PENDING"})
    assert fields(err) == ["status"]


def test_limit_and_status_errors_are_collected():
    err = error_of(validate_list_params, {"limit": "0", "status": "created"})
    assert fields(err) == ["limit", "status"]


# --- next_token -------------------------------------------------------------


def _token(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def test_next_token_roundtrip():
    key = {"id": str(uuid.uuid4())}
    token = encode_next_token(key)
    assert "=" not in token
    assert decode_next_token(token) == key
    assert validate_list_params({"next_token": token}) == (20, None, key)


@pytest.mark.parametrize(
    "token",
    [
        "X" + encode_next_token({"id": str(uuid.uuid4())})[1:],  # tampered
        _token(json.dumps({"id": str(uuid.uuid4()), "extra": 1}).encode()),
        _token(json.dumps({"id": "not-a-uuid"}).encode()),
        _token(json.dumps([str(uuid.uuid4())]).encode()),
        "%%%not-base64%%%",
        "",
    ],
)
def test_invalid_next_token(token):
    err = error_of(validate_list_params, {"next_token": token})
    assert (err.status, err.code) == (400, "INVALID_NEXT_TOKEN")
