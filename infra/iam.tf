# Read/write policy for the unattended deck-creation agent, attached directly to
# a dedicated IAM user. The agent runs on a self-hosted box (see
# specs/email-agent.md §4.6), so there is no instance profile to assume a role
# from; the scoping below is what limits blast radius, not an intermediate role.
data "aws_iam_policy_document" "cbc-wilm-agent-publisher" {
  statement {
    sid       = "ListBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.cbc-wilm-agent-public.arn]
  }

  statement {
    sid    = "ReadWriteObjects"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]

    resources = ["${aws_s3_bucket.cbc-wilm-agent-public.arn}/*"]
  }
}

resource "aws_iam_policy" "cbc-wilm-agent-publisher" {
  name        = "cbc-wilm-agent-publisher"
  description = "Read/write access to the cbc-wilm-agent-public deck bucket"
  policy      = data.aws_iam_policy_document.cbc-wilm-agent-publisher.json
}

# The agent's own identity, kept separate from any human user so it can be
# revoked and audited independently.
#
# Access keys are deliberately NOT managed here: aws_iam_access_key would write
# the secret into the Terraform state. Create the key by hand and put it only in
# the agent host's environment.
resource "aws_iam_user" "cbc-wilm-agent" {
  name = "cbc-wilm-agent"
}

resource "aws_iam_user_policy_attachment" "cbc-wilm-agent-publisher" {
  user       = aws_iam_user.cbc-wilm-agent.name
  policy_arn = aws_iam_policy.cbc-wilm-agent-publisher.arn
}
