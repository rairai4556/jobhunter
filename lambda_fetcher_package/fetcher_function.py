import json
import boto3
import hashlib
import urllib.request
import uuid
import time
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
seen_jobs_table = dynamodb.Table("jobhunter-seen-jobs")
MAX_JOBS_PER_RUN = 5
sqs = boto3.client("sqs")

QUEUE_URL = "https://sqs.us-east-2.amazonaws.com/044846890751/jobhunter-match-queue"

results_table = dynamodb.Table("jobhunter-results")

STRONG_TARGET_KEYWORDS = [
    "devops",
    "cloud",
    "infrastructure",
    "platform",
    "site reliability",
    "sre",
    "aws"
]

SECONDARY_TARGET_KEYWORDS = [
    "qa",
    "test",
    "support",
    "systems",
    "service desk",
    "help desk",
    "helpdesk"
]

def lambda_handler(event, context):
    print("JobHunter fetcher started")

    url = "https://remotive.com/api/remote-jobs?category=software-dev"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(request) as response:
        data = json.loads(response.read().decode("utf-8"))

    jobs = data.get("jobs", [])

    print("Jobs fetched:", len(jobs))

    results = []
    new_jobs_queued = 0

    for remote_job in jobs:

        job = {
            "title": remote_job.get("title", ""),
            "company": remote_job.get("company_name", ""),
            "url": remote_job.get("url", ""),
            "job_text": remote_job.get("description", "")
        }

        raw_key = (
            job["company"]
            + "|"
            + job["title"]
            + "|"
            + job["url"]
        )

        job_key = hashlib.sha256(
            raw_key.encode("utf-8")
        ).hexdigest()

        response = seen_jobs_table.get_item(
            Key={
                "job_key": job_key
            }
        )

        if "Item" in response:
            print("Duplicate:", job["title"])

            results.append({
                "title": job["title"],
                "status": "duplicate"
            })

            continue

        
        title_lower = job["title"].lower()

        is_strong_target = any(
            keyword in title_lower
            for keyword in STRONG_TARGET_KEYWORDS
        )

        is_secondary_target = any(
            keyword in title_lower
            for keyword in SECONDARY_TARGET_KEYWORDS
        )

        if not (
            is_strong_target
            or is_secondary_target
        ):
            print("Skipped irrelevant job:", job["title"])

            results.append({
                "title": job["title"],
                "status": "irrelevant"
            })

            continue
        print("New job:", job["title"])
        job_id = str(uuid.uuid4())

        expires_at = int(time.time()) + (7 * 24 * 60 * 60)

        results_table.put_item(
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
                "job_text": job["job_text"]
            })
        )

        seen_jobs_table.put_item(
            Item={
                "job_key": job_key,
                "title": job["title"],
                "company": job["company"],
                "url": job["url"]
            }
        )

        results.append({
            "title": job["title"],
            "company": job["company"],
            "status": "new",
            "job_key": job_key,
            "job_id": job_id
        })
        new_jobs_queued += 1

        if new_jobs_queued >= MAX_JOBS_PER_RUN:
            print("Reached maximum new jobs per run")
            break
    return {
        "statusCode": 200,
        "body": json.dumps({
            "jobs_checked": len(results),
            "new_jobs_queued": new_jobs_queued,
            "results": results
        })
    }