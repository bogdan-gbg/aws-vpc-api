"""Unit test setup: no AWS account and no network needed.

The environment is set before the Lambda modules are imported; creating boto3
clients makes no network call.
"""

import os

os.environ["AWS_DEFAULT_REGION"] = "eu-central-1"
os.environ["AWS_REGION"] = "eu-central-1"
os.environ["TABLE_NAME"] = "test-table"

import pytest  # noqa: E402


class FakeContext:
    """The subset of the Lambda context used by the code."""

    aws_request_id = "test-request-id"
    invoked_function_arn = "arn:aws:lambda:eu-central-1:account-id:function:vpc-api-api"

    def get_remaining_time_in_millis(self) -> int:
        return 25_000


@pytest.fixture
def context() -> FakeContext:
    return FakeContext()


@pytest.fixture
def make_event():
    def _make_event(route_key: str, body: str | None = None, **extra) -> dict:
        event = {
            "version": "2.0",
            "routeKey": route_key,
            "isBase64Encoded": False,
            "requestContext": {
                "authorizer": {"jwt": {"claims": {"sub": "11111111-2222-3333-4444-555555555555"}}}
            },
        }
        if body is not None:
            event["body"] = body
        event.update(extra)
        return event

    return _make_event
