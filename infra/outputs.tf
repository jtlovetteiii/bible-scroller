output "deck_bucket_name" {
  description = "Name of the public deck bucket"
  value       = aws_s3_bucket.cbc-wilm-agent-public.id
}

output "deck_website_endpoint" {
  description = "Static website endpoint; use as the media asset base for build-deck.js"
  value       = "http://${aws_s3_bucket_website_configuration.cbc-wilm-agent-public-website.website_endpoint}"
}

output "deck_publisher_policy_arn" {
  description = "Policy granting the agent read/write on the deck bucket"
  value       = aws_iam_policy.cbc-wilm-agent-publisher.arn
}

output "deck_publisher_user_name" {
  description = "Agent's IAM user; create its access key by hand, out of state"
  value       = aws_iam_user.cbc-wilm-agent.name
}
