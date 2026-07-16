output "deck_bucket_name" {
  description = "Name of the public deck bucket"
  value       = aws_s3_bucket.cbc-wilm-agent-public.id
}

# THIS is the one to use for DECK_BASE_URL / build-deck.js --asset-base.
#
# The REST endpoint, because it serves https and the website endpoint cannot
# (bs-a4a). The origin is baked into every <img src> at render time, so an http
# base means http images, which a browser blocks on an https page — leaving a
# deck with perfect text and no backgrounds, and no error to explain it.
output "deck_rest_endpoint" {
  description = "HTTPS REST endpoint — use this for DECK_BASE_URL and as build-deck.js --asset-base"
  value       = "https://${aws_s3_bucket.cbc-wilm-agent-public.bucket_regional_domain_name}"
}

# Kept for reference only. Do NOT use as the asset base: it is http-only, and
# see the warning above. Nothing depends on its index-document suffix, since
# published decks are always explicit .../index.html paths.
output "deck_website_endpoint" {
  description = "Static website endpoint (http-only). Reference only — NOT the asset base; use deck_rest_endpoint."
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
