"""Adapter between API Gateway HTTP API (payload format 2.0) and the operations.

Everything that depends on the event and response format lives here, so moving to
another front door (REST API, ALB) only means changing this module.
"""

import base64
import binascii
import json
from decimal import Decimal
from typing import Any

MESSAGES: dict[str, str] = {
    "INVALID_JSON": "Request body must be a JSON object.",
    "VALIDATION_ERROR": "Request validation failed.",
    "SUBNETS_DO_NOT_FIT": "The requested subnets do not fit in the VPC CIDR block.",
    "INVALID_ID": "The id must be a UUID.",
    "INVALID_NEXT_TOKEN": "The next_token is invalid.",
    "NOT_FOUND": "Resource not found.",
    "CIDR_OVERLAP": "The CIDR block overlaps an existing VPC created by this API.",
    "VPC_QUOTA_EXCEEDED": "The VPC quota for this region has been reached.",
    "DEPENDENCY_VIOLATION": (
        "The VPC has resources that were not created by this API; remove them and retry."
    ),
    "INTERNAL_ERROR": "Internal error. Use request_id to find details in the logs.",
}


class ApiError(Exception):
    """An error that is returned to the client in the standard error format."""

    def __init__(
        self,
        status: int,
        code: str,
        details: list[dict] | None = None,
        resource_id: str | None = None,
        *,
        aws_error_code: str | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = MESSAGES[code]
        self.details: list[dict] = list(details) if details else []
        # Set only when the error happened after EC2 provisioning started, so the
        # client can read the FAILED record and find the resources by RequestId tag.
        self.resource_id = resource_id
        # Logged only; the raw AWS error never reaches the client.
        self.aws_error_code = aws_error_code
        super().__init__(f"{code}: {self.message}")


def parse_json_body(event: dict) -> object:
    """Return the decoded JSON body; any decoding problem is INVALID_JSON."""
    body = event.get("body")
    if body is None:
        raise ApiError(400, "INVALID_JSON")
    try:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode("utf-8")
        return json.loads(body)
    except (binascii.Error, ValueError):
        # json.JSONDecodeError and UnicodeDecodeError are both ValueError subclasses.
        raise ApiError(400, "INVALID_JSON") from None


def path_id(event: dict) -> str | None:
    return (event.get("pathParameters") or {}).get("id")


def query_params(event: dict) -> dict[str, str]:
    return event.get("queryStringParameters") or {}


def caller_sub(event: dict) -> str:
    """Cognito user id (sub) from the JWT verified by API Gateway; never the email."""
    return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]


def _json_default(value: Any) -> Any:
    # DynamoDB returns every number as Decimal; the only numbers we store are integers.
    if isinstance(value, Decimal):
        return int(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=_json_default)


def response(status: int, body: Any, headers: dict[str, str] | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json_dumps(body),
        "isBase64Encoded": False,
    }


def error_response(err: ApiError, request_id: str) -> dict:
    error: dict[str, Any] = {
        "code": err.code,
        "message": err.message,
        "request_id": request_id,
        "details": err.details,
    }
    if err.resource_id is not None:
        error["id"] = err.resource_id
    return response(err.status, {"error": error})
