# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: rds_not_public must still fire when a CLOSING brace appears in a
# comment, a string, and a heredoc body ahead of the offending attribute.
# A `}` in those positions is not a block delimiter; treating it as one truncated
# the resource body before `publicly_accessible = true` and reported zero
# violations. Keep every stray "}" below — removing them defeats the guard.
resource "aws_db_instance" "bad" {
  storage_encrypted = true
  # capacity review } pending
  identifier        = "primary } db"
  description       = <<EOT
  a closing } brace inside heredoc body
EOT
  publicly_accessible = true
}
