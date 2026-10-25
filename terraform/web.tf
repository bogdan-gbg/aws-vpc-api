# Private bucket: no website hosting, all public access blocked. Only CloudFront
# can read it, through Origin Access Control.
resource "aws_s3_bucket" "web" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = local.bucket_name
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_iam_policy_document" "web_bucket" {
  statement {
    sid       = "CloudFrontReadOnly"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    # Only this distribution, not any CloudFront distribution.
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.web.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = data.aws_iam_policy_document.web_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.web]
}

# No caching: a new deployment is visible immediately, without invalidations.
data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

# connect-src uses the execute-api wildcard for the region instead of the exact API
# URL: the API CORS origin needs the CloudFront domain, so referencing the API here
# would create a dependency cycle. The Cognito domain is exact (built from its prefix).
resource "aws_cloudfront_response_headers_policy" "web" {
  name = "${var.project}-web-security-${local.suffix}"

  security_headers_config {
    content_security_policy {
      content_security_policy = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src https://*.execute-api.${var.aws_region}.amazonaws.com https://${local.cognito_domain}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
      override                = true
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }

    content_type_options {
      override = true
    }
  }
}

# Default *.cloudfront.net certificate: no custom domain, so no ACM certificate and
# no provider in us-east-1.
resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  origin {
    origin_id                = "s3-web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    target_origin_id           = "s3-web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.web.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

locals {
  # Generated, never committed: the values change on every apply after a destroy.
  config_js = templatefile("${path.module}/../web/config.js.tftpl", {
    api_url        = aws_apigatewayv2_api.this.api_endpoint
    cognito_domain = local.cognito_domain
    client_id      = aws_cognito_user_pool_client.web.id
    redirect_uri   = "https://${aws_cloudfront_distribution.web.domain_name}/"
  })
}

resource "aws_s3_object" "index_html" {
  bucket       = aws_s3_bucket.web.id
  key          = "index.html"
  source       = "${path.module}/../web/index.html"
  source_hash  = filemd5("${path.module}/../web/index.html")
  content_type = "text/html; charset=utf-8"
}

resource "aws_s3_object" "app_js" {
  bucket       = aws_s3_bucket.web.id
  key          = "app.js"
  source       = "${path.module}/../web/app.js"
  source_hash  = filemd5("${path.module}/../web/app.js")
  content_type = "application/javascript"
}

resource "aws_s3_object" "config_js" {
  bucket       = aws_s3_bucket.web.id
  key          = "config.js"
  content      = local.config_js
  source_hash  = md5(local.config_js)
  content_type = "application/javascript"
}
