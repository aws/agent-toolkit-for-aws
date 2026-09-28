# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Regression for the list-form wildcard gap: Resource = ["*"] (single-element
# list) must FAIL, same as the bare-string Resource = "*" form.
resource "aws_iam_policy" "bad_listform" {
  name = "bad-listform-wildcard"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:*"]
        Resource = ["*"]
      }
    ]
  })
}
