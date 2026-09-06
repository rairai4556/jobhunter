terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
    archive = {
      source = "hashicorp/archive"
    }
  }
}

provider "aws" {
  region  = "us-east-2"
  profile = "terraform-sso"
}


data "archive_file" "jobhunter_lambda_zip" {
  type        = "zip"
  source_dir  = "../lambda_api_package"
  output_path = "jobhunter_lambda.zip"
}

data "archive_file" "jobhunter_worker_zip" {
  type        = "zip"
  source_dir  = "../lambda_worker_package"
  output_path = "jobhunter_worker.zip"
}

data "archive_file" "jobhunter_fetcher_zip" {
  type        = "zip"
  source_dir  = "../lambda_fetcher_package"
  output_path = "jobhunter_fetcher.zip"
}

resource "aws_lambda_function" "jobhunter_worker" {
  function_name = "jobhunter-worker"

  role = aws_iam_role.jobhunter_worker_role.arn

  handler = "worker_function.lambda_handler"

  runtime = "python3.13"

  filename         = data.archive_file.jobhunter_worker_zip.output_path
  source_code_hash = data.archive_file.jobhunter_worker_zip.output_base64sha256

  timeout = 60

  memory_size = 512
}

resource "aws_iam_role" "jobhunter_lambda_role" {
  name = "jobhunter-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role" "jobhunter_worker_role" {
  name = "jobhunter-worker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "jobhunter_lambda_basic_execution" {
  role       = aws_iam_role.jobhunter_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "jobhunter_worker_basic_execution" {
  role       = aws_iam_role.jobhunter_worker_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "jobhunter_lambda" {
  role             = aws_iam_role.jobhunter_lambda_role.arn
  function_name    = "jobhunter-lambda"
  filename         = data.archive_file.jobhunter_lambda_zip.output_path
  source_code_hash = data.archive_file.jobhunter_lambda_zip.output_base64sha256
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.13"
  timeout          = 60
  memory_size      = 512
}

resource "aws_lambda_function" "jobhunter_fetcher" {
  function_name = "jobhunter-fetcher"

  role = aws_iam_role.jobhunter_fetcher_role.arn

  handler = "fetcher_function.lambda_handler"

  runtime = "python3.13"

  filename         = data.archive_file.jobhunter_fetcher_zip.output_path
  source_code_hash = data.archive_file.jobhunter_fetcher_zip.output_base64sha256

  timeout = 60

  memory_size = 256
}

resource "aws_iam_role_policy" "jobhunter_worker_ssm_access" {
  name = "jobhunter-worker-ssm-access"
  role = aws_iam_role.jobhunter_worker_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "ssm:GetParameter"
        ]

        Resource = ["arn:aws:ssm:us-east-2:*:parameter/jobhunter/openai-api-key",
          "arn:aws:ssm:us-east-2:*:parameter/jobhunter/telegram-bot-token",
        "arn:aws:ssm:us-east-2:*:parameter/jobhunter/telegram-chat-id"]
      }
    ]
  })
}

resource "aws_iam_role_policy" "jobhunter_worker_sqs_access" {
  name = "jobhunter-worker-sqs-access"
  role = aws_iam_role.jobhunter_worker_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]

        Resource = aws_sqs_queue.jobhunter_match_queue.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "jobhunter_worker_dynamodb_access" {
  name = "jobhunter-worker-dynamodb-access"
  role = aws_iam_role.jobhunter_worker_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "dynamodb:UpdateItem"
        ]

        Resource = aws_dynamodb_table.jobhunter_results.arn
      }
    ]
  })
}

resource "aws_apigatewayv2_api" "jobhunter_api" {
  name          = "jobhunter-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "jobhunter_lambda_integration" {
  api_id                 = aws_apigatewayv2_api.jobhunter_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.jobhunter_lambda.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "jobhunter_match_route" {
  api_id    = aws_apigatewayv2_api.jobhunter_api.id
  route_key = "POST /match"
  target    = "integrations/${aws_apigatewayv2_integration.jobhunter_lambda_integration.id}"
}

resource "aws_apigatewayv2_route" "jobhunter_results_route" {
  api_id    = aws_apigatewayv2_api.jobhunter_api.id
  route_key = "GET /results/{job_id}"
  target    = "integrations/${aws_apigatewayv2_integration.jobhunter_lambda_integration.id}"
}

resource "aws_apigatewayv2_stage" "jobhunter_stage" {
  name        = "$default"
  api_id      = aws_apigatewayv2_api.jobhunter_api.id
  auto_deploy = true

}

resource "aws_lambda_permission" "allow_api_gateway" {
  function_name = aws_lambda_function.jobhunter_lambda.function_name
  action        = "lambda:InvokeFunction"
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.jobhunter_api.execution_arn}/*/*"
}

output "jobhunter_api_endpoint" {
  value = aws_apigatewayv2_api.jobhunter_api.api_endpoint
}

resource "aws_dynamodb_table" "jobhunter_results" {
  name         = "jobhunter-results"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"
  attribute {
    name = "job_id"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "jobhunter_seen_jobs" {
  name         = "jobhunter-seen-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_key"

  attribute {
    name = "job_key"
    type = "S"
  }
}

resource "aws_s3_bucket" "jobhunter_resume" {
  bucket = "jobhunter-resume-storage"

  force_destroy = false
  tags          = { Name = "jobhunter-resume-storage" }

}

resource "aws_iam_role_policy" "jobhunter_fetcher_results_access" {
  name = "jobhunter-fetcher-results-access"
  role = aws_iam_role.jobhunter_fetcher_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "dynamodb:PutItem"
        ]

        Resource = aws_dynamodb_table.jobhunter_results.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "jobhunter_worker_s3_resume_access" {
  name = "jobhunter-worker-s3-resume-access"
  role = aws_iam_role.jobhunter_worker_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "s3:GetObject"
        ]

        Resource = "arn:aws:s3:::jobhunter-resume-storage/resume.txt"
      }
    ]
  })
}

resource "aws_iam_role_policy" "jobhunter_fetcher_seen_jobs_access" {
  name = "jobhunter-fetcher-seen-jobs-access"
  role = aws_iam_role.jobhunter_fetcher_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem"
        ]

        Resource = aws_dynamodb_table.jobhunter_seen_jobs.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "jobhunter_lambda_dynamodb_access" {
  name = "jobhunter-lambda-dynamodb-access"
  role = aws_iam_role.jobhunter_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem"
        ]

        Resource = aws_dynamodb_table.jobhunter_results.arn
      }
    ]
  })
}

resource "aws_sqs_queue" "jobhunter_match_queue" {
  name                       = "jobhunter-match-queue"
  visibility_timeout_seconds = 360
  message_retention_seconds  = 86400
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobhunter_match_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_iam_role_policy" "jobhunter_lambda_sqs_access" {
  name = "jobhunter-lambda-sqs-access"
  role = aws_iam_role.jobhunter_lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "sqs:SendMessage"
        ]

        Resource = aws_sqs_queue.jobhunter_match_queue.arn
      }
    ]
  })
}


resource "aws_lambda_event_source_mapping" "jobhunter_worker_mapping" {
  function_name    = aws_lambda_function.jobhunter_worker.function_name
  event_source_arn = aws_sqs_queue.jobhunter_match_queue.arn
  batch_size       = 1
  enabled          = true
}

resource "aws_sqs_queue" "jobhunter_match_dlq" {
  name                      = "jobhunter-match-dlq"
  message_retention_seconds = 1209600
}

resource "aws_cloudwatch_metric_alarm" "jobhunter_worker_errors" {
  alarm_name = "jobhunter-worker-errors"

  namespace   = "AWS/Lambda"
  metric_name = "Errors"

  dimensions = {
    FunctionName = aws_lambda_function.jobhunter_worker.function_name
  }

  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  alarm_actions     = [aws_sns_topic.jobhunter_alerts.arn]
  alarm_description = "Alarm when the JobHunter worker Lambda has an error."
}

resource "aws_cloudwatch_metric_alarm" "jobhunter_dlq_messages" {
  alarm_name = "jobhunter-dlq-messages"

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.jobhunter_match_dlq.name
  }

  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  alarm_actions     = [aws_sns_topic.jobhunter_alerts.arn]
  alarm_description = "Alarm when a message appears in the JobHunter dead-letter queue."


}

resource "aws_sns_topic" "jobhunter_alerts" {
  name = "jobhunter-alerts"

}



resource "aws_sns_topic_subscription" "jobhunter_email_alerts" {
  topic_arn = aws_sns_topic.jobhunter_alerts.arn
  protocol  = "email"
  endpoint  = "iamanothereraihan@gmail.com"
}

resource "aws_dynamodb_table" "jobhunter_resume_cache" {
  name         = "jobhunter-resume-cache"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "resume_hash"

  attribute {
    name = "resume_hash"
    type = "S"
  }
}

resource "aws_iam_role" "jobhunter_fetcher_role" {
  name = "jobhunter-fetcher-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "jobhunter_fetcher_basic_execution" {
  role       = aws_iam_role.jobhunter_fetcher_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "jobhunter_fetcher_sqs_access" {
  name = "jobhunter-fetcher-sqs-access"
  role = aws_iam_role.jobhunter_fetcher_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "sqs:SendMessage"
        ]

        Resource = aws_sqs_queue.jobhunter_match_queue.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "jobhunter_worker_resume_cache_access" {
  name = "jobhunter-worker-resume-cache-access"
  role = aws_iam_role.jobhunter_worker_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem"
        ]

        Resource = aws_dynamodb_table.jobhunter_resume_cache.arn
      }
    ]
  })
}


resource "aws_cloudwatch_event_rule" "jobhunter_fetch_schedule" {
  name                = "jobhunter-fetch-schedule"
  schedule_expression = "rate(1 day)"
}

resource "aws_cloudwatch_event_target" "jobhunter_fetcher_target" {
  rule      = aws_cloudwatch_event_rule.jobhunter_fetch_schedule.name
  target_id = "jobhunter-fetcher"
  arn       = aws_lambda_function.jobhunter_fetcher.arn
}

resource "aws_lambda_permission" "allow_eventbridge_fetcher" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.jobhunter_fetcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.jobhunter_fetch_schedule.arn
}

resource "aws_cloudwatch_metric_alarm" "jobhunter_fetcher_errors" {
  alarm_name          = "jobhunter-fetcher-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.jobhunter_fetcher.function_name
  }

  alarm_actions = [
    aws_sns_topic.jobhunter_alerts.arn
  ]
}