import json
import boto3
import hashlib
import urllib.request
import urllib.parse
import uuid
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import zip_longest

dynamodb = boto3.resource("dynamodb")
seen_jobs_table = dynamodb.Table("jobhunter-seen-jobs")
MAX_JOBS_PER_RUN = 5
sqs = boto3.client("sqs")

QUEUE_URL = "https://sqs.us-east-2.amazonaws.com/044846890751/jobhunter-match-queue"

results_table = dynamodb.Table("jobhunter-results")

SENIOR_TITLE_KEYWORDS = [
    "senior",
    "sr.",
    "sr ",
    "lead",
    "principal",
    "staff",
    "architect",
    "manager",
    "director",
    "head of"
]

ENTRY_LEVEL_TITLE_KEYWORDS = [
    "junior",
    "jr.",
    "jr ",
    "entry level",
    "entry-level",
    "new grad",
    "graduate",
    "co-op",
    "coop",
    "intern",
    "internship",
    "student"
]

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

def fetch_json(url, headers=None):
    request = urllib.request.Request(
        url,
        headers=headers or {"User-Agent": "JobHunter/2.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_remotive_jobs():
    url = "https://remotive.com/api/remote-jobs?category=software-dev"

    data = fetch_json(url)

    jobs = []

    for remote_job in data.get("jobs", []):
        jobs.append({
            "title": remote_job.get("title", ""),
            "company": remote_job.get("company_name", ""),
            "url": remote_job.get("url", ""),
            "job_text": remote_job.get("description", ""),
            "source": "remotive"
        })

    return jobs


def fetch_jobicy_jobs():
    data = fetch_json(
        "https://jobicy.com/api/v2/remote-jobs?count=200&geo=canada"
    )

    return [
        {
            "title": job.get("jobTitle", ""),
            "company": job.get("companyName", ""),
            "url": job.get("url", ""),
            "job_text": job.get("jobDescription", ""),
            "source": "jobicy"
        }
        for job in data.get("jobs", [])
    ]


def fetch_remote_ok_jobs():
    data = fetch_json(
        "https://remoteok.com/api?tags=dev,python,cloud,devops",
        headers={"User-Agent": "JobHunter/2.0 (personal job search)"}
    )

    jobs = []
    for job in data:
        if not isinstance(job, dict) or not job.get("position"):
            continue

        jobs.append({
            "title": job.get("position", ""),
            "company": job.get("company", ""),
            "url": job.get("apply_url") or job.get("url", ""),
            "job_text": job.get("description", ""),
            "source": "remoteok"
        })

    return jobs


def fetch_the_muse_jobs():
    query = urllib.parse.urlencode({
        "page": 0,
        "level": "Entry Level",
        "location": "Toronto, Canada"
    })
    data = fetch_json(
        f"https://www.themuse.com/api/public/jobs?{query}"
    )

    jobs = []
    for job in data.get("results", []):
        refs = job.get("refs", {})
        company = job.get("company", {})
        jobs.append({
            "title": job.get("name", ""),
            "company": company.get("name", ""),
            "url": refs.get("landing_page", ""),
            "job_text": job.get("contents", ""),
            "source": "themuse"
        })

    return jobs


def fetch_all_jobs():
    sources = [
        ("remotive", fetch_remotive_jobs),
        ("jobicy", fetch_jobicy_jobs),
        ("remoteok", fetch_remote_ok_jobs),
        ("themuse", fetch_the_muse_jobs)
    ]
    jobs_by_source = {}

    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {
            executor.submit(fetcher): source_name
            for source_name, fetcher in sources
        }

        for future in as_completed(futures):
            source_name = futures[future]
            try:
                source_jobs = future.result()
                print(f"{source_name} jobs fetched: {len(source_jobs)}")
                source_jobs.sort(
                    key=lambda job: not any(
                        keyword in job.get("title", "").lower()
                        for keyword in ENTRY_LEVEL_TITLE_KEYWORDS
                    )
                )
                jobs_by_source[source_name] = source_jobs
            except Exception as error:
                print(f"{source_name} fetch failed: {error}")

    ordered_sources = [
        jobs_by_source.get(source_name, [])
        for source_name, _ in sources
    ]

    return [
        job
        for source_group in zip_longest(*ordered_sources)
        for job in source_group
        if job is not None
    ]


def remove_cross_source_duplicates(jobs):
    unique_jobs = []
    seen = set()

    for job in jobs:
        identity = (
            job.get("company", "").strip().lower(),
            job.get("title", "").strip().lower()
        )

        if identity in seen:
            print("Cross-source duplicate:", job.get("title", ""))
            continue

        seen.add(identity)
        unique_jobs.append(job)

    return unique_jobs



def lambda_handler(event, context):
    print("JobHunter fetcher started")

    jobs = remove_cross_source_duplicates(fetch_all_jobs())

    print("Jobs fetched:", len(jobs))

    results = []
    new_jobs_queued = 0

    for remote_job in jobs:

        job = remote_job

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

        is_entry_level_role = any(
            keyword in title_lower
            for keyword in ENTRY_LEVEL_TITLE_KEYWORDS
        )

        is_senior_role = any(
            keyword in title_lower
            for keyword in SENIOR_TITLE_KEYWORDS
        )

        if is_senior_role:
            print("Skipped senior job:", job["title"])

            results.append({
                "title": job["title"],
                "status": "senior"
            })

            continue

        is_strong_target = any(
            keyword in title_lower
            for keyword in STRONG_TARGET_KEYWORDS
        )

        is_secondary_target = any(
            keyword in title_lower
            for keyword in SECONDARY_TARGET_KEYWORDS
        )

        if is_entry_level_role:
            print("Entry-level job:", job["title"])

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
                "title": job["title"],
                "company": job["company"],
                "source": job["source"],
                "job_url": job["url"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": expires_at
            }
        )

        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "job_id": job_id,
                "title": job["title"],
                "company": job["company"],
                "job_text": job["job_text"],
                "source": job["source"],
                "url": job["url"]
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
