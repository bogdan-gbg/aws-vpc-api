"""Input validation: pure functions, standard library only, no AWS calls.

Validation runs before any EC2 call, so an invalid request creates nothing and is
never stored.
"""

import base64
import binascii
import ipaddress
import json
import re
import uuid

from vpc_api.adapter import ApiError

ALLOWED_FIELDS = ("name", "cidr_block", "subnet_count", "subnet_prefix")
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-_]*$")
NAME_MAX_LENGTH = 64
VPC_PREFIX_MIN, VPC_PREFIX_MAX = 16, 28
SUBNET_COUNT_MIN, SUBNET_COUNT_MAX = 2, 6
SUBNET_PREFIX_MIN, SUBNET_PREFIX_MAX = 17, 28
DEFAULT_SUBNET_PREFIX = 24
# Explicit RFC 1918 ranges: ipaddress.is_private would also accept loopback,
# link-local and documentation ranges.
RFC1918_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
STATUSES = ("CREATED", "FAILED", "DELETED")


def _detail(field: str, message: str) -> dict:
    return {"field": field, "message": message}


def _is_strict_int(value: object) -> bool:
    # bool is a subclass of int, so isinstance() would accept true as 1.
    return type(value) is int


def _check_name(body: dict, details: list[dict]) -> None:
    if "name" not in body:
        details.append(_detail("name", "This field is required."))
        return
    value = body["name"]
    if not isinstance(value, str):
        details.append(_detail("name", "Must be a string."))
    elif not 1 <= len(value) <= NAME_MAX_LENGTH:
        details.append(_detail("name", f"Must be 1-{NAME_MAX_LENGTH} characters long."))
    elif not NAME_PATTERN.fullmatch(value):
        details.append(
            _detail(
                "name",
                "Must start with a letter or digit and contain only letters, digits, '-' and '_'.",
            )
        )


def _check_cidr_block(body: dict, details: list[dict]) -> ipaddress.IPv4Network | None:
    if "cidr_block" not in body:
        details.append(_detail("cidr_block", "This field is required."))
        return None
    value = body["cidr_block"]
    if not isinstance(value, str):
        details.append(_detail("cidr_block", "Must be a string."))
        return None
    try:
        # strict=True: a CIDR with host bits set is rejected, not silently corrected.
        network = ipaddress.IPv4Network(value, strict=True)
    except ValueError:
        details.append(
            _detail("cidr_block", "Must be a valid IPv4 CIDR block with no host bits set.")
        )
        return None
    if not VPC_PREFIX_MIN <= network.prefixlen <= VPC_PREFIX_MAX:
        details.append(
            _detail(
                "cidr_block",
                f"Prefix length must be between /{VPC_PREFIX_MIN} and /{VPC_PREFIX_MAX}.",
            )
        )
        return None
    if not any(network.subnet_of(private) for private in RFC1918_NETWORKS):
        details.append(
            _detail(
                "cidr_block",
                "Must be inside a private RFC 1918 range "
                "(10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16).",
            )
        )
        return None
    return network


def _check_int(
    body: dict,
    field: str,
    minimum: int,
    maximum: int,
    details: list[dict],
    default: int | None = None,
) -> int | None:
    if field not in body:
        if default is not None:
            return default
        details.append(_detail(field, "This field is required."))
        return None
    value = body[field]
    if not _is_strict_int(value):
        details.append(_detail(field, "Must be an integer."))
        return None
    if not minimum <= value <= maximum:
        details.append(_detail(field, f"Must be between {minimum} and {maximum}."))
        return None
    return value


def validate_create_body(body: object) -> dict:
    """Validate the POST /v1/vpcs body and return the normalized input."""
    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_JSON")

    details: list[dict] = []
    # Unknown fields are rejected: a typo such as "subnet_cout" must not silently
    # fall back to a default value.
    for key in body:
        if key not in ALLOWED_FIELDS:
            details.append(_detail(str(key), "Unknown field."))

    _check_name(body, details)
    network = _check_cidr_block(body, details)
    subnet_count = _check_int(body, "subnet_count", SUBNET_COUNT_MIN, SUBNET_COUNT_MAX, details)
    subnet_prefix = _check_int(
        body,
        "subnet_prefix",
        SUBNET_PREFIX_MIN,
        SUBNET_PREFIX_MAX,
        details,
        default=DEFAULT_SUBNET_PREFIX,
    )

    if details:
        raise ApiError(400, "VALIDATION_ERROR", details=details)

    assert network is not None and subnet_count is not None and subnet_prefix is not None
    # Arithmetic check: listing every possible subnet would be needlessly expensive.
    if (
        subnet_prefix <= network.prefixlen
        or 2 ** (subnet_prefix - network.prefixlen) < subnet_count
    ):
        raise ApiError(400, "SUBNETS_DO_NOT_FIT")

    return {
        "name": body["name"],
        "cidr_block": str(network),
        "subnet_count": subnet_count,
        "subnet_prefix": subnet_prefix,
    }


def _is_canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def validate_id(value: object) -> str:
    """Accept only canonical UUIDs (lowercase, with hyphens); checked before DynamoDB."""
    if not _is_canonical_uuid(value):
        raise ApiError(400, "INVALID_ID")
    return value  # type: ignore[return-value]


def validate_list_params(query: dict) -> tuple[int, str | None, dict | None]:
    """Return (limit, status, exclusive_start_key); unknown parameters are ignored."""
    details: list[dict] = []

    limit = DEFAULT_LIMIT
    raw_limit = query.get("limit")
    if raw_limit is not None:
        # isascii() + length bound keep int() safe (no Unicode digits, no huge strings).
        if (
            raw_limit.isascii()
            and raw_limit.isdigit()
            and len(raw_limit) <= 3
            and 1 <= int(raw_limit) <= MAX_LIMIT
        ):
            limit = int(raw_limit)
        else:
            details.append(_detail("limit", f"Must be an integer between 1 and {MAX_LIMIT}."))

    status = query.get("status")
    if status is not None and status not in STATUSES:
        details.append(_detail("status", f"Must be one of {', '.join(STATUSES)}."))

    if details:
        raise ApiError(400, "VALIDATION_ERROR", details=details)

    raw_token = query.get("next_token")
    start_key = decode_next_token(raw_token) if raw_token is not None else None
    return limit, status, start_key


def encode_next_token(key: dict) -> str:
    payload = json.dumps({"id": key["id"]}).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_next_token(token: str) -> dict:
    """Decode and strictly check a next_token.

    The token comes from the client and becomes ExclusiveStartKey; anything that is
    not exactly {"id": "<uuid>"} is rejected here instead of failing in DynamoDB.
    """
    try:
        if not isinstance(token, str) or not token or not token.isascii():
            raise ValueError("token must be a non-empty ASCII string")
        padded = token + "=" * (-len(token) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        key = json.loads(raw)
    except (binascii.Error, ValueError):
        raise ApiError(400, "INVALID_NEXT_TOKEN") from None
    if not isinstance(key, dict) or set(key) != {"id"} or not _is_canonical_uuid(key["id"]):
        raise ApiError(400, "INVALID_NEXT_TOKEN")
    return {"id": key["id"]}
