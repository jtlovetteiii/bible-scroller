resource "aws_s3_bucket" "cbc-wilm-agent-public" {
  bucket = "cbc-wilm-agent-public"
}

resource "aws_s3_bucket_website_configuration" "cbc-wilm-agent-public-website" {
  bucket = aws_s3_bucket.cbc-wilm-agent-public.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "error.html"
  }
}

# Lets a deck rendered OUTSIDE this bucket (a local preview built with
# --asset-base pointing here) load template images without tainting the
# html2canvas canvas, which would make the Export button throw SecurityError
# while the slides still render correctly. Decks served from the bucket itself
# are same-origin and don't need this.
#
# This is only half the fix: the <img> tags must also carry
# crossorigin="anonymous" or the browser never sends Origin and the response
# headers go unused. That half lives in build-deck.js — see bs-517.
#
# allowed_origins is "*" because every object here is already anonymously
# readable by the bucket policy; a narrower list would imply a confidentiality
# this bucket does not have.
resource "aws_s3_bucket_cors_configuration" "cbc-wilm-agent-public-cors" {
  bucket = aws_s3_bucket.cbc-wilm-agent-public.id

  cors_rule {
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

# ACLs are disabled: object access is governed entirely by the bucket policy
# below and by the agent's IAM policy in iam.tf.
resource "aws_s3_bucket_ownership_controls" "cbc-wilm-agent-public-ownership" {
  bucket = aws_s3_bucket.cbc-wilm-agent-public.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Only the two policy-related blocks are relaxed; public ACLs stay blocked
# because BucketOwnerEnforced means no ACL can grant anything anyway.
resource "aws_s3_bucket_public_access_block" "cbc-wilm-agent-public-access" {
  bucket = aws_s3_bucket.cbc-wilm-agent-public.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = false
  restrict_public_buckets = false
}

data "aws_iam_policy_document" "cbc-wilm-agent-public-read" {
  statement {
    sid    = "PublicReadObjects"
    effect = "Allow"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.cbc-wilm-agent-public.arn}/*"]
  }
}

resource "aws_s3_bucket_policy" "cbc-wilm-agent-public-policy" {
  depends_on = [aws_s3_bucket_public_access_block.cbc-wilm-agent-public-access]

  bucket = aws_s3_bucket.cbc-wilm-agent-public.id
  policy = data.aws_iam_policy_document.cbc-wilm-agent-public-read.json
}
