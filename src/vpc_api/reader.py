"""GET /v1/vpcs and GET /v1/vpcs/{id}: read from the table only, no EC2 calls.

Authorization is open to every authenticated user, so there is no filter on
created_by: everyone sees every record.
"""

from vpc_api import store
from vpc_api.adapter import ApiError, path_id, query_params, response
from vpc_api.validation import encode_next_token, validate_id, validate_list_params


def get_vpc(event: dict, context) -> dict:
    vpc_request_id = validate_id(path_id(event))
    item = store.get_item(vpc_request_id)
    if item is None:
        raise ApiError(404, "NOT_FOUND")
    return response(200, store.to_api(item))


def list_vpcs(event: dict, context) -> dict:
    limit, status, start_key = validate_list_params(query_params(event))
    items, last_key = store.list_page(limit, status, start_key)
    return response(
        200,
        {
            "items": [store.to_api(item) for item in items],
            "next_token": encode_next_token(last_key) if last_key else None,
        },
    )
