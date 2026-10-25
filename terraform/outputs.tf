output "api_url" {
  description = "HTTP API base URL (without /v1 and without a trailing slash)."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "web_url" {
  description = "Web page URL."
  value       = "https://${aws_cloudfront_distribution.web.domain_name}/"
}

output "cognito_domain" {
  description = "Cognito hosted login domain."
  value       = local.cognito_domain
}

output "user_pool_id" {
  description = "Cognito user pool id (its prefix is the region)."
  value       = aws_cognito_user_pool.this.id
}

output "web_client_id" {
  description = "App client used by the web page."
  value       = aws_cognito_user_pool_client.web.id
}

output "cli_client_id" {
  description = "App client used by the operator scripts."
  value       = aws_cognito_user_pool_client.cli.id
}

output "table_name" {
  description = "DynamoDB table with the VPC requests."
  value       = aws_dynamodb_table.vpcs.name
}

output "demo_owner_username" {
  description = "Username of the demo-owner user."
  value       = aws_cognito_user.demo_owner.username
}

output "reviewer_username" {
  description = "Username of the reviewer user."
  value       = aws_cognito_user.reviewer.username
}

output "demo_owner_password" {
  description = "Password of the demo-owner user."
  value       = random_password.demo_owner.result
  sensitive   = true
}

output "reviewer_password" {
  description = "Password of the reviewer user."
  value       = random_password.reviewer.result
  sensitive   = true
}
