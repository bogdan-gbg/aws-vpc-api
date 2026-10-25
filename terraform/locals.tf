locals {
  account_id     = data.aws_caller_identity.current.account_id
  ec2_arn_prefix = "arn:aws:ec2:${var.aws_region}:${local.account_id}"

  # The tag contract of the runtime resources, enforced in IAM (aws:TagKeys).
  allowed_tag_keys = ["Name", "ManagedBy", "RequestId", "CreatedBy", "Tier"]

  # Bucket names and Cognito domain prefixes are globally unique: random suffix.
  suffix = random_id.suffix.hex

  function_name         = "${var.project}-api"
  table_name            = "${var.project}-vpcs"
  log_group_name        = "/aws/lambda/${local.function_name}"
  bucket_name           = "${var.project}-web-${local.suffix}"
  cognito_domain_prefix = "${var.project}-${local.suffix}"
  # Built from the prefix (not from the domain resource) so the CloudFront CSP does
  # not depend on Cognito, which itself depends on CloudFront.
  cognito_domain = "${local.cognito_domain_prefix}.auth.${var.aws_region}.amazoncognito.com"
}
