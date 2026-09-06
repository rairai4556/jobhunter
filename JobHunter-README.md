# JobHunter --- AI-Assisted Job Matching on AWS

JobHunter is a serverless job-matching project that analyzes a job
posting against a resume, uses AI to extract structured requirements and
resume evidence, and then uses deterministic Python logic to calculate a
match score and return an `APPLY`, `STRETCH`, or `SKIP` recommendation.

> **Current status:** The local matcher is complete, the full matcher
> runs successfully in AWS Lambda, the OpenAI API key is securely
> retrieved from AWS Systems Manager Parameter Store, and the API
> Gateway HTTP API phase is in progress.

## Core Design

The main design principle is:

> **AI interprets. Python decides.**

AI converts unstructured resume/job text into structured evidence.
Python performs scoring, experience calculations, transferable-credit
calculations, and the final recommendation.

## Current Architecture

``` text
Resume + Job Posting
        |
        v
   AWS Lambda
        |
        +--------------------------+
        |                          |
        v                          v
SSM Parameter Store           OpenAI API
(OpenAI API key)                   |
                                   v
                     Job + Resume Extraction
                                   |
                                   v
                        Deterministic Matcher
                                   |
                                   v
                        APPLY / STRETCH / SKIP
```

The API architecture currently being built is:

``` text
Client
  |
  | POST /match
  v
API Gateway
  |
  v
AWS Lambda
  |
  +--> SSM Parameter Store
  +--> OpenAI
  |
  v
JobHunter Matcher
```

The longer-term target is:

``` text
Job + Resume
     |
     v
API Gateway
     |
     v
Lambda
  |    |     |
  v    v     v
OpenAI S3  DynamoDB
     |
     v
CloudWatch / Automation / Notifications
```

No VPC is required for the initial serverless version.

## Technologies

-   Python
-   OpenAI API
-   Pydantic
-   Terraform
-   AWS Lambda
-   AWS IAM
-   AWS Systems Manager Parameter Store
-   AWS API Gateway
-   AWS CloudWatch
-   AWS CLI / SSO
-   PowerShell
-   Git / GitHub

Planned: DynamoDB, S3, EventBridge, and notifications.

## Project Structure

``` text
jobhunter/
├── .env
├── job.md
├── job.txt
├── resume.md
├── resume.txt
├── lambda_app/
│   ├── ai_extractor.py
│   ├── lambda_function.py
│   ├── matcher.py
│   ├── requirements.txt
│   ├── resume_extractor.py
│   └── skills.py
├── lambda_package/
│   ├── application .py files
│   ├── openai/
│   ├── pydantic/
│   ├── pydantic_core/
│   └── other Linux-compatible dependencies
└── terraform/
    ├── main.tf
    ├── jobhunter_lambda.zip
    ├── payload.json
    └── response.json
```

`lambda_app/` is the source of truth. Code is edited there.

`lambda_package/` is the Linux-compatible AWS deployment build. Source
files are copied into it before Terraform packages and deploys Lambda.

## 1. Local Matcher

The project began as a local Python matcher taking resume text and
job-posting text.

It evolved from basic keyword matching into a system that understands
requirement strength, resume evidence strength, skill families,
transferable knowledge, professional experience, and relevant projects.

## 2. Skill Vocabulary

`skills.py` contains standardized technical skills such as AWS,
Terraform, Docker, Kubernetes, ECS, Fargate, EC2, Lambda, S3, IAM, RDS,
EKS, CloudWatch, CloudTrail, Route 53, Git, GitHub Actions, CI/CD,
Linux, shell scripting, Python, Ansible, Chef, Puppet, microservices,
and networking.

Each skill can contain a weight, category, family, and matching terms.

Chef terms were made specific (`chef infra`,
`chef configuration management`, `chef automation`) to prevent unrelated
words such as the Eco-Chef project name from creating false matches.

## 3. AI Job Extraction

`ai_extractor.py` uses structured OpenAI output to extract:

-   job title
-   required years of experience
-   required skills
-   preferred skills
-   mentioned skills
-   other requirements

Requirement strengths are:

``` text
HARD_REQUIREMENT
STRONG_REQUIREMENT
FAMILIARITY
EXAMPLE
PREFERRED
MENTIONED
```

The extractor validates skills against the known vocabulary and
de-duplicates results, with required classifications taking precedence
over preferred or mentioned classifications.

## 4. AI Resume Extraction

`resume_extractor.py` separately analyzes the resume.

Evidence types are:

``` text
PROFESSIONAL
PROJECT
EDUCATION
SKILLS_SECTION
```

A technology merely listed in a skills section is intentionally weaker
evidence than technology demonstrated in professional work or a project.

The extractor avoids unsupported inference:

``` text
EC2 != Linux
AWS != Lambda
Docker != Kubernetes
Terraform != Ansible
EC2 != ECS
Kubernetes != EKS
```

Concrete infrastructure such as VPCs, subnets, routes, gateways, and
security groups can still support an abstract skill such as networking.

## 5. Deterministic Scoring

The AI does not calculate the final score.

Requirement multipliers:

``` python
STRENGTH_MULTIPLIERS = {
    "HARD_REQUIREMENT": 3.0,
    "STRONG_REQUIREMENT": 2.5,
    "FAMILIARITY": 1.5,
    "EXAMPLE": 0.75,
    "PREFERRED": 1.5,
    "MENTIONED": 1.0
}
```

Resume evidence multipliers:

``` python
RESUME_EVIDENCE_MULTIPLIERS = {
    "PROFESSIONAL": 1.0,
    "PROJECT": 1.0,
    "EDUCATION": 0.65,
    "SKILLS_SECTION": 0.40
}
```

Transferable credit between related skill-family members is capped at:

``` python
MAX_TRANSFERABLE_CREDIT = 0.30
```

This allows related knowledge to help without pretending it is
equivalent to direct experience.

## 6. Experience Calculation

AI extracts role dates and relevance. Python calculates the duration.

Projects do not count as professional years.

The matcher calculates an experience-match percentage against the job's
required years. Jobs requiring zero years receive a 100% experience
match.

A future improvement is to merge overlapping relevant professional date
intervals before summing them.

## 7. Recommendation Engine

JobHunter returns:

``` text
APPLY
STRETCH
SKIP
```

The decision considers technical match, hard requirements, strong
requirements, professional experience, experience gap, and relevant
project experience.

A low technical score combined with missing hard requirements and a
large experience gap can result in `SKIP`.

A sufficiently strong technical match with no missing hard requirements
and sufficient experience can result in `APPLY`.

Intermediate cases become `STRETCH`.

## 8. Lambda Refactor

The original matcher ran when imported. It was refactored so the
application logic lives in:

``` python
match_job(resume_text, job_text)
```

Local execution remains behind:

``` python
if __name__ == "__main__":
```

Import safety was verified with:

``` powershell
python -c "import matcher; print('matcher imported successfully')"
```

## 9. Terraform Lambda Deployment

Terraform uses AWS and Archive providers.

``` hcl
provider "aws" {
  region  = "us-east-2"
  profile = "terraform-sso"
}
```

The deployment directory is archived with:

``` hcl
data "archive_file" "jobhunter_lambda_zip" {
  type        = "zip"
  source_dir  = "../lambda_package"
  output_path = "jobhunter_lambda.zip"
}
```

The Lambda is configured as Python 3.13 with 512 MB memory and a
60-second timeout.

`source_code_hash` is used so Terraform detects package changes.

## 10. IAM

A dedicated role named `jobhunter-lambda-role` allows the Lambda service
to assume it.

`AWSLambdaBasicExecutionRole` is attached for basic Lambda/CloudWatch
logging.

An additional narrowly scoped inline policy permits:

``` text
ssm:GetParameter
```

for only:

``` text
/jobhunter/openai-api-key
```

The IAM policy-language version is correctly set to:

``` text
2012-10-17
```

An earlier incorrect policy version caused `MalformedPolicyDocument` and
was corrected.

## 11. Secure OpenAI API Key

The OpenAI API key is not hard-coded and is not stored in Terraform.

It is stored in AWS Systems Manager Parameter Store as a `SecureString`:

``` text
/jobhunter/openai-api-key
```

The AI modules use a runtime helper that:

1.  loads `.env` for local development;
2.  checks `OPENAI_API_KEY`;
3.  if missing, requests the SecureString from SSM;
4.  creates the OpenAI client.

This lets the same code run locally and in Lambda without putting the
secret in source control or Terraform state.

## 12. Windows/Linux Packaging Fix

Development happens on Windows, while Lambda runs on Linux.

Installing deployment dependencies directly into the source folder
caused a native `pydantic_core` error because Windows and Linux binary
packages are different.

The solution was to separate clean source from the deployment build and
install Linux-compatible wheels into `lambda_package/`:

``` powershell
pip install `
  --platform manylinux2014_x86_64 `
  --implementation cp `
  --python-version 3.13 `
  --only-binary=:all: `
  --target . `
  -r ..\lambda_app\requirements.txt
```

Updated source files are synchronized with:

``` powershell
Copy-Item ..\lambda_app\*.py ..\lambda_package\ -Force
```

Deployment flow:

``` text
Edit lambda_app
      |
      v
Copy source to lambda_package
      |
      v
Terraform creates ZIP
      |
      v
Terraform updates Lambda
```

## 13. Successful Full AWS Test

The full matcher was successfully invoked in AWS with:

``` powershell
aws lambda invoke `
  --function-name jobhunter-lambda `
  --payload fileb://payload.json `
  --cli-binary-format raw-in-base64-out `
  response.json `
  --profile terraform-sso `
  --region us-east-2
```

AWS returned status code 200.

The test job produced approximately:

``` json
{
  "job_title": "AWS Devops Engineer",
  "recommendation": "SKIP",
  "technical_match": 39.9,
  "resume_evidence_score": 36.02,
  "transferable_credit": 3.41,
  "technical_recommendation": "WEAK TECHNICAL MATCH",
  "required_experience_years": 2,
  "professional_experience_years": 0.0,
  "experience_match": 0.0,
  "has_relevant_project": true
}
```

The complete response also contained matched, partial, and missing
skills; missing hard and strong requirements; category and family
scores; and deterministic reasons.

This proved the complete path:

``` text
Resume + Job
   |
   v
Lambda
   |
   +--> SSM API key retrieval
   |
   +--> OpenAI job extraction
   |
   +--> OpenAI resume extraction
   |
   v
Python matcher
   |
   v
Recommendation
```

## 14. Preparing for API Gateway

For an HTTP response, the Lambda result is serialized:

``` python
import json
```

``` python
return {
    "statusCode": 200,
    "body": json.dumps(result)
}
```

This converts the Python dictionary into JSON text suitable for an HTTP
response.

## 15. API Gateway --- Current Phase

API Gateway v2 HTTP API is being used.

The first API resource is:

``` hcl
resource "aws_apigatewayv2_api" "jobhunter_api" {
  name          = "jobhunter-api"
  protocol_type = "HTTP"
}
```

The API itself has been added. The remaining pieces will connect
requests to Lambda:

``` text
HTTP API
   |
   +--> Lambda Integration
   +--> POST /match Route
   +--> $default Stage
   +--> Lambda Invoke Permission
```

The Lambda handler will also need to normalize API Gateway's HTTP event
format, because posted JSON arrives inside `event["body"]`.

## Security Notes

-   Never commit `.env`.
-   Never commit or print the OpenAI API key.
-   The OpenAI secret is stored as an SSM SecureString.
-   Lambda uses least-privilege SSM access.
-   AWS access uses the configured SSO profile.
-   Before broadly exposing the HTTP endpoint, add suitable protection
    against abuse because requests can generate OpenAI API costs.

## Current Progress

  Component                       Status
  ------------------------------- ----------------
  Local matcher                   ✅ Complete
  Skill vocabulary                ✅ Complete
  AI job extractor                ✅ Complete
  AI resume extractor             ✅ Complete
  Deterministic scoring           ✅ Complete
  Experience scoring              ✅ Complete
  APPLY / STRETCH / SKIP engine   ✅ Complete
  Lambda-safe refactor            ✅ Complete
  Terraform Lambda deployment     ✅ Complete
  Linux dependency packaging      ✅ Complete
  IAM execution role              ✅ Complete
  SSM SecureString                ✅ Complete
  Lambda SSM permission           ✅ Complete
  OpenAI calls from Lambda        ✅ Complete
  Full end-to-end AWS test        ✅ Complete
  API-compatible JSON response    ✅ Complete
  API Gateway HTTP API            🚧 In progress
  Lambda integration              ⏭️ Next
  `POST /match` route             ⏳ Planned
  API stage                       ⏳ Planned
  Lambda invoke permission        ⏳ Planned
  DynamoDB                        ⏳ Planned
  S3                              ⏳ Planned
  Automation / notifications      ⏳ Planned

## Roadmap

``` text
1. Local matcher                         DONE
2. Tiny Lambda locally                   DONE
3. Deploy Lambda with Terraform          DONE
4. Pass event data into Lambda           DONE
5. Refactor matcher into function        DONE
6. Run JobHunter logic in Lambda         DONE
7. Secure OpenAI key with SSM            DONE
8. Build HTTP API                        IN PROGRESS
9. Store results in DynamoDB
10. Store/manage resume with S3
11. Add automation and notifications
```

## Future Vision

``` text
Indeed / TMU Co-op / Other Sources
                 |
                 v
             JobHunter
                 |
          Resume + Job
                 |
                 v
          AI Extraction
                 |
                 v
       Deterministic Matcher
                 |
                 v
        APPLY / STRETCH / SKIP
                 |
                 v
       Store + Notify User
```

A future notification could look like:

``` text
New AWS role — 78% match
Recommendation: APPLY
```

Later versions could support multiple job sources, mobile review,
approval workflows, and assisted application preparation.

## What This Project Demonstrates

JobHunter is more than a wrapper around an AI API. It demonstrates:

-   Python application architecture
-   structured AI outputs
-   deterministic scoring and decision logic
-   AWS serverless computing
-   Lambda deployment
-   IAM and least privilege
-   secure secret management
-   infrastructure as code with Terraform
-   cross-platform dependency packaging
-   HTTP API design
-   cloud debugging
-   deployment workflows

The project is intentionally being built incrementally so each AWS
component is understood before the next one is introduced.
