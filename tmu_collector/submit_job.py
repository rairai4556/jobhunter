import json
import subprocess
import urllib.request


TMU_ENDPOINT = "https://t0r6wiqif4.execute-api.us-east-2.amazonaws.com/tmu-jobs"

def get_ingest_key():
    result = subprocess.run(
        [
            "aws",
            "ssm",
            "get-parameter",
            "--name",
            "/jobhunter/tmu-ingest-key",
            "--with-decryption",
            "--query",
            "Parameter.Value",
            "--output",
            "text",
            "--profile",
            "terraform-sso",
            "--region",
            "us-east-2"
        ],
        capture_output=True,
        text=True,
        check=True
    )

    return result.stdout.strip()


def submit_job(job):
    ingest_key = get_ingest_key()

    body = json.dumps(job).encode("utf-8")

    request = urllib.request.Request(
        TMU_ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-jobhunter-key": ingest_key
        },
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(
            response.read().decode("utf-8")
        )