from collections import Counter

from vpc_api.topology import (
    allocate_subnet_cidrs,
    assign_zones,
    sort_zones,
    subnet_tags,
    vpc_tags,
)

ZONES = [
    {"ZoneName": "eu-central-1c", "ZoneId": "euc1-az1"},
    {"ZoneName": "eu-central-1a", "ZoneId": "euc1-az2"},
    {"ZoneName": "eu-central-1b", "ZoneId": "euc1-az3"},
]


def test_first_consecutive_blocks():
    assert allocate_subnet_cidrs("10.0.0.0/16", 24, 3) == [
        "10.0.0.0/24",
        "10.0.1.0/24",
        "10.0.2.0/24",
    ]


def test_zones_sorted_by_name():
    names = [zone["ZoneName"] for zone in sort_zones(ZONES)]
    assert names == ["eu-central-1a", "eu-central-1b", "eu-central-1c"]


def _spread(count: int) -> list[int]:
    placement = assign_zones(sort_zones(ZONES), count)
    counts = Counter(zone["ZoneName"] for zone in placement)
    return [counts[name] for name in ("eu-central-1a", "eu-central-1b", "eu-central-1c")]


def test_round_robin_with_two_subnets_uses_first_two_zones():
    assert _spread(2) == [1, 1, 0]


def test_round_robin_with_four_subnets():
    assert _spread(4) == [2, 1, 1]


def test_round_robin_with_five_subnets():
    assert _spread(5) == [2, 2, 1]


def test_vpc_tags():
    assert vpc_tags("team-a", "req-1", "sub-1") == [
        {"Key": "Name", "Value": "team-a"},
        {"Key": "ManagedBy", "Value": "vpc-api"},
        {"Key": "RequestId", "Value": "req-1"},
        {"Key": "CreatedBy", "Value": "sub-1"},
    ]


def test_subnet_tags():
    assert subnet_tags("team-a", 1, "eu-central-1a", "req-1", "sub-1") == [
        {"Key": "Name", "Value": "team-a-1-eu-central-1a"},
        {"Key": "ManagedBy", "Value": "vpc-api"},
        {"Key": "RequestId", "Value": "req-1"},
        {"Key": "CreatedBy", "Value": "sub-1"},
        {"Key": "Tier", "Value": "private"},
    ]
