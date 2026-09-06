import json
import boto3
import hashlib
import urllib.request
import urllib.parse
from matcher import match_job
from resume_extractor import ResumeAnalysis

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

def send_telegram_message(result):

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

    reasons = "\n".join(
        f"- {reason}"
        for reason in result.get("reasons", [])
    )

    message = (
        "🚀 JobHunter APPLY Match\n\n"
        f"Job: {result.get('job_title', '')}\n"
        f"Recommendation: {result.get('recommendation', '')}\n"
        f"Technical Match: {result.get('technical_match', 0)}%\n"
        f"Experience Match: {result.get('experience_match', 0)}%\n\n"
        f"Why:\n{reasons}"
    )

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message
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

def lambda_handler(event, context):
    print("JobHunter worker started")
    
    for record in event["Records"]:
        message = json.loads(record["body"])

        job_id = message["job_id"]
        resume_object = s3.get_object(
            Bucket=RESUME_BUCKET,
            Key=RESUME_KEY
        )

        resume_text = resume_object["Body"].read().decode("utf-8")
        job_text = message["job_text"]
        resume_hash = hashlib.sha256(
            resume_text.encode("utf-8")
        ).hexdigest()

        cache_response = resume_cache_table.get_item(
            Key={
                "resume_hash": resume_hash
            }
        )

        cached_item = cache_response.get("Item")
        cached_resume_analysis = None

        if cached_item:
            print("Resume cache HIT")

            cached_resume_analysis = ResumeAnalysis(
                **cached_item["resume_analysis"]
            )

        else:
            print("Resume cache MISS")
        
        

        try:
            result = match_job(
                resume_text,
                job_text,
                resume_analysis=cached_resume_analysis
            )

            if not cached_item:
                print("Saving resume analysis to cache")

                resume_cache_table.put_item(
                    Item={
                        "resume_hash": resume_hash,
                        "resume_analysis": result["resume_analysis"]
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
                        missing_strong_requirements = :missing_strong_requirements
                """,
                ExpressionAttributeNames={
                    "#status": "status"
                },
                ExpressionAttributeValues={
                    ":status": "DONE",
                    ":job_title": result.get("job_title", ""),
                    ":recommendation": result.get("recommendation", ""),
                    ":technical_match": str(
                        result.get("technical_match", 0)
                    ),
                    ":experience_match": str(
                        result.get("experience_match", 0)
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

                    ":missing_hard_requirements": result.get(
                        "missing_hard_requirements",
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

                    ":missing_strong_requirements": result.get(
                        "missing_strong_requirements",
                        []  
                    )
                    
                }
            )

            if result.get("recommendation") == "APPLY":
                try:
                    send_telegram_message(result)
                except Exception as telegram_error:
                    print(
                        "Telegram notification failed:",
                        telegram_error
                    )
        except Exception as error:
            print(f"Job {job_id} failed: {error}")

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