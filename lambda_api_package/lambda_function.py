import json
import boto3
import time
import uuid
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("jobhunter-results")

sqs = boto3.client("sqs")
QUEUE_URL = "https://sqs.us-east-2.amazonaws.com/044846890751/jobhunter-match-queue"


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