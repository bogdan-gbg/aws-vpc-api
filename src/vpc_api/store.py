"""DynamoDB operations and the API representation of a record.

One row per request with a confirmed result (CREATED or FAILED), written once;
DELETE turns it into DELETED (soft delete). Every attribute in an expression uses a
placeholder, because names such as "status" and "name" are reserved words.
"""

from datetime import datetime, timezone
from ipaddress import IPv4Network

from botocore.exceptions import ClientError

from vpc_api.aws_clients import TABLE

API_FIELDS = (
    "id",
    "status",
    "name",
    "cidr_block",
    "subnet_count",
    "subnet_prefix",
    "vpc_id",
    "subnets",
    "error",
    "region",
    "account_id",
    "created_by",
    "created_at",
    "deleted_at",
)
SUBNET_FIELDS = ("subnet_id", "cidr_block", "availability_zone", "availability_zone_id")
ERROR_FIELDS = ("code", "message", "aws_error_code", "leftover_resources")


def utc_now() -> str:
    """ISO 8601 UTC with a Z suffix (datetime.utcnow() is deprecated and naive)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_conditional_check_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def find_overlapping(cidr_block: str) -> list[dict]:
    """CREATED records whose CIDR overlaps `cidr_block` (all pages, consistent read)."""
    requested = IPv4Network(cidr_block)
    kwargs: dict = {
        "ConsistentRead": True,
        "FilterExpression": "#status = :created",
        "ProjectionExpression": "#id, #cidr_block",
        "ExpressionAttributeNames": {
            "#status": "status",
            "#id": "id",
            "#cidr_block": "cidr_block",
        },
        "ExpressionAttributeValues": {":created": "CREATED"},
    }
    conflicts: list[dict] = []
    while True:
        page = TABLE.scan(**kwargs)
        for item in page.get("Items", []):
            if requested.overlaps(IPv4Network(item["cidr_block"])):
                conflicts.append({"id": item["id"], "cidr_block": item["cidr_block"]})
        last_key = page.get("LastEvaluatedKey")
        if not last_key:
            return conflicts
        kwargs["ExclusiveStartKey"] = last_key


def put_result(item: dict) -> None:
    """Write the single CREATED / FAILED row for a request."""
    try:
        TABLE.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(#id)",
            ExpressionAttributeNames={"#id": "id"},
        )
    except ClientError as exc:
        # The id is a fresh UUID, so only this request could have written the row:
        # the failed condition means a boto3 retry after a lost response, i.e. success.
        if _is_conditional_check_failure(exc):
            return
        raise


def get_item(vpc_request_id: str) -> dict | None:
    result = TABLE.get_item(Key={"id": vpc_request_id}, ConsistentRead=True)
    return result.get("Item")


def list_page(
    limit: int, status: str | None, start_key: dict | None
) -> tuple[list[dict], dict | None]:
    """One Scan page, eventually consistent, order not guaranteed.

    Limit applies before the filter, so a page can be short or even empty while a
    next_token is still returned.
    """
    kwargs: dict = {"Limit": limit}
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    if status:
        kwargs["FilterExpression"] = "#status = :status"
        kwargs["ExpressionAttributeNames"] = {"#status": "status"}
        kwargs["ExpressionAttributeValues"] = {":status": status}
    page = TABLE.scan(**kwargs)
    return page.get("Items", []), page.get("LastEvaluatedKey")


def mark_deleted(vpc_request_id: str, now: str) -> dict | None:
    """CREATED / FAILED -> DELETED; None if a concurrent DELETE already did it."""
    try:
        result = TABLE.update_item(
            Key={"id": vpc_request_id},
            UpdateExpression="SET #status = :deleted, #deleted_at = :now",
            ConditionExpression="#status IN (:created, :failed)",
            ExpressionAttributeNames={"#status": "status", "#deleted_at": "deleted_at"},
            ExpressionAttributeValues={
                ":deleted": "DELETED",
                ":now": now,
                ":created": "CREATED",
                ":failed": "FAILED",
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if _is_conditional_check_failure(exc):
            return None
        raise
    return result["Attributes"]


def to_api(item: dict) -> dict:
    """Fixed key order; attributes omitted in the table become null."""
    record = {field: item.get(field) for field in API_FIELDS}
    # DynamoDB maps do not keep key order, so nested objects are rebuilt as well.
    if record["subnets"] is not None:
        record["subnets"] = [
            {field: subnet.get(field) for field in SUBNET_FIELDS} for subnet in record["subnets"]
        ]
    if record["error"] is not None:
        record["error"] = {field: record["error"].get(field) for field in ERROR_FIELDS}
    return record
