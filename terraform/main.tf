data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 4
}
