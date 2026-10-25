# LITE tier with the classic hosted login: the cheapest option that supports the
# code + PKCE flow. Self sign-up is disabled: only users created here can log in.
# Plain usernames and no email attribute: Cognito never sends messages, so the
# stack holds no personal data.
resource "aws_cognito_user_pool" "this" {
  name              = "${var.project}-users"
  user_pool_tier    = "LITE"
  mfa_configuration = "OFF"

  # "Reviewer" and "reviewer" are the same user. Cannot be changed after creation.
  username_configuration {
    case_sensitive = false
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # No email or phone to send a code to: passwords are reset by the administrator
  # (terraform apply -replace=random_password.<user>).
  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_domain" "this" {
  domain                = local.cognito_domain_prefix
  user_pool_id          = aws_cognito_user_pool.this.id
  managed_login_version = 1
}

# Public client for the web page: no secret (it would be visible in the browser),
# code flow with PKCE, redirects only to the CloudFront domain.
resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${var.project}-web"
  user_pool_id                         = aws_cognito_user_pool.this.id
  generate_secret                      = false
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["https://${aws_cloudfront_distribution.web.domain_name}/"]
  logout_urls                          = ["https://${aws_cloudfront_distribution.web.domain_name}/"]
  # Declared explicitly to avoid drift on every plan.
  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]
}

# Client for the operator scripts: only the admin password flow, which also needs
# AWS credentials (cognito-idp:AdminInitiateAuth), so it opens no password-guessing
# path. ALLOW_USER_PASSWORD_AUTH is enabled on no client.
resource "aws_cognito_user_pool_client" "cli" {
  name                = "${var.project}-cli"
  user_pool_id        = aws_cognito_user_pool.this.id
  generate_secret     = false
  explicit_auth_flows = ["ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
}

# Random permanent passwords: the users log in directly, without the
# FORCE_CHANGE_PASSWORD step. They are stored in the local state, which is never
# committed. At least one character of every class, as Cognito requires.
resource "random_password" "demo_owner" {
  length           = 20
  special          = true
  min_upper        = 1
  min_lower        = 1
  min_numeric      = 1
  min_special      = 1
  override_special = "!@#$%&*()-_=+[]{}<>:?"
}

resource "random_password" "reviewer" {
  length           = 20
  special          = true
  min_upper        = 1
  min_lower        = 1
  min_numeric      = 1
  min_special      = 1
  override_special = "!@#$%&*()-_=+[]{}<>:?"
}

# SUPPRESS: Cognito sends no invitation; the credentials are shared out of band.
resource "aws_cognito_user" "demo_owner" {
  user_pool_id   = aws_cognito_user_pool.this.id
  username       = var.demo_owner_username
  password       = random_password.demo_owner.result
  message_action = "SUPPRESS"
}

resource "aws_cognito_user" "reviewer" {
  user_pool_id   = aws_cognito_user_pool.this.id
  username       = var.reviewer_username
  password       = random_password.reviewer.result
  message_action = "SUPPRESS"
}
