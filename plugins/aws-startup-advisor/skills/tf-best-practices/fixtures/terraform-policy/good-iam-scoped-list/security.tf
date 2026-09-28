# Compliant fixture — MUST pass (POLICY_OK).
# Proves the list-form wildcard check does NOT false-positive on:
#   (a) a list of scoped actions, and
#   (b) a list of scoped resource ARNs (list form, but not a "*" wildcard).
resource "aws_iam_policy" "good_list" {
  name = "good-scoped-list"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "arn:aws:s3:::my-bucket",
          "arn:aws:s3:::my-bucket/*",
        ]
      }
    ]
  })
}
