# No "profile" here: credentials come from AWS_PROFILE, so the code runs on any
# machine and does not expose local configuration.
provider "aws" {
  region = var.aws_region

  # ManagedBy is deliberately not here: it is reserved for the VPCs created at
  # runtime, and the Lambda IAM policy relies on it.
  default_tags {
    tags = {
      Project = var.project
      IaC     = "terraform"
    }
  }
}
