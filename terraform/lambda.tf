# Only the standard library and the boto3 shipped with the runtime are used, so the
# package is just the source tree: no layer, no dependency build.
# build/ is git-ignored, so it is missing in a fresh clone: the archive provider
# creates the parent directory of output_path when it reads this data source, and
# scripts/env.py up also creates it before terraform init.
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/../build/lambda.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]
}

# Declared here so it gets a retention and is removed by terraform destroy; the
# function has no permission to create it on its own.
resource "aws_cloudwatch_log_group" "lambda" {
  name              = local.log_group_name
  retention_in_days = 1
}

resource "aws_lambda_function" "api" {
  function_name    = local.function_name
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.14"
  handler          = "vpc_api.handler.handler"
  architectures    = ["arm64"]
  memory_size      = 256
  timeout          = 25 # Below the fixed 30 s HTTP API integration timeout.
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.vpcs.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

# Only this API may invoke the function; there is no Function URL that could
# bypass API Gateway and its JWT authorizer.
resource "aws_lambda_permission" "api" {
  statement_id  = "AllowHttpApiInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
