"""DELETE /v1/vpcs/{id}: delete the EC2 resources, then mark the row DELETED.

The ids to delete come from the row (never from a tag search), and IAM only allows
deleting resources tagged ManagedBy=vpc-api: two independent safeguards against
touching a foreign VPC. The row is kept as history (soft delete).
"""

import logging

from botocore.exceptions import BotoCoreError, ClientError

from vpc_api import store
from vpc_api.adapter import ApiError, path_id, response
from vpc_api.aws_clients import EC2
from vpc_api.validation import validate_id

logger = logging.getLogger(__name__)

# Deletes are idempotent: an already deleted resource counts as success.
NOT_FOUND_CODES = frozenset({"InvalidSubnetID.NotFound", "InvalidVpcID.NotFound"})


def _resources_to_delete(item: dict) -> list[str]:
    """Subnets first, then the VPC."""
    if item["status"] == "CREATED":
        subnet_ids = [subnet["subnet_id"] for subnet in item.get("subnets") or []]
        return [*subnet_ids, item["vpc_id"]]
    leftovers = (item.get("error") or {}).get("leftover_resources") or []
    subnet_ids = [resource for resource in leftovers if resource.startswith("subnet-")]
    vpc_ids = [resource for resource in leftovers if resource.startswith("vpc-")]
    return [*subnet_ids, *vpc_ids]


def _delete_resource(resource_id: str) -> None:
    try:
        if resource_id.startswith("subnet-"):
            EC2.delete_subnet(SubnetId=resource_id)
        else:
            EC2.delete_vpc(VpcId=resource_id)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in NOT_FOUND_CODES:
            return
        logger.error("Could not delete %s (%s): %s", resource_id, code, exc)
        if code == "DependencyViolation":
            # Someone added resources to the VPC; they are never deleted by this API.
            raise ApiError(409, "DEPENDENCY_VIOLATION", aws_error_code=code) from exc
        raise ApiError(500, "INTERNAL_ERROR", aws_error_code=code) from exc
    except BotoCoreError as exc:
        logger.error("Could not delete %s: %s", resource_id, exc)
        raise ApiError(500, "INTERNAL_ERROR", aws_error_code=type(exc).__name__) from exc


def delete_vpc(event: dict, context) -> dict:
    vpc_request_id = validate_id(path_id(event))
    item = store.get_item(vpc_request_id)
    if item is None:
        raise ApiError(404, "NOT_FOUND")
    if item["status"] == "DELETED":
        return response(200, store.to_api(item))

    for resource_id in _resources_to_delete(item):
        _delete_resource(resource_id)

    updated = store.mark_deleted(vpc_request_id, store.utc_now())
    if updated is None:
        # A concurrent DELETE won the conditional update; return its result.
        updated = store.get_item(vpc_request_id)
        if updated is None:
            raise ApiError(404, "NOT_FOUND")
    return response(200, store.to_api(updated))
