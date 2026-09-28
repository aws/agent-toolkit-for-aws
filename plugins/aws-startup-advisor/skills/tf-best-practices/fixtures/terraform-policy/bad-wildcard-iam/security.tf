# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: no_wildcard_iam failure path (Allow Action "*" on Resource "*").
resource "aws_iam_policy" "bad" {
  name = "bad-wildcard"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "*"
        Resource = "*"
      }
    ]
  })
}
