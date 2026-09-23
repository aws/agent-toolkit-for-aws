# Compliant fixture — scoped IAM. MUST pass (POLICY_OK).
resource "aws_iam_policy" "good" {
  name = "good-scoped"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:us-east-1:111122223333:secret:db-password-*"
      }
    ]
  })
}

# Assume-role trust policy with sts:AssumeRole is NOT a wildcard violation.
resource "aws_iam_role" "app" {
  name = "app-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "lambda.amazonaws.com" }
      }
    ]
  })
}
