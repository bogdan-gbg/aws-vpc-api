"""POST /v1/vpcs: synchronous creation, one DynamoDB write with the confirmed result.

Order: validate -> overlap check -> EC2 provisioning -> PutItem CREATED or FAILED.
There is no PENDING state and no rollback: anything created before an error stays
in the account, is listed in error.leftover_resources and is removed with DELETE.
Resources without a row (PutItem failure, Lambda timeout) are found by their
ManagedBy / RequestId tags and removed by scripts/cleanup.py.
"""

import logging
import os
import uuid

from botocore.exceptions import BotoCoreError, ClientError

from vpc_api import store
from vpc_api.adapter import MESSAGES, ApiError, caller_sub, parse_json_body, response
from vpc_api.aws_clients import EC2
from vpc_api.topology import (
    allocate_subnet_cidrs,
    assign_zones,
    sort_zones,
    subnet_tags,
    vpc_tags,
)
from vpc_api.validation import validate_create_body

logger = logging.getLogger(__name__)

# Stop before an EC2 call when less time is left: the rest of the budget is kept for
# storing the FAILED record instead of letting the Lambda time out without a row.
TIME_RESERVE_MS = 3000


class ProvisioningAborted(Exception):
    """Provisioning stopped by our own checks (time reserve, no availability zone)."""


def _check_time(context) -> None:
    if context.get_remaining_time_in_millis() < TIME_RESERVE_MS:
        raise ProvisioningAborted("Time reserve exhausted before the next EC2 call.")


def _aws_error_code(exc: Exception) -> str | None:
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code")
    if isinstance(exc, BotoCoreError):
        return type(exc).__name__
    return None


def _provision(
    spec: dict, request_id: str, created_by: str, context, created: list[str]
) -> tuple[str, list[dict]]:
    """Create the VPC and its subnets; every created id is appended to `created`.

    No waiters and no retry on *.NotFound: EC2 is eventually consistent, and such an
    error ends as a FAILED row with the VPC in leftover_resources.
    """
    _check_time(context)
    zones = sort_zones(
        EC2.describe_availability_zones(
            Filters=[
                {"Name": "state", "Values": ["available"]},
                # Excludes Local Zones and Wavelength Zones.
                {"Name": "zone-type", "Values": ["availability-zone"]},
            ]
        )["AvailabilityZones"]
    )
    if not zones:
        raise ProvisioningAborted("No available availability zone in the region.")

    _check_time(context)
    vpc = EC2.create_vpc(
        CidrBlock=spec["cidr_block"],
        TagSpecifications=[
            {"ResourceType": "vpc", "Tags": vpc_tags(spec["name"], request_id, created_by)}
        ],
    )["Vpc"]
    vpc_id = vpc["VpcId"]
    created.append(vpc_id)

    _check_time(context)
    EC2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})

    cidrs = allocate_subnet_cidrs(spec["cidr_block"], spec["subnet_prefix"], spec["subnet_count"])
    placement = assign_zones(zones, spec["subnet_count"])
    subnets: list[dict] = []
    for index, (cidr, zone) in enumerate(zip(cidrs, placement, strict=True), start=1):
        _check_time(context)
        subnet = EC2.create_subnet(
            VpcId=vpc_id,
            CidrBlock=cidr,
            AvailabilityZone=zone["ZoneName"],
            TagSpecifications=[
                {
                    "ResourceType": "subnet",
                    "Tags": subnet_tags(
                        spec["name"], index, zone["ZoneName"], request_id, created_by
                    ),
                }
            ],
        )["Subnet"]
        created.append(subnet["SubnetId"])
        subnets.append(
            {
                "subnet_id": subnet["SubnetId"],
                "cidr_block": subnet["CidrBlock"],
                "availability_zone": subnet["AvailabilityZone"],
                "availability_zone_id": subnet["AvailabilityZoneId"],
            }
        )
    return vpc_id, subnets


def _fail(base: dict, exc: Exception, created: list[str]) -> ApiError:
    """Store the FAILED row (best effort) and build the error for the client."""
    aws_error_code = _aws_error_code(exc)
    if aws_error_code == "VpcLimitExceeded":
        status, code = 409, "VPC_QUOTA_EXCEEDED"
    else:
        status, code = 500, "INTERNAL_ERROR"
    # The raw AWS message may contain account details or encoded authorization
    # messages: it goes to the logs only, never to the client or the table.
    logger.error(
        "EC2 provisioning failed for %s (%s): %s", base["id"], aws_error_code, exc
    )

    item = {
        **base,
        "status": "FAILED",
        "created_at": store.utc_now(),
        "error": {
            "code": code,
            "message": MESSAGES[code],
            "aws_error_code": aws_error_code,
            "leftover_resources": list(created),
        },
    }
    try:
        store.put_result(item)
    except Exception:
        logger.exception("Could not store the FAILED record for %s", base["id"])
    return ApiError(status, code, resource_id=base["id"], aws_error_code=aws_error_code)


def create_vpc(event: dict, context) -> dict:
    spec = validate_create_body(parse_json_body(event))

    conflicts = store.find_overlapping(spec["cidr_block"])
    if conflicts:
        raise ApiError(
            409,
            "CIDR_OVERLAP",
            details=[
                {
                    "field": "cidr_block",
                    "message": f"Overlaps {conflict['cidr_block']} of VPC request {conflict['id']}.",
                    "conflicting_id": conflict["id"],
                }
                for conflict in conflicts
            ],
        )

    request_id = str(uuid.uuid4())
    base = {
        "id": request_id,
        **spec,
        "region": os.environ["AWS_REGION"],
        # Account from the function ARN: no STS call needed.
        "account_id": context.invoked_function_arn.split(":")[4],
        "created_by": caller_sub(event),
    }

    created: list[str] = []
    try:
        vpc_id, subnets = _provision(spec, request_id, base["created_by"], context, created)
    except (ClientError, BotoCoreError, ProvisioningAborted) as exc:
        raise _fail(base, exc, created) from exc

    item = {
        **base,
        "status": "CREATED",
        "vpc_id": vpc_id,
        "subnets": subnets,
        "created_at": store.utc_now(),
    }
    try:
        store.put_result(item)
    except Exception as exc:
        # Nothing is written: the resources stay, unregistered, and are removed by
        # tag (RequestId = the id returned in the error).
        logger.exception("Could not store the CREATED record for %s", request_id)
        raise ApiError(
            500, "INTERNAL_ERROR", resource_id=request_id, aws_error_code=_aws_error_code(exc)
        ) from exc

    return response(201, store.to_api(item), headers={"Location": f"/v1/vpcs/{request_id}"})
