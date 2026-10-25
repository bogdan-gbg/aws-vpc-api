resource "aws_apigatewayv2_api" "this" {
  name          = "${var.project}-api"
  protocol_type = "HTTP"

  # Only the web page origin, never "*". HTTP API answers the OPTIONS preflight.
  cors_configuration {
    allow_origins = ["https://${aws_cloudfront_distribution.web.domain_name}"]
    allow_methods = ["GET", "POST", "DELETE"]
    allow_headers = ["authorization", "content-type"]
  }
}

# Both app clients are in the audience: tokens from the "cli" client would
# otherwise get 401. No scopes: authorization is open to every authenticated user.
resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.this.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    issuer = "https://${aws_cognito_user_pool.this.endpoint}"
    audience = [
      aws_cognito_user_pool_client.web.id,
      aws_cognito_user_pool_client.cli.id,
    ]
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# Explicit routes only, each with the JWT authorizer. No $default catch-all route:
# a route without an authorizer would be fully public.
resource "aws_apigatewayv2_route" "this" {
  for_each = toset([
    "POST /v1/vpcs",
    "GET /v1/vpcs",
    "GET /v1/vpcs/{id}",
    "DELETE /v1/vpcs/{id}",
  ])

  api_id             = aws_apigatewayv2_api.this.id
  route_key          = each.value
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# No default_route_settings / route_settings: on HTTP API a rate or burst of 0
# blocks every request, so "no throttling" means the block is absent. No access logs.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
}
