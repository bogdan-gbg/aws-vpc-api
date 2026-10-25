"""Find and delete the VPCs and subnets created by the API, by tag.

Safety net for resources the API no longer sees (PutItem failure, Lambda timeout,
duplicates from a retry) and the step before terraform destroy, which does not know
about runtime resources. Runs with the operator's credentials, not the Lambda role.

    python scripts/cleanup.py                          # dry run: list only
    python scripts/cleanup.py --yes                    # delete everything tagged ManagedBy=vpc-api
    python scripts/cleanup.py --request-id <id> --yes  # only the resources of one request

Only EC2 is touched: the DynamoDB table is not updated. During a test cycle, use
DELETE through the API for records that exist, and this script with --request-id
for orphans. Run it without a filter only right before terraform destroy.
"""

import argparse
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

MANAGED_BY = "vpc-api"
NOT_FOUND_CODES = {"InvalidSubnetID.NotFound", "InvalidVpcID.NotFound"}


def _tags(resource: dict) -> dict[str, str]:
    return {tag["Key"]: tag["Value"] for tag in resource.get("Tags", [])}


def _describe(ec2, operation: str, key: str, filters: list[dict]) -> list[dict]:
    resources: list[dict] = []
    for page in ec2.get_paginator(operation).paginate(Filters=filters):
        resources.extend(page[key])
    return resources


def _print_resources(kind: str, resources: list[dict], id_key: str) -> None:
    print(f"{kind}: {len(resources)}")
    for resource in resources:
        tags = _tags(resource)
        print(
            f"  {resource[id_key]}  RequestId={tags.get('RequestId', '-')}  "
            f"Name={tags.get('Name', '-')}"
        )


def _delete(ec2, resource_id: str) -> bool:
    """Return True if the resource is gone (deleted now or already)."""
    try:
        if resource_id.startswith("subnet-"):
            ec2.delete_subnet(SubnetId=resource_id)
        else:
            ec2.delete_vpc(VpcId=resource_id)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in NOT_FOUND_CODES:
            print(f"  already deleted: {resource_id}")
            return True
        # DependencyViolation included: resources added by someone else are never
        # deleted here; report and continue with the next one.
        print(f"  NOT deleted: {resource_id} ({code})")
        return False
    except BotoCoreError as exc:
        print(f"  NOT deleted: {resource_id} ({type(exc).__name__})")
        return False
    print(f"  deleted: {resource_id}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete VPCs and subnets tagged ManagedBy=vpc-api.")
    parser.add_argument("--yes", action="store_true", help="delete (default: dry run, list only)")
    parser.add_argument("--request-id", help="only resources with this RequestId tag")
    parser.add_argument("--region", help="AWS region (default: the region of the AWS profile)")
    args = parser.parse_args(argv)

    # The region is not read from terraform output: this must also work after
    # terraform destroy or when the state is lost.
    session = boto3.session.Session(region_name=args.region)
    region = session.region_name
    if not region:
        print("No region: pass --region or set a region in the AWS profile.", file=sys.stderr)
        return 2

    # Shown first, so a wrong profile is obvious before anything is deleted.
    account = session.client("sts").get_caller_identity()["Account"]
    print(f"Account: {account}  Region: {region}")

    filters = [{"Name": "tag:ManagedBy", "Values": [MANAGED_BY]}]
    if args.request_id:
        filters.append({"Name": "tag:RequestId", "Values": [args.request_id]})

    ec2 = session.client("ec2")
    vpcs = _describe(ec2, "describe_vpcs", "Vpcs", filters)
    subnets = _describe(ec2, "describe_subnets", "Subnets", filters)
    _print_resources("VPCs", vpcs, "VpcId")
    _print_resources("Subnets", subnets, "SubnetId")

    if not args.yes:
        print("Dry run: nothing deleted. Re-run with --yes to delete.")
        return 0

    failures = 0
    # Subnets first: a VPC cannot be deleted while it still has subnets.
    for resource_id in [s["SubnetId"] for s in subnets] + [v["VpcId"] for v in vpcs]:
        if not _delete(ec2, resource_id):
            failures += 1

    if failures:
        print(f"{failures} resource(s) not deleted; resolve them manually.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
