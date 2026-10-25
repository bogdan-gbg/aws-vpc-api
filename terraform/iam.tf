data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.project}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# One inline policy, created and destroyed with the role. No AWS managed policies:
# AWSLambdaBasicExecutionRole would add logs:CreateLogGroup on "*".
# Everything not listed here is denied by default: no Internet Gateway, NAT, routes,
# security groups, DeleteTags, extra Describe*, DeleteItem, iam:* or sts:*. An
# explicit Deny in the same role would not be a real guarantee (whoever can edit the
# role can remove it); that belongs in an SCP or a permissions boundary.
data "aws_iam_policy_document" "lambda" {
  # VPCs can only be created with ManagedBy=vpc-api in the request, and only with
  # the known tag keys.
  statement {
    sid       = "CreateVpcTagged"
    actions   = ["ec2:CreateVpc"]
    resources = ["${local.ec2_arn_prefix}:vpc/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["vpc-api"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.allowed_tag_keys
    }
  }

  # CreateSubnet is authorized on two resources: the new subnet and the parent VPC.
  # The request tag only exists on the subnet, so the VPC needs its own statement.
  statement {
    sid       = "CreateSubnetTagged"
    actions   = ["ec2:CreateSubnet"]
    resources = ["${local.ec2_arn_prefix}:subnet/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["vpc-api"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.allowed_tag_keys
    }
  }

  # The parent VPC must already be ours: no subnets in the default VPC or in any
  # foreign VPC.
  statement {
    sid       = "CreateSubnetInManagedVpc"
    actions   = ["ec2:CreateSubnet"]
    resources = ["${local.ec2_arn_prefix}:vpc/*"]

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/ManagedBy"
      values   = ["vpc-api"]
    }
  }

  # Tags only at creation time. An unrestricted CreateTags would let the function
  # put ManagedBy=vpc-api on a foreign VPC ("adopt" it) and then delete it.
  statement {
    sid     = "TagOnCreateOnly"
    actions = ["ec2:CreateTags"]
    resources = [
      "${local.ec2_arn_prefix}:vpc/*",
      "${local.ec2_arn_prefix}:subnet/*",
    ]

    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values   = ["CreateVpc", "CreateSubnet"]
    }
  }

  # Modify and delete only resources that carry the tag.
  statement {
    sid = "ManageOwnResources"
    actions = [
      "ec2:ModifyVpcAttribute",
      "ec2:DeleteVpc",
      "ec2:DeleteSubnet",
    ]
    resources = [
      "${local.ec2_arn_prefix}:vpc/*",
      "${local.ec2_arn_prefix}:subnet/*",
    ]

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/ManagedBy"
      values   = ["vpc-api"]
    }
  }

  # DescribeAvailabilityZones has no resource-level permissions; the region
  # condition keeps the function inside the deployment region.
  statement {
    sid       = "DiscoverAzs"
    actions   = ["ec2:DescribeAvailabilityZones"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  # No DeleteItem (soft delete keeps the history) and no Query (no index).
  statement {
    sid = "Table"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.vpcs.arn]
  }

  # No CreateLogGroup: the log group is managed by Terraform, so no orphan log
  # group without retention survives terraform destroy.
  statement {
    sid = "Logs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:${local.log_group_name}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.project}-lambda"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}
