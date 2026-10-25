"""Lambda entry point: one function, routed on the HTTP API routeKey.

Each operation lives in its own module, so splitting the function by privilege
level later (reader / creator / deleter) only changes the Terraform wiring.
"""

import json
import logging

from vpc_api.adapter import ApiError, error_response, path_id
from vpc_api.creator import create_vpc
from vpc_api.deleter import delete_vpc
from vpc_api.reader import get_vpc, list_vpcs

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ROUTES = {
    "POST /v1/vpcs": create_vpc,
    "GET /v1/vpcs": list_vpcs,
    "GET /v1/vpcs/{id}": get_vpc,
    "DELETE /v1/vpcs/{id}": delete_vpc,
}


def _resource_id(event: dict, result: dict, err: ApiError | None) -> str | None:
    if err is not None and err.resource_id:
        return err.resource_id
    location = (result.get("headers") or {}).get("Location")
    if location:
        return location.rsplit("/", 1)[-1]
    return path_id(event)


def handler(event: dict, context) -> dict:
    route = event.get("routeKey", "")
    request_id = context.aws_request_id
    err: ApiError | None = None
    try:
        operation = ROUTES.get(route)
        if operation is None:
            raise ApiError(404, "NOT_FOUND")
        result = operation(event, context)
    except ApiError as exc:
        err = exc
        result = error_response(err, request_id)
    except Exception:
        logger.exception("Unhandled error")
        err = ApiError(500, "INTERNAL_ERROR")
        result = error_response(err, request_id)

    # One JSON line per request; no body, token or email is ever logged.
    logger.info(
        json.dumps(
            {
                "route": route,
                "status_code": result["statusCode"],
                "id": _resource_id(event, result, err),
                "error_code": err.code if err else None,
                "aws_error_code": err.aws_error_code if err else None,
                "request_id": request_id,
            }
        )
    )
    return result
