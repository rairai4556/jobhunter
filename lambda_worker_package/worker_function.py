import json
import boto3
import hashlib
import urllib.request
import urllib.parse
import uuid
from matcher import match_job
from resume_extractor import ResumeAnalysis
from cover_letter import generate_cover_letter
from pdf_document import create_cover_letter_pdf

dynamodb = boto3.resource("dynamodb")

table = dynamodb.Table("jobhunter-results")
resume_cache_table = dynamodb.Table("jobhunter-resume-cache")

s3 = boto3.client("s3")

ssm = boto3.client(
    "ssm",
    region_name="us-east-2"
)

RESUME_BUCKET = "jobhunter-resume-storage"
RESUME_KEY = "resume.txt"


def get_telegram_credentials():
    token_response = ssm.get_parameter(
        Name="/jobhunter/telegram-bot-token",
        WithDecryption=True
    )

    chat_response = ssm.get_parameter(
        Name="/jobhunter/telegram-chat-id",
        WithDecryption=True
    )

    bot_token = token_response["Parameter"]["Value"]
    chat_id = chat_response["Parameter"]["Value"]

    return bot_token, chat_id


def send_telegram_text(text):
    bot_token, chat_id = get_telegram_credentials()

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text
    }).encode("utf-8")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=data,
        method="POST"
    )

    with urllib.request.urlopen(
        request,
        timeout=10
    ) as response:

        print(
            "Telegram notification sent:",
            response.status
        )


def send_telegram_message(result):
    send_telegram_text(build_telegram_message(result))


def build_telegram_message(result):
    reasons = "\n".join(
        f"- {reason}"
        for reason in result.get("reasons", [])
    )

    return (
        "🚀 JobHunter APPLY Match\n\n"
        f"Job: {result.get('job_title', '')}\n"
        f"Company: {result.get('company', '')}\n"
        f"Source: {result.get('source', '')}\n"
        f"Recommendation: {result.get('recommendation', '')}\n"
        f"Technical Match: {result.get('technical_match', 0)}%\n"
        f"Experience Match: {result.get('experience_match', 0)}%\n"
        f"Apply: {result.get('url', '')}\n\n"
        f"Why:\n{reasons}"
    )


def send_telegram_cover_letter_pdf(result):
    bot_token, chat_id = get_telegram_credentials()
    boundary = f"JobHunterBoundary{uuid.uuid4().hex}"
    caption = build_telegram_message(result)[:1024]
    filename = "tailored-cover-letter.pdf"
    pdf_bytes = create_cover_letter_pdf(result.get("cover_letter", ""))

    parts = [
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
        f"{chat_id}\r\n".encode("utf-8"),
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="caption"\r\n\r\n'
        f"{caption}\r\n".encode("utf-8"),
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n".encode("utf-8"),
        pdf_bytes,
        f"\r\n--{boundary}--\r\n".encode("utf-8")
    ]
    body = b"".join(parts)

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendDocument",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        },
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        print("Telegram cover letter PDF sent:", response.status)


def lambda_handler(event, context):

    print("JobHunter worker started")

    for record in event["Records"]:

        message = json.loads(
            record["body"]
        )

        job_id = message["job_id"]

        job_title = message.get(
            "title",
            ""
        )

        company = message.get(
            "company",
            ""
        )

        source = message.get("source", "")
        job_url = message.get("url", "")

        resume_object = s3.get_object(
            Bucket=RESUME_BUCKET,
            Key=RESUME_KEY
        )

        resume_text = resume_object[
            "Body"
        ].read().decode("utf-8")

        job_text = message["job_text"]

        resume_hash = hashlib.sha256(
            resume_text.encode("utf-8")
        ).hexdigest()

        cache_response = resume_cache_table.get_item(
            Key={
                "resume_hash": resume_hash
            }
        )

        cached_item = cache_response.get(
            "Item"
        )

        cached_resume_analysis = None

        if cached_item:

            print("Resume cache HIT")

            cached_resume_analysis = ResumeAnalysis(
                **cached_item[
                    "resume_analysis"
                ]
            )

        else:

            print("Resume cache MISS")


        try:

            result = match_job(
                resume_text,
                job_text,
                resume_analysis=cached_resume_analysis
            )

            if job_title:
                result["job_title"] = job_title

            if company:
                result["company"] = company

            result["source"] = source
            result["url"] = job_url

            # Trusted ingestion adapters may preserve a requirement that lives
            # outside the portal's main job-description section.
            if message.get("requires_cover_letter"):
                result["requires_cover_letter"] = True
                result["cover_letter_evidence"] = message.get(
                    "cover_letter_evidence",
                    result.get("cover_letter_evidence", "")
                )

            if (
                result.get("recommendation") == "APPLY"
                and result.get("requires_cover_letter")
            ):
                try:
                    result["cover_letter"] = generate_cover_letter(
                        resume_text,
                        job_text,
                        result.get("job_title", job_title),
                        result.get("company", company)
                    )
                except Exception as cover_letter_error:
                    print(
                        "Cover letter generation failed:",
                        cover_letter_error
                    )
                    result["cover_letter"] = ""


            if not cached_item:

                print(
                    "Saving resume analysis to cache"
                )

                resume_cache_table.put_item(
                    Item={
                        "resume_hash": resume_hash,
                        "resume_analysis":
                            result[
                                "resume_analysis"
                            ]
                    }
                )


            result.pop(
                "resume_analysis",
                None
            )


            table.update_item(
                Key={
                    "job_id": job_id
                },

                UpdateExpression="""
                    SET #status = :status,
                        job_title = :job_title,
                        company = :company,
                        recommendation = :recommendation,
                        technical_match = :technical_match,
                        experience_match = :experience_match,
                        matched_skills = :matched_skills,
                        partial_skills = :partial_skills,
                        missing_skills = :missing_skills,
                        category_scores = :category_scores,
                        family_scores = :family_scores,
                        reasons = :reasons,
                        missing_hard_requirements = :missing_hard_requirements,
                        missing_strong_requirements = :missing_strong_requirements,
                        #source = :source,
                        job_url = :job_url,
                        requires_cover_letter = :requires_cover_letter,
                        cover_letter_evidence = :cover_letter_evidence,
                        cover_letter = :cover_letter
                """,

                ExpressionAttributeNames={
                    "#status": "status",
                    "#source": "source"
                },

                ExpressionAttributeValues={
                    ":status": "DONE",

                    ":job_title": result.get(
                        "job_title",
                        ""
                    ),

                    ":company": result.get(
                        "company",
                        ""
                    ),

                    ":recommendation": result.get(
                        "recommendation",
                        ""
                    ),

                    ":technical_match": str(
                        result.get(
                            "technical_match",
                            0
                        )
                    ),

                    ":experience_match": str(
                        result.get(
                            "experience_match",
                            0
                        )
                    ),

                    ":category_scores": {
                        key: str(value)
                        for key, value in result.get(
                            "category_scores",
                            {}
                        ).items()
                    },

                    ":family_scores": {
                        key: str(value)
                        for key, value in result.get(
                            "family_scores",
                            {}
                        ).items()
                    },

                    ":matched_skills": result.get(
                        "matched_skills",
                        []
                    ),

                    ":partial_skills": result.get(
                        "partial_skills",
                        []
                    ),

                    ":missing_skills": result.get(
                        "missing_skills",
                        []
                    ),

                    ":reasons": result.get(
                        "reasons",
                        []
                    ),

                    ":missing_hard_requirements": result.get(
                        "missing_hard_requirements",
                        []
                    ),

                    ":missing_strong_requirements": result.get(
                        "missing_strong_requirements",
                        []
                    ),

                    ":source": result.get("source", ""),
                    ":job_url": result.get("url", ""),
                    ":requires_cover_letter": result.get(
                        "requires_cover_letter",
                        False
                    ),
                    ":cover_letter_evidence": result.get(
                        "cover_letter_evidence",
                        ""
                    ),
                    ":cover_letter": result.get("cover_letter", "")
                }
            )


            if result.get("recommendation") == "APPLY":

                try:

                    if result.get("cover_letter"):
                        send_telegram_cover_letter_pdf(result)
                    else:
                        send_telegram_message(result)

                except Exception as telegram_error:

                    print(
                        "Telegram notification failed:",
                        telegram_error
                    )


        except Exception as error:

            print(
                f"Job {job_id} failed: {error}"
            )

            table.update_item(
                Key={
                    "job_id": job_id
                },

                UpdateExpression="""
                    SET #status = :status,
                        error_message = :error_message
                """,

                ExpressionAttributeNames={
                    "#status": "status"
                },

                ExpressionAttributeValues={
                    ":status": "FAILED",
                    ":error_message": str(error)
                }
            )

            raise
