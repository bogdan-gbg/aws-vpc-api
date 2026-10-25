"""End-to-end fixtures: real API, real Cognito users, real EC2 checks.

Run manually after `terraform apply`, with the operator's AWS credentials:

    pytest -m e2e
"""

import pytest
import boto3
import requests

from get_token import get_access_token
from tf_outputs import load_outputs

TIMEOUT_SECONDS = 30


@pytest.fixture(scope="session")
def outputs() -> dict:
    return load_outputs()


@pytest.fixture(scope="session")
def api_url(outputs) -> str:
    return f"{outputs['api_url']}/v1/vpcs"


@pytest.fixture(scope="session")
def owner_token() -> str:
    return get_access_token("demo-owner")


@pytest.fixture(scope="session")
def reviewer_token() -> str:
    return get_access_token("reviewer")


@pytest.fixture(scope="session")
def ec2(outputs):
    # The operator's credentials (AWS_PROFILE), not the Lambda role.
    region = str(outputs["user_pool_id"]).split("_", 1)[0]
    return boto3.client("ec2", region_name=region)


@pytest.fixture(scope="session")
def created_ids(api_url, owner_token):
    """Ids created by the tests; deleted through the API at the end, even on failure."""
    ids: list[str] = []
    yield ids
    for vpc_request_id in ids:
        try:
            requests.delete(
                f"{api_url}/{vpc_request_id}",
                headers={"Authorization": f"Bearer {owner_token}"},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            print(f"Cleanup of {vpc_request_id} failed: {exc}; use scripts/cleanup.py")
