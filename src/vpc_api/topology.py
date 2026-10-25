"""VPC topology: pure functions for subnet CIDRs, AZ placement and tags."""

import itertools
from ipaddress import IPv4Network

MANAGED_BY = "vpc-api"


def allocate_subnet_cidrs(cidr_block: str, subnet_prefix: int, count: int) -> list[str]:
    """First `count` consecutive blocks; the rest of the VPC range stays free."""
    blocks = IPv4Network(cidr_block).subnets(new_prefix=subnet_prefix)
    return [str(block) for block in itertools.islice(blocks, count)]


def sort_zones(zones: list[dict]) -> list[dict]:
    """Deterministic order: EC2 does not guarantee the order of DescribeAvailabilityZones."""
    return sorted(zones, key=lambda zone: zone["ZoneName"])


def assign_zones(zones: list[dict], count: int) -> list[dict]:
    """Round-robin; with 4-5 subnets on 3 AZs the spread is uneven (2/1/1, 2/2/1)."""
    return [zones[index % len(zones)] for index in range(count)]


def _tags(values: dict[str, str]) -> list[dict]:
    return [{"Key": key, "Value": value} for key, value in values.items()]


def vpc_tags(name: str, request_id: str, created_by: str) -> list[dict]:
    # Applied through TagSpecifications at creation time: the IAM policy requires
    # ManagedBy in the request and allows no tagging afterwards.
    return _tags(
        {
            "Name": name,
            "ManagedBy": MANAGED_BY,
            "RequestId": request_id,
            "CreatedBy": created_by,
        }
    )


def subnet_tags(
    name: str, index: int, zone_name: str, request_id: str, created_by: str
) -> list[dict]:
    """`index` is 1-based: {name}-1-eu-central-1a."""
    return _tags(
        {
            "Name": f"{name}-{index}-{zone_name}",
            "ManagedBy": MANAGED_BY,
            "RequestId": request_id,
            "CreatedBy": created_by,
            "Tier": "private",
        }
    )
