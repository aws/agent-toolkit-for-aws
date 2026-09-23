resource "aws_iam_role_policy" "codepipeline" {
  name = "heroku-eb-codepipeline"
  role = "example-role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "elasticbeanstalk:CreateStorageLocation"
      Resource = "*"
    }]
  })
}
