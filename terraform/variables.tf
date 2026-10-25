variable "aws_region" {
  description = "AWS region for the whole stack and for the VPCs created by the API."
  type        = string
  default     = "eu-central-1"

  # EU for data residency, enabled by default (opt-in regions fail late in a new
  # account), and at least 3 AZs (up to 6 subnets = 2 per AZ). Static list,
  # maintained by hand.
  validation {
    condition = contains(
      ["eu-central-1", "eu-west-1", "eu-west-2", "eu-west-3", "eu-north-1"],
      var.aws_region
    )
    error_message = "aws_region must be an EU region enabled by default with at least 3 AZs: eu-central-1, eu-west-1, eu-west-2, eu-west-3, eu-north-1."
  }
}

variable "project" {
  description = "Name prefix for every resource. Lowercase, because it is used in the S3 bucket name and the Cognito domain prefix."
  type        = string
  default     = "vpc-api"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.project))
    error_message = "project must be 3-20 characters: lowercase letters, digits and '-'."
  }
}

# Plain usernames, no email: Cognito never sends anything (the credentials are
# printed by env.py up and shared out of band), so no personal data is needed.
variable "demo_owner_username" {
  description = "Username of the Cognito user used by the operator and the end-to-end test."
  type        = string
  default     = "demo-owner"

  validation {
    condition     = can(regex("^[a-z0-9._-]{3,32}$", var.demo_owner_username))
    error_message = "demo_owner_username must be 3-32 characters: lowercase letters, digits, '.', '_' and '-'."
  }
}

variable "reviewer_username" {
  description = "Username of the Cognito user handed to the reviewers."
  type        = string
  default     = "reviewer"

  validation {
    condition     = can(regex("^[a-z0-9._-]{3,32}$", var.reviewer_username))
    error_message = "reviewer_username must be 3-32 characters: lowercase letters, digits, '.', '_' and '-'."
  }
}
