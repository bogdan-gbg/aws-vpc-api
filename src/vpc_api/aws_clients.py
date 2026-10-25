"""AWS clients, created once per Lambda execution environment."""

import os

import boto3
from botocore.config import Config

# Without an explicit Config, boto3 uses the "legacy" retry mode (up to 5 attempts).
# "standard" with 3 attempts retries throttling, 5xx and network errors with
# exponential backoff. Caveat: a retry after a read timeout can duplicate
# CreateVpc / CreateSubnet; duplicates carry the same RequestId tag and are removed
# by scripts/cleanup.py.
# Timeouts are per attempt and keep a stuck call shorter than the Lambda timeout,
# so there is still time left to store the FAILED record.
AWS_CONFIG = Config(
    retries={"mode": "standard", "total_max_attempts": 3},
    connect_timeout=2,
    read_timeout=5,
)

# The region comes from AWS_REGION, set by the Lambda runtime: VPCs are created in
# the region where the function runs.
EC2 = boto3.client("ec2", config=AWS_CONFIG)
TABLE = boto3.resource("dynamodb", config=AWS_CONFIG).Table(os.environ["TABLE_NAME"])
