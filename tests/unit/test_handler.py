import json

import pytest
from botocore.stub import Stubber

from vpc_api import aws_clients
from vpc_api.handler import handler


@pytest.fixture
def no_aws_calls():
    """Any EC2 or DynamoDB call fails, because no response is queued."""
    with Stubber(aws_clients.EC2) as ec2, Stubber(aws_clients.TABLE.meta.client) as dynamodb:
        yield
        ec2.assert_no_pending_responses()
        dynamodb.assert_no_pending_responses()


def _error(result: dict) -> dict:
    return json.loads(result["body"])["error"]


def test_unknown_route_is_not_found(make_event, context, no_aws_calls):
    result = handler(make_event("PATCH /v1/vpcs"), context)
    assert result["statusCode"] == 404
    error = _error(result)
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"] == context.aws_request_id


def test_post_with_invalid_body_returns_400_without_aws_calls(make_event, context, no_aws_calls):
    body = json.dumps({"name": "team-a", "cidr_block": "8.8.8.0/24", "subnet_count": 3})
    result = handler(make_event("POST /v1/vpcs", body=body), context)
    assert result["statusCode"] == 400
    error = _error(result)
    assert error["code"] == "VALIDATION_ERROR"
    assert "id" not in error


def test_post_with_malformed_json_returns_400(make_event, context, no_aws_calls):
    result = handler(make_event("POST /v1/vpcs", body="{"), context)
    assert result["statusCode"] == 400
    assert _error(result)["code"] == "INVALID_JSON"


def test_get_with_invalid_id_returns_400_without_aws_calls(make_event, context, no_aws_calls):
    event = make_event("GET /v1/vpcs/{id}", pathParameters={"id": "not-a-uuid"})
    result = handler(event, context)
    assert result["statusCode"] == 400
    assert _error(result)["code"] == "INVALID_ID"
