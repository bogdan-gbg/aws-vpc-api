"""End-to-end test against the deployed stack (pytest -m e2e).

Checks both the API answers and what really exists in AWS: a private VPC with the
expected tags, DNS hostnames, subnets spread over AZs and no Internet Gateway.
"""

import base64
import json
import time
import uuid

import pytest
import requests

pytestmark = pytest.mark.e2e

TIMEOUT_SECONDS = 30
E2E_BODY = {"name": "e2e-test", "cidr_block": "10.250.0.0/16", "subnet_count": 3}
EXPECTED_SUBNET_CIDRS = ["10.250.0.0/24", "10.250.1.0/24", "10.250.2.0/24"]


def _headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _jwt_sub(token: str) -> str:
    """Read the sub claim without verifying the signature (API Gateway did that)."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


def _tags(resource: dict) -> dict[str, str]:
    return {tag["Key"]: tag["Value"] for tag in resource.get("Tags", [])}


def _listed_ids(api_url: str, token: str) -> set[str]:
    ids: set[str] = set()
    params: dict[str, str] = {"limit": "100"}
    while True:
        result = requests.get(api_url, headers=_headers(token), params=params, timeout=TIMEOUT_SECONDS)
        assert result.status_code == 200, result.text
        page = result.json()
        ids.update(item["id"] for item in page["items"])
        if not page["next_token"]:
            return ids
        params["next_token"] = page["next_token"]


def _wait_until(condition, timeout: float, interval: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if condition():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def test_requests_without_token_are_rejected(api_url):
    assert requests.get(api_url, timeout=TIMEOUT_SECONDS).status_code == 401
    assert requests.post(api_url, json=E2E_BODY, timeout=TIMEOUT_SECONDS).status_code == 401


def test_invalid_input_is_rejected(api_url, owner_token):
    body = {"name": "e2e-invalid", "cidr_block": "8.8.8.0/24", "subnet_count": 2}
    result = requests.post(api_url, headers=_headers(owner_token), json=body, timeout=TIMEOUT_SECONDS)
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_id_is_not_found(api_url, owner_token):
    result = requests.get(
        f"{api_url}/{uuid.uuid4()}", headers=_headers(owner_token), timeout=TIMEOUT_SECONDS
    )
    assert result.status_code == 404
    assert result.json()["error"]["code"] == "NOT_FOUND"


def test_create_read_overlap_delete(api_url, owner_token, reviewer_token, ec2, created_ids):
    # Create.
    result = requests.post(api_url, headers=_headers(owner_token), json=E2E_BODY, timeout=TIMEOUT_SECONDS)
    assert result.status_code == 201, result.text
    record = result.json()
    vpc_request_id = record["id"]
    created_ids.append(vpc_request_id)
    assert result.headers["Location"] == f"/v1/vpcs/{vpc_request_id}"
    assert record["status"] == "CREATED"
    vpc_id = record["vpc_id"]

    # Read by id: same record.
    result = requests.get(
        f"{api_url}/{vpc_request_id}", headers=_headers(owner_token), timeout=TIMEOUT_SECONDS
    )
    assert result.status_code == 200
    assert result.json() == record

    # Listed (the list is eventually consistent: retry for up to 10 s).
    assert _wait_until(
        lambda: vpc_request_id in _listed_ids(api_url, owner_token), timeout=10, interval=1
    )

    # Authorization is open: the reviewer sees the record created by demo-owner.
    result = requests.get(
        f"{api_url}/{vpc_request_id}", headers=_headers(reviewer_token), timeout=TIMEOUT_SECONDS
    )
    assert result.status_code == 200
    assert result.json()["created_by"] == _jwt_sub(owner_token)

    # In AWS: the VPC with its tags and DNS hostnames.
    vpc = ec2.describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0]
    vpc_tags = _tags(vpc)
    assert vpc_tags["Name"] == "e2e-test"
    assert vpc_tags["ManagedBy"] == "vpc-api"
    assert vpc_tags["RequestId"] == vpc_request_id
    assert vpc_tags["CreatedBy"] == _jwt_sub(owner_token)
    dns = ec2.describe_vpc_attribute(VpcId=vpc_id, Attribute="enableDnsHostnames")
    assert dns["EnableDnsHostnames"]["Value"] is True

    # In AWS: 3 private subnets in 3 different AZs.
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]
    assert sorted(subnet["CidrBlock"] for subnet in subnets) == EXPECTED_SUBNET_CIDRS
    assert len({subnet["AvailabilityZone"] for subnet in subnets}) == 3
    for subnet in subnets:
        assert subnet["MapPublicIpOnLaunch"] is False
        assert _tags(subnet)["Tier"] == "private"

    # In AWS: no Internet Gateway attached.
    gateways = ec2.describe_internet_gateways(
        Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
    )["InternetGateways"]
    assert gateways == []

    # Overlapping CIDR is rejected and points to the existing request.
    overlap = {"name": "e2e-overlap", "cidr_block": "10.250.128.0/17", "subnet_count": 2}
    result = requests.post(api_url, headers=_headers(owner_token), json=overlap, timeout=TIMEOUT_SECONDS)
    if result.status_code == 201:
        created_ids.append(result.json()["id"])
    assert result.status_code == 409
    error = result.json()["error"]
    assert error["code"] == "CIDR_OVERLAP"
    assert error["details"][0]["conflicting_id"] == vpc_request_id

    # Delete: soft delete, resources gone from AWS.
    result = requests.delete(
        f"{api_url}/{vpc_request_id}", headers=_headers(owner_token), timeout=TIMEOUT_SECONDS
    )
    assert result.status_code == 200, result.text
    deleted = result.json()
    assert deleted["status"] == "DELETED"
    assert deleted["deleted_at"]

    def gone() -> bool:
        vpcs = ec2.describe_vpcs(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Vpcs"]
        remaining = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]
        return not vpcs and not remaining

    assert _wait_until(gone, timeout=30, interval=2)

    # Second DELETE is idempotent.
    result = requests.delete(
        f"{api_url}/{vpc_request_id}", headers=_headers(owner_token), timeout=TIMEOUT_SECONDS
    )
    assert result.status_code == 200
    assert result.json()["status"] == "DELETED"
