import json
from decimal import Decimal

from vpc_api.adapter import ApiError, error_response, json_dumps, response
from vpc_api.store import API_FIELDS, to_api


def test_decimal_is_serialized_as_int():
    assert json.loads(json_dumps({"subnet_count": Decimal("3")})) == {"subnet_count": 3}


def test_response_format():
    result = response(201, {"id": "x"}, headers={"Location": "/v1/vpcs/x"})
    assert result["statusCode"] == 201
    assert result["headers"] == {"Content-Type": "application/json", "Location": "/v1/vpcs/x"}
    assert json.loads(result["body"]) == {"id": "x"}


def test_to_api_fills_missing_attributes_with_null_in_fixed_order():
    item = {
        "status": "FAILED",
        "id": "abc",
        "subnet_count": Decimal("2"),
        "error": {
            "leftover_resources": ["vpc-1"],
            "code": "INTERNAL_ERROR",
            "aws_error_code": "InvalidVpcID.NotFound",
            "message": "Internal error. Use request_id to find details in the logs.",
        },
    }
    record = to_api(item)
    assert tuple(record) == API_FIELDS
    assert record["vpc_id"] is None
    assert record["subnets"] is None
    assert record["deleted_at"] is None
    assert list(record["error"]) == ["code", "message", "aws_error_code", "leftover_resources"]
    assert json.loads(json_dumps(record))["subnet_count"] == 2


def test_to_api_keeps_subnet_key_order():
    item = {
        "id": "abc",
        "subnets": [
            {
                "availability_zone_id": "euc1-az2",
                "subnet_id": "subnet-1",
                "availability_zone": "eu-central-1a",
                "cidr_block": "10.0.0.0/24",
            }
        ],
    }
    assert list(to_api(item)["subnets"][0]) == [
        "subnet_id",
        "cidr_block",
        "availability_zone",
        "availability_zone_id",
    ]


def test_error_format_without_id():
    result = error_response(ApiError(400, "INVALID_ID"), "req-1")
    assert result["statusCode"] == 400
    assert json.loads(result["body"]) == {
        "error": {
            "code": "INVALID_ID",
            "message": "The id must be a UUID.",
            "request_id": "req-1",
            "details": [],
        }
    }


def test_error_format_with_id():
    err = ApiError(409, "VPC_QUOTA_EXCEEDED", resource_id="abc", aws_error_code="VpcLimitExceeded")
    body = json.loads(error_response(err, "req-1")["body"])
    assert body["error"]["id"] == "abc"
    assert body["error"]["details"] == []
    # The AWS error code is for the logs only.
    assert "aws_error_code" not in body["error"]
