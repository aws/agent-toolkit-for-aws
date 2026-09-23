# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: rds_not_public must still fire when a lexically-irrelevant brace
# appears in a comment or string literal ahead of the offending attribute.
# Braces inside comments/strings/heredocs are NOT block delimiters; counting them
# as such once hid `publicly_accessible = true` and reported this stack compliant.
# Keep the stray "{" characters below — removing them defeats the guard.
resource "aws_db_instance" "bad" {
  # capacity review pending { revisit next quarter
  identifier          = "primary { db"
  instance_class      = "db.t3.micro"
  publicly_accessible = true
  storage_encrypted   = true
}
