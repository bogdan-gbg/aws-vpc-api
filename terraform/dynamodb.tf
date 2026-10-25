# Minimal PoC table: on-demand, partition key only. No TTL, PITR, deletion
# protection, CMK or streams; the environment is destroyed after each test cycle.
resource "aws_dynamodb_table" "vpcs" {
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  # Only key attributes are declared; the other attributes are schemaless.
  attribute {
    name = "id"
    type = "S"
  }
}
