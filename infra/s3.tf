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
