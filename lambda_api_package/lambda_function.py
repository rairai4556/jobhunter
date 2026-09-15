import json
import boto3
import time
import uuid
from datetime import datetime, timezone
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("jobhunter-results")

sqs = boto3.client("sqs")
QUEUE_URL = "https://sqs.us-east-2.amazonaws.com/044846890751/jobhunter-match-queue"
ssm = boto3.client("ssm", region_name="us-east-2")

def lambda_handler(event, context):
    print("JobHunter Lambda started")

    route_key = event.get("routeKey", "")

    if route_key == "GET /results/{job_id}":
        path_parameters = event.get("pathParameters", {})
        job_id = path_parameters.get("job_id", "")

        if not job_id:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "Missing job_id"
                })
            }

        response = table.get_item(
            Key={
                "job_id": job_id
            }
        )

        item = response.get("Item")

        if not item:
            return {
                "statusCode": 404,
                "body": json.dumps({
                    "message": "Job not found"
                })
            }

        return {
            "statusCode": 200,
            "body": json.dumps(item)
        }

    body = event.get("body", event)

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "Invalid JSON body"
                })
            }
    if not isinstance(body, dict):
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "Request body must be a JSON object"
            })
        }

    if route_key == "POST /tmu-jobs":
        headers = event.get("headers", {})

        provided_key = headers.get("x-jobhunter-key", "")

        secret_response = ssm.get_parameter(
            Name="/jobhunter/tmu-ingest-key",
            WithDecryption=True
        )

        expected_key = secret_response["Parameter"]["Value"]

        if provided_key != expected_key:
            return {
                "statusCode": 401,
                "body": json.dumps({
                    "message": "Unauthorized"
                })
            }
        posting_id = body.get("postingId", "")
        title = body.get("title", "")
        company = body.get("company", "")
        job_text = body.get("job_text", "")

        if not posting_id:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "Missing postingId"
                })
            }

        if not title:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "Missing title"
                })
            }

        if not job_text:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "Missing job_text"
                })
            }

        job_id = f"tmu-{posting_id}"
        expires_at = int(time.time()) + (7 * 24 * 60 * 60)

        try:
            table.put_item(
                Item={
                    "job_id": job_id,
                    "status": "PROCESSING",
                    "title": title,
                    "company": company,
                    "source": "tmu",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": expires_at
                },
                ConditionExpression="attribute_not_exists(job_id)"
            )

        except ClientError as error:

            if (
                error.response["Error"]["Code"]
                == "ConditionalCheckFailedException"
            ):
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "job_id": job_id,
                        "status": "DUPLICATE"
                    })
                }

            raise

        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "job_id": job_id,
                "title": title,
                "company": company,
                "job_text": job_text,
                "source": "tmu"
            })
        )

        return {
            "statusCode": 202,
            "body": json.dumps({
                "job_id": job_id,
                "status": "PROCESSING"
            })
        }

    resume_text = body.get(
        "resume_text",
        ""
    )

    job_text = body.get(
        "job_text",
        ""
    )

    if not resume_text:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "Missing resume_text"
            })
        }

    if not job_text:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "Missing job_text"
            })
        }

    job_id = str(uuid.uuid4())

    expires_at = int(time.time()) + (7 * 24 * 60 * 60)
    table.put_item(
        Item={
            "job_id": job_id,
            "status": "PROCESSING",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at
        }
    )

    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps({
            "job_id": job_id,
            "resume_text": resume_text,
            "job_text": job_text
        })
    )

    return {
        "statusCode": 202,
        "body": json.dumps({
            "job_id": job_id,
            "status": "PROCESSING"
        })
    }