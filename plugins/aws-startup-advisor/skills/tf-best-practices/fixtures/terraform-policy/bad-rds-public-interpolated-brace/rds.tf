# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: rds_not_public must still fire when a brace appears inside a quoted
# string NESTED IN AN INTERPOLATION.
#
# The lexer's first revision ended the outer string at the inner string's closing
# quote, so the rest of the line was scanned as code. The `{` in "primary{db" then
# counted toward brace depth, putting `publicly_accessible = true` at depth 2 —
# judged a nested attribute and skipped. Worse, it reported a FALSE
# rds_encryption_at_rest at the same time, with storage_encrypted = true present.
# So this shape must produce exactly one violation: rds_not_public.
resource "aws_db_instance" "interpolated_brace" {
  identifier          = "${lookup(var.names, "primary{db")}"
  instance_class      = "db.t3.micro"
  engine              = "postgres"
  publicly_accessible = true
  storage_encrypted   = true
}
