# JobHunter — Complete Project History, Architecture, Mistakes, Fixes, and Current State

> **Project:** JobHunter — Serverless AI Job Matching / Job Discovery System  
> **AWS Region:** `us-east-2` (Ohio)  
> **IaC:** Terraform  
> **Primary language:** Python 3.13  
> **Status:** JobHunter v1 is complete and working end-to-end. The system automatically fetches real jobs from Remotive once per day through EventBridge, filters and deduplicates them, sends up to 5 new relevant jobs through SQS to the worker Lambda, loads the resume from S3, reuses cached resume analysis, scores each job, stores results in DynamoDB, monitors failures with CloudWatch/SNS, and sends a Telegram notification when the final recommendation is `APPLY`.

---

# 1. Why I Built JobHunter

JobHunter started as an idea for reducing the amount of time spent manually reading job postings and deciding whether they were worth applying to.

The goal gradually became:

1. Accept a resume and job posting.
2. Extract job requirements with AI.
3. Extract evidence from the resume with AI.
4. Score the candidate against the posting.
5. Return an `APPLY`, `STRETCH`, or `SKIP` recommendation.
6. Run the expensive matching work asynchronously.
7. Store results so they can be retrieved later.
8. Avoid re-analyzing the same resume repeatedly.
9. Monitor failures and alert by email.
10. Automatically fetch jobs.
11. Avoid processing the same posting more than once.
12. Eventually run automatically on a schedule.

This project became much more than a matcher. It now combines application code, AI integration, Infrastructure as Code, event-driven architecture, queues, serverless compute, persistent state, observability, alerting, caching, and job-ingestion design.

---

# 2. Architecture — Current High-Level Design


JobHunter now has two entry paths that converge on the same asynchronous worker pipeline.

The first is the manual API path:

```text
User / Client
    │
    ▼
API Gateway HTTP API
    │
    ├── POST /match
    │       │
    │       ▼
    │  API Lambda
    │       │
    │       ├── create job_id
    │       ├── write PROCESSING record
    │       └── send work to SQS
    │
    └── GET /results/{job_id}
            │
            ▼
       API Lambda
            │
            ▼
    jobhunter-results
```

The second is the fully automated discovery path:

```text
EventBridge schedule
     rate(1 day)
         │
         ▼
jobhunter-fetcher Lambda
         │
         ▼
Remotive public job API
         │
         ▼
normalize posting
         │
         ├── duplicate? ──> skip
         │
         ├── irrelevant title? ──> skip
         │
         └── new relevant job
                    │
                    ▼
              create job_id
                    │
                    ▼
            PROCESSING result
                    │
                    ▼
             SQS Match Queue
                    │
                    ▼
             Worker Lambda
                    │
          ┌─────────┼──────────┐
          ▼         ▼          ▼
      S3 Resume  Resume      OpenAI
                 Cache       job analysis
          │         │          │
          └─────────┴──────────┘
                    │
                    ▼
               Matcher
                    │
                    ▼
        APPLY / STRETCH / SKIP
                    │
                    ▼
            jobhunter-results
                    │
             recommendation
                == APPLY?
               /       \
             no         yes
             │           │
           finish     Telegram
```

The worker loads the resume from:

```text
S3 bucket: jobhunter-resume-storage
object:    resume.txt
```

It hashes the resume and checks:

```text
jobhunter-resume-cache
```

so the same resume is not re-analyzed for every job.

The fetcher uses:

```text
jobhunter-seen-jobs
```

for idempotent duplicate detection.

Monitoring currently includes:

```text
Worker Lambda Errors ──────────────┐
Fetcher Lambda Errors ─────────────┼──> CloudWatch Alarms
DLQ Visible Messages ──────────────┘
                                          │
                                          ▼
                                      SNS Topic
                                          │
                                          ▼
                                         Email
```

Application-level good-match notifications are separate:

```text
Recommendation == APPLY
        │
        ▼
Telegram Bot API
        │
        ▼
Telegram message
```

# 3. Phase 1 — Original Local Matcher

The first version ran locally and used a hand-maintained skill dictionary.

Initial skills included things such as:

- AWS
- Terraform
- Docker
- Linux
- Python
- Kubernetes

The matcher originally looked for keywords and calculated a simple percentage.

Early output looked similar to:

```text
Match: 0%
Recommendation: SKIP
```

This was useful for proving the idea, but it was too simplistic.

## Improvements made

The matcher was upgraded to support:

- Regex/term matching
- Weighted skills
- Skill aliases
- Required vs preferred vs mentioned skills
- Category scoring
- Skill-family scoring
- Evidence strength
- Transferable credit
- Experience requirements
- Relevant project detection
- Final decision rules

The skill dictionary eventually covered areas such as:

- AWS core services
- Terraform
- Docker
- Kubernetes
- ECS
- Fargate
- EC2
- Lambda
- S3
- IAM
- RDS
- EKS
- CloudWatch
- CloudTrail
- Route 53
- Git
- GitHub Actions
- CI/CD
- shell scripting
- Ansible
- Chef
- Puppet
- microservices
- networking

---

# 4. Phase 2 — AI Job Requirement Extraction

A dedicated AI extractor was added so the program no longer had to rely only on manually parsing job text.

The AI extractor identifies:

- Job title
- Required years of experience
- Required skills
- Preferred skills
- Mentioned technologies
- Strength of each requirement
- Reason for the classification
- Supporting evidence from the posting
- Other job requirements

Requirement-strength categories used by the matcher include:

```text
HARD_REQUIREMENT
STRONG_REQUIREMENT
FAMILIARITY
EXAMPLE
PREFERRED
MENTIONED
```

The matcher assigns different multipliers to these levels.

Example:

```python
STRENGTH_MULTIPLIERS = {
    "HARD_REQUIREMENT": 3.0,
    "STRONG_REQUIREMENT": 2.5,
    "FAMILIARITY": 1.5,
    "EXAMPLE": 0.75,
    "PREFERRED": 1.5,
    "MENTIONED": 1.0
}
```

This made the score much more realistic than treating every word in a posting as equally important.

---

# 5. Phase 3 — AI Resume Evidence Extraction

A second AI extractor analyzes the resume.

Instead of simply asking whether a word exists, it identifies how strongly the resume actually demonstrates a skill.

Resume evidence types:

```text
PROFESSIONAL
PROJECT
EDUCATION
SKILLS_SECTION
```

Current evidence multipliers:

```python
RESUME_EVIDENCE_MULTIPLIERS = {
    "PROFESSIONAL": 1.0,
    "PROJECT": 1.0,
    "EDUCATION": 0.65,
    "SKILLS_SECTION": 0.40
}
```

This distinction matters.

For example:

```text
Docker listed under Skills
```

does not receive the same credit as:

```text
Built and deployed a containerized application with Docker.
```

The current matcher can therefore distinguish:

- demonstrated skill
- partial evidence
- missing skill

---

# 6. Matcher Scoring System

The scoring system became one of the most detailed parts of the project.

For each job skill:

```text
base skill weight
        ×
job requirement strength
        ×
resume evidence strength
        =
earned points
```

The matcher tracks:

- total available points
- earned points
- category totals
- category matches
- family totals
- family matches

It calculates:

```text
Resume evidence score
Adjusted technical score
Experience match
Technical recommendation
Final recommendation
```

---

# 7. Transferable Skill Credit

A transferable-credit system was added so related experience can give a small amount of credit for missing technologies.

Current cap:

```python
MAX_TRANSFERABLE_CREDIT = 0.30
```

Example:

```text
Strong AWS experience
    ↓
small transferable credit toward a missing AWS service
```

This does **not** convert a missing requirement into a full match.

It only prevents the score from acting as though related experience is completely worthless.

Example observed transferable credits included small amounts for:

- Kubernetes
- microservices
- shell scripting
- CloudWatch
- CloudTrail
- ECS
- EKS
- Lambda
- RDS
- Route 53
- Ansible
- Chef
- Puppet
- Fargate

---

# 8. Professional Experience Matching

The matcher extracts relevant Cloud/DevOps professional roles and parses dates such as:

```text
Jan 2025
January 2025
Present
Current
```

It converts role duration into months and then years.

Example logic:

```text
required experience: 2 years
relevant professional experience: 0 years
experience match: 0%
```

Relevant projects are tracked separately so project experience can strengthen an application without pretending it is professional employment.

---

# 9. Final Recommendation Engine

The current output uses:

```text
APPLY
STRETCH
SKIP
```

A `SKIP` can occur when all of these are true:

- technical score is below 50%
- at least one hard requirement is missing
- professional experience gap is at least 2 years

An `APPLY` can occur when:

- technical match is strong
- there are no missing hard requirements
- professional experience is close to the requirement

A separate entry-level rule exists for jobs requiring no prior experience.

Everything else generally becomes `STRETCH`.

---

# 10. First AWS Serverless Version

The project was then moved from a local Python program into AWS.

The first serverless path was:

```text
Client
  │
  ▼
API Gateway HTTP API
  │
  ▼
Lambda
  │
  ▼
AI matcher
```

Terraform manages the infrastructure.

Main API route:

```text
POST /match
```

The API Gateway integration uses:

```text
AWS_PROXY
payload format version 2.0
```

The API Lambda handler is:

```text
lambda_function.lambda_handler
```

Runtime:

```text
Python 3.13
```

---

# 11. Major Problem — HTTP API Body Parsing

## What went wrong

The first Lambda expected fields directly from the Lambda event:

```python
event.get("resume_text")
event.get("job_text")
```

But API Gateway HTTP API sends the actual JSON request inside:

```python
event["body"]
```

and the body may be a JSON string.

This caused failures including:

```text
Internal Server Error
```

## Fix

The handler was changed to:

```python
body = event.get("body", event)

if isinstance(body, str):
    body = json.loads(body)
```

Then another validation layer was added:

```python
if not isinstance(body, dict):
    return {
        "statusCode": 400,
        "body": json.dumps({
            "message": "Request body must be a JSON object"
        })
    }
```

## Validation tests

Malformed JSON:

```text
{"resume_text": "hello",
```

Correct response:

```text
Invalid JSON body
```

JSON array instead of object:

```json
["resume", "job"]
```

Correct response:

```text
Request body must be a JSON object
```

Missing job:

```json
{"resume_text":"hello"}
```

Correct response:

```text
Missing job_text
```

Missing resume:

```json
{"job_text":"hello"}
```

Correct response:

```text
Missing resume_text
```

### What I learned

API Gateway events are not the same thing as the JSON body the client sends.

The Lambda must understand the event envelope produced by the integration.

---

# 12. Async Architecture — SQS + Worker Lambda

Running the full AI match inside the API Lambda was not ideal because AI requests can take many seconds.

The architecture was redesigned to be asynchronous.

Current flow:

```text
POST /match
      │
      ▼
API Lambda
      │
      ├── create job_id
      ├── write PROCESSING record
      └── send request to SQS
                 │
                 ▼
           Worker Lambda
                 │
                 ├── AI analysis
                 ├── matcher
                 └── update DynamoDB
```

The API can now respond immediately:

```json
{
  "job_id": "...",
  "status": "PROCESSING"
}
```

with HTTP:

```text
202 Accepted
```

---

# 13. DynamoDB Results Table

Table:

```text
jobhunter-results
```

Primary key:

```text
job_id
```

Billing mode:

```text
PAY_PER_REQUEST
```

A TTL field was added:

```text
expires_at
```

Results expire after approximately 7 days.

Stored output includes fields such as:

- job title
- status
- recommendation
- technical match
- experience match
- matched skills
- partial skills
- missing skills
- missing hard requirements
- missing strong requirements
- category scores
- family scores
- reasons
- timestamps

A real successful DynamoDB result showed:

```text
status: DONE
recommendation: SKIP
technical_match: 43.55
```

with missing hard requirements such as:

```text
kubernetes
microservices
```

---

# 14. Results Retrieval Endpoint

A second API route was added:

```text
GET /results/{job_id}
```

The same API Lambda handles both routes.

The Lambda checks:

```python
route_key = event.get("routeKey", "")
```

For results:

```text
GET /results/{job_id}
        │
        ▼
DynamoDB GetItem
```

Possible responses:

```text
200 -> result exists
400 -> missing job_id
404 -> result not found
```

---

# 15. SQS Match Queue

Queue:

```text
jobhunter-match-queue
```

Important settings:

```text
visibility_timeout_seconds = 360
message_retention_seconds  = 86400
```

The API Lambda only needs:

```text
sqs:SendMessage
```

The worker needs:

```text
sqs:ReceiveMessage
sqs:DeleteMessage
sqs:GetQueueAttributes
```

The worker is connected to SQS through:

```text
aws_lambda_event_source_mapping
```

with:

```text
batch_size = 1
```

This gives one job message to the worker at a time.

---

# 16. Dead-Letter Queue

A DLQ was added:

```text
jobhunter-match-dlq
```

Retention:

```text
1209600 seconds
```

which is 14 days.

Main queue redrive configuration:

```text
maxReceiveCount = 3
```

Meaning:

```text
Worker fails message
      ↓
SQS retries
      ↓
fails enough times
      ↓
message goes to DLQ
```

This prevents poison messages from retrying forever.

---

# 17. CloudWatch Monitoring

Two CloudWatch metric alarms were added.

## Worker Lambda error alarm

```text
jobhunter-worker-errors
```

Metric:

```text
AWS/Lambda
Errors
```

Configuration:

```text
Statistic: Sum
Period: 60 seconds
Evaluation periods: 1
Threshold: >= 1
```

Meaning:

```text
If at least one worker Lambda error occurs during a one-minute evaluation period,
the alarm can enter ALARM state.
```

## DLQ message alarm

```text
jobhunter-dlq-messages
```

Metric:

```text
AWS/SQS
ApproximateNumberOfMessagesVisible
```

Configuration:

```text
Statistic: Maximum
Period: 60 seconds
Evaluation periods: 1
Threshold: >= 1
```

A confirmed healthy state looked like:

```text
StateValue: OK
recent datapoint: 0
threshold: 1
```

---

# 18. SNS Email Alerts

SNS topic:

```text
jobhunter-alerts
```

Both CloudWatch alarms point their `alarm_actions` at this topic.

An email subscription was created.

## Problem — subscription kept becoming unsubscribed/deleted

During setup, the subscription appeared as:

```text
PendingConfirmation
```

and at one point:

```text
SubscriptionArn: Deleted
```

Terraform itself showed:

```text
No changes. Your infrastructure matches the configuration.
```

Eventually a new confirmation was completed and SNS showed a real subscription ARN.

### Lesson

Email SNS subscriptions require confirmation by the recipient.

Terraform can create the subscription request, but the user still has to confirm the email subscription outside Terraform.

---

# 19. SSM Parameter Store for OpenAI API Key

The worker retrieves the OpenAI API key from Systems Manager Parameter Store rather than hardcoding it into Python.

Parameter path:

```text
/jobhunter/openai-api-key
```

Worker IAM permission:

```text
ssm:GetParameter
```

limited to that parameter.

This keeps the secret out of source code and Git.

---

# 20. Separate API and Worker IAM Roles

The project uses separate roles instead of giving every Lambda the same broad permissions.

```text
jobhunter-lambda-role
    ├── CloudWatch logging
    ├── DynamoDB PutItem/GetItem on jobhunter-results
    └── SQS SendMessage

jobhunter-worker-role
    ├── CloudWatch logging
    ├── SQS Receive/Delete/GetAttributes
    ├── DynamoDB UpdateItem on jobhunter-results
    ├── DynamoDB resume-cache access
    └── SSM GetParameter

jobhunter-fetcher-role
    ├── CloudWatch logging
    ├── SQS SendMessage
    └── DynamoDB GetItem/PutItem on jobhunter-seen-jobs
```

This follows least-privilege principles much better than giving every function administrator permissions.

---

# 21. Resume Analysis Cache

One of the biggest optimizations was caching the AI resume analysis.

Without caching:

```text
Job 1
  -> analyze resume with AI
  -> analyze job with AI

Job 2
  -> analyze resume with AI AGAIN
  -> analyze job with AI AGAIN
```

This wastes money and time because the resume usually does not change between job applications.

A DynamoDB table was added:

```text
jobhunter-resume-cache
```

Primary key:

```text
resume_hash
```

The resume text is hashed.

Flow:

```text
Resume
  │
  ▼
hash resume text
  │
  ▼
DynamoDB lookup
  │
  ├── cache HIT -> use stored resume analysis
  │
  └── cache MISS -> call AI -> save result
```

Observed logs:

First run:

```text
Resume cache MISS
Analyzing job and resume with AI...
Resume analysis took 19.62 seconds
Job analysis took 23.43 seconds
Saving resume analysis to cache
```

Second run:

```text
Resume cache HIT
Using cached resume analysis.
Analyzing job with AI...
Job analysis took 19.84 seconds
```

This proved the optimization worked.

---

# 22. Concurrent AI Analysis

The matcher imports:

```python
ThreadPoolExecutor
```

and the worker was designed so job and resume analysis could be done concurrently when a cache miss requires both.

Observed first-run timings demonstrated the two AI operations happening in the same overall worker request rather than purely serial end-to-end processing.

---

# 23. Token Usage Logging

Token logging was added directly after each OpenAI response.

Job extractor:

```python
print("JOB TOKEN USAGE")
print("Input tokens:", response.usage.input_tokens)
print("Output tokens:", response.usage.output_tokens)
print("Total tokens:", response.usage.total_tokens)
```

Resume extractor uses the same pattern with:

```text
RESUME TOKEN USAGE
```

## Actual measured cached-job usage

A real worker invocation logged:

```text
JOB TOKEN USAGE
Input tokens: 2451
Output tokens: 2000
Total tokens: 4451
```

Because the resume was cached, only the job analyzer consumed AI tokens in that request.

This is useful because future cost calculations can use measured usage instead of guesses.

---

# 24. Worker Performance Observed

A cache-miss worker invocation:

```text
Duration: ~24.27 seconds
Billed Duration: ~27.20 seconds
Memory: 512 MB
Max Memory Used: ~195 MB
```

A cache-hit invocation:

```text
Duration: ~20.03 seconds
Billed Duration: ~20.03 seconds
Memory: 512 MB
Max Memory Used: ~198 MB
```

A later token-logging invocation took around:

```text
26.47 seconds
```

with a cold-start initialization of around:

```text
2.88 seconds
```

The exact duration varies because the AI request latency varies.

---

# 25. Worker Output Example

For the AWS DevOps Engineer test posting, the system correctly identified demonstrated skills such as:

```text
networking
terraform
git
aws
ec2
iam
```

Partial resume evidence included:

```text
docker
linux
s3
python
```

Major missing requirements included:

```text
kubernetes
microservices
github actions
ci/cd
shell scripting
cloudwatch
```

Example category scores:

```text
networking:       100%
devops_tools:     100%
aws_core:          92.5%
iac:               71.43%
os_scripting:      30.48%
containers:        13.33%
cicd:               0%
aws_observability:  0%
```

Final result:

```text
Recommendation: SKIP
Technical match: 39.9%
Experience match: 0%
Relevant Cloud/DevOps project: YES
```

Reasons:

```text
Technical match is below 50%.
At least one hard technical requirement is missing.
Professional experience is at least 2 years below the job requirement.
```

---

# 26. Source Folder / Packaging Confusion

## What went wrong

At one point, project files were being edited directly inside a Lambda package directory.

This created confusion about which directory was the real source of truth.

There was also confusion around files such as:

```text
typing_extensions.py
```

which had been packaged as dependencies rather than being application source code.

## Fix

The workflow was clarified:

```text
lambda_app/
    ↓ edit source here

lambda_worker_package/
    ↓ copy deployable files here

Terraform archive_file
    ↓

Lambda ZIP
```

For worker changes, the deployment flow became:

```text
edit source
  ↓
Copy-Item source -> lambda_worker_package
  ↓
terraform plan
  ↓
terraform apply
```

Example copy commands used:

```powershell
Copy-Item ..\lambda_app\ai_extractor.py ..\lambda_worker_package\ai_extractor.py -Force
Copy-Item ..\lambda_app\resume_extractor.py ..\lambda_worker_package\resume_extractor.py -Force
```

### Lesson

A clear source directory prevents accidental editing of generated/deployment artifacts.

---

# 27. Terraform ZIP Detection

Terraform uses the Archive provider:

```hcl
data "archive_file" "jobhunter_lambda_zip" {
  type        = "zip"
  source_dir  = "../lambda_api_package"
  output_path = "jobhunter_lambda.zip"
}
```

Equivalent blocks exist for the worker and fetcher.

Each Lambda uses:

```hcl
source_code_hash = data.archive_file.<name>.output_base64sha256
```

This lets Terraform detect when code changed.

Typical plan after code-only changes:

```text
~ aws_lambda_function.jobhunter_worker
Plan: 0 to add, 1 to change, 0 to destroy
```

---

# 28. Third Lambda — Job Fetcher

The next phase added:

```text
jobhunter-fetcher
```

Purpose:

```text
Automatically discover jobs
       ↓
normalize posting
       ↓
deduplicate
       ↓
eventually send new jobs to SQS
```

Fetcher configuration:

```text
Runtime: Python 3.13
Memory: 256 MB
Timeout: 60 seconds
Handler: fetcher_function.lambda_handler
```

Fetcher IAM role:

```text
jobhunter-fetcher-role
```

Permissions currently include:

- CloudWatch logs
- SQS `SendMessage`
- DynamoDB `GetItem`
- DynamoDB `PutItem`

---

# 29. Important Safety Decision — Do Not Trigger AI with a Fake Job

The first fetcher test code contained:

```python
test_message = {
    "job_id": "fetcher-test",
    "resume_text": "test resume",
    "job_text": "test job"
}
```

and sent it to the real match queue.

## Why that was a bad test

The real worker is subscribed to the queue.

So invoking the fetcher would have caused:

```text
Fetcher
   ↓
SQS
   ↓
Worker
   ↓
AI call on "test resume" and "test job"
```

That would waste an AI request.

## Fix

The fetcher was temporarily changed to a safe smoke test:

```python
def lambda_handler(event, context):
    print("JobHunter fetcher started")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Fetcher works"
        })
    }
```

Direct invocation returned:

```json
{
  "statusCode": 200,
  "body": "{\"message\": \"Fetcher works\"}"
}
```

This proved the Lambda itself worked before connecting it to real ingestion.

---

# 30. Seen-Jobs DynamoDB Table

A table was added for duplicate detection:

```text
jobhunter-seen-jobs
```

Primary key:

```text
job_key
```

Billing:

```text
PAY_PER_REQUEST
```

The fetcher creates a stable string:

```text
company | title | URL
```

then hashes it with SHA-256:

```python
job_key = hashlib.sha256(
    raw_key.encode("utf-8")
).hexdigest()
```

Example generated key:

```text
da618957a35eafea0b05bcaba77a39a0107d2ce470f7bbabc640557d47d29507
```

---

# 31. Major Problem — Fetcher DynamoDB AccessDenied

This was one of the most useful debugging incidents in the project.

## Symptom

The fetcher failed with:

```text
AccessDeniedException
```

AWS said:

```text
jobhunter-fetcher-role is not authorized to perform dynamodb:GetItem
on jobhunter-seen-jobs
because no identity-based policy allows the action
```

## First suspicion

The obvious possibilities were:

- policy not created
- wrong role
- wrong table ARN
- permissions boundary
- Terraform not applied
- IAM propagation delay

## Verification 1 — inspect inline policy

Command:

```powershell
aws iam get-role-policy `
  --role-name jobhunter-fetcher-role `
  --policy-name jobhunter-fetcher-seen-jobs-access `
  --profile terraform-sso
```

AWS showed:

```text
dynamodb:GetItem
dynamodb:PutItem
```

and the exact table ARN.

So the policy existed and was correct.

## Verification 2 — IAM policy simulator

Command:

```powershell
aws iam simulate-principal-policy `
  --policy-source-arn arn:aws:iam::<ACCOUNT_ID>:role/jobhunter-fetcher-role `
  --action-names dynamodb:GetItem `
  --resource-arns arn:aws:dynamodb:us-east-2:<ACCOUNT_ID>:table/jobhunter-seen-jobs `
  --profile terraform-sso
```

Result:

```text
EvalDecision: allowed
```

The matched statement was:

```text
jobhunter-fetcher-seen-jobs-access
```

## Verification 3 — confirm Lambda execution role

Command:

```powershell
aws lambda get-function-configuration `
  --function-name jobhunter-fetcher `
  --query Role `
  --output text `
  --profile terraform-sso `
  --region us-east-2
```

Result:

```text
arn:aws:iam::<ACCOUNT_ID>:role/jobhunter-fetcher-role
```

So the Lambda was using the correct role.

## Verification 4 — permissions boundary

`aws iam get-role` showed no permissions boundary.

## Root cause / practical fix

The Lambda execution environment was still operating with stale role credentials after the IAM permission change.

A trivial Lambda configuration update was used to force a fresh environment:

```powershell
aws lambda update-function-configuration `
  --function-name jobhunter-fetcher `
  --description "JobHunter fetcher with DynamoDB access" `
  --profile terraform-sso `
  --region us-east-2
```

Then:

```powershell
aws lambda wait function-updated `
  --function-name jobhunter-fetcher `
  --profile terraform-sso `
  --region us-east-2
```

After that, the same invocation succeeded:

```text
New job found
```

### What I learned

When IAM says a policy allows an action but a long-lived Lambda execution environment still receives `AccessDenied`, refreshing the Lambda configuration can force new execution credentials.

Also, always verify:

```text
policy
role
resource ARN
permissions boundary
actual execution role
```

instead of blindly rewriting IAM.

---

# 32. Terraform Drift Caused by Manual CLI Update

The manual Lambda description change solved the stale-credential issue, but created Terraform drift.

Terraform later showed:

```text
description = "JobHunter fetcher with DynamoDB access" -> null
```

Why?

Because the description was changed manually with the AWS CLI but was not present in `main.tf`.

Terraform correctly wanted to return AWS to the declared configuration.

### Lesson

Manual console/CLI changes are sometimes useful for diagnosis, but with IaC they can create drift.

After debugging, either:

- add the desired setting to Terraform, or
- let Terraform restore the declared state

---

# 33. Duplicate Job Detection Test

The fetcher originally only checked DynamoDB.

Then `PutItem` was added for newly discovered jobs.

New-job path:

```text
calculate hash
    ↓
GetItem
    ↓
not found
    ↓
PutItem
    ↓
save:
    job_key
    title
    company
    url
```

First invocation:

```json
{
  "message": "New job found",
  "job_key": "da618957..."
}
```

Second invocation with the identical job:

```json
{
  "message": "Duplicate job skipped"
}
```

This confirmed the deduplication mechanism works.

---

# 34. Current Terraform-Managed AWS Resources


The final Terraform-managed v1 stack includes the following major resources.

## API

```text
aws_apigatewayv2_api.jobhunter_api
aws_apigatewayv2_stage.jobhunter_stage
aws_apigatewayv2_integration.jobhunter_lambda_integration
aws_apigatewayv2_route.jobhunter_match_route
aws_apigatewayv2_route.jobhunter_results_route
```

Routes:

```text
POST /match
GET /results/{job_id}
```

## Lambda

```text
jobhunter-lambda
jobhunter-worker
jobhunter-fetcher
```

## IAM

Separate least-privilege execution roles exist for:

```text
API Lambda
Worker Lambda
Fetcher Lambda
```

The worker can read the specific SSM parameters used by JobHunter, including the OpenAI key and Telegram configuration.

## SQS

```text
jobhunter-match-queue
jobhunter-match-dlq
```

The main queue uses a 360-second visibility timeout and redrives failed messages to the DLQ after the configured receive limit.

## DynamoDB

```text
jobhunter-results
jobhunter-resume-cache
jobhunter-seen-jobs
```

`jobhunter-results` uses TTL through `expires_at`.

## S3

```text
jobhunter-resume-storage
└── resume.txt
```

The worker reads the resume from S3 instead of carrying the full resume in every SQS message.

## EventBridge

```text
aws_cloudwatch_event_rule.jobhunter_fetch_schedule
aws_cloudwatch_event_target.jobhunter_fetcher_target
aws_lambda_permission.allow_eventbridge_fetcher
```

Schedule:

```text
rate(1 day)
```

The rule was verified as:

```text
State: ENABLED
ScheduleExpression: rate(1 day)
```

and its target was verified as:

```text
jobhunter-fetcher
```

## Monitoring

```text
jobhunter-worker-errors
jobhunter-fetcher-errors
jobhunter-dlq-messages
```

## SNS

```text
jobhunter-alerts
```

The SNS email subscription is used for infrastructure/error alarms.

## SSM Parameter Store

The project uses parameters including:

```text
/jobhunter/openai-api-key
/jobhunter/telegram-bot-token
/jobhunter/telegram-chat-id
```

The actual secret values are not stored in source control.

# 35. Current API Lambda Logic

The API Lambda supports both POST and GET.

Pseudo-flow:

```text
lambda_handler
    │
    ├── route == GET /results/{job_id}
    │      │
    │      ├── validate job_id
    │      ├── DynamoDB GetItem
    │      └── return 200/404
    │
    └── otherwise process POST body
           │
           ├── parse body
           ├── require JSON object
           ├── require resume_text
           ├── require job_text
           ├── generate UUID
           ├── create PROCESSING item
           ├── set TTL
           ├── send SQS message
           └── return HTTP 202
```

---

# 36. Current Worker Logic


The worker is now the central processing component.

Pseudo-flow:

```text
SQS message arrives
      │
      ▼
Worker starts
      │
      ├── read job_id
      ├── read job_text
      │
      ├── download resume.txt from S3
      │
      ├── SHA-256 hash resume
      │
      ├── check jobhunter-resume-cache
      │
      ├── cache HIT?
      │      ├── yes -> deserialize cached ResumeAnalysis
      │      └── no  -> analyze resume with AI
      │
      ├── analyze job with AI
      │
      ├── run match_job()
      │
      ├── score skills
      │
      ├── calculate transferable credit
      │
      ├── calculate professional experience
      │
      ├── decide APPLY / STRETCH / SKIP
      │
      ├── save resume analysis if cache miss
      │
      ├── update jobhunter-results to DONE
      │
      └── if recommendation == APPLY
               │
               ▼
          send Telegram message
```

Telegram notification failure is intentionally isolated from the core match result.

The worker first writes the successful result to DynamoDB. The Telegram send is wrapped in its own `try/except`, so a temporary Telegram problem does not incorrectly change a successful match to `FAILED` or cause unnecessary SQS retries.

A successful controlled test produced:

```text
Recommendation: APPLY
Technical match: 85.0 %
Experience match: 100 %
Telegram notification sent: 200
```

# 37. Current Fetcher Logic


The fetcher is fully connected to a real job source.

Current source:

```text
Remotive public remote-jobs API
```

Current endpoint:

```text
https://remotive.com/api/remote-jobs?category=software-dev
```

The fetcher sends a browser-like `User-Agent` because the first direct `urllib` request returned HTTP `403 Forbidden`.

Current flow:

```text
Fetcher starts
    │
    ▼
GET Remotive jobs
    │
    ▼
normalize:
    title
    company
    url
    job_text
    │
    ▼
company + title + URL
    │
    ▼
SHA-256 -> job_key
    │
    ▼
GetItem(job_key)
    │
    ├── exists -> duplicate -> skip
    │
    └── missing
           │
           ▼
      title relevance filter
           │
      ┌────┴────┐
 irrelevant   relevant
      │           │
     skip         ▼
             create job_id
                  │
                  ▼
        PROCESSING result row
                  │
                  ▼
             SQS SendMessage
                  │
                  ▼
        mark posting as seen
```

The fetcher was improved so the cap applies to **new jobs actually queued**, not merely the first N postings inspected.

Current safety cap:

```python
MAX_JOBS_PER_RUN = 5
```

The loop can scan past duplicates and irrelevant postings but stops after 5 new relevant jobs have actually been queued.

The fetcher also returns:

```text
jobs_checked
new_jobs_queued
results
```

for easier testing and visibility.

# 38. Next Planned Step — Real Job Source


Real job-source ingestion is complete for v1.

The hard-coded fetcher job was replaced with Remotive.

The integration was built incrementally:

1. Fetch a real external feed.
2. Add a `User-Agent` after the initial HTTP 403.
3. Normalize each posting into `title`, `company`, `url`, and `job_text`.
4. Reuse the existing SHA-256 seen-job key.
5. Verify first-run `new` and second-run `duplicate`.
6. Give the fetcher permission to create `PROCESSING` items in `jobhunter-results`.
7. Send only unseen jobs to the real SQS queue.
8. Verify the worker processes the real posting.
9. Verify resume cache HIT behavior.
10. Verify final DynamoDB status becomes `DONE`.

A real Remotive `Senior DevOps Engineer` posting completed end-to-end and produced:

```text
Recommendation: STRETCH
Technical match: 56.86 %
Experience match: 0.0 %
Missing hard requirements:
- kubernetes
```

The resulting DynamoDB item was verified with:

```text
status: DONE
recommendation: STRETCH
technical_match: 56.86
experience_match: 0.0
```

# 39. Future EventBridge Scheduling


EventBridge scheduling **has been implemented and verified**.

Terraform resources:

```text
aws_cloudwatch_event_rule.jobhunter_fetch_schedule
aws_cloudwatch_event_target.jobhunter_fetcher_target
aws_lambda_permission.allow_eventbridge_fetcher
```

Rule:

```hcl
resource "aws_cloudwatch_event_rule" "jobhunter_fetch_schedule" {
  name                = "jobhunter-fetch-schedule"
  schedule_expression = "rate(1 day)"
}
```

Target:

```text
jobhunter-fetcher Lambda
```

The Lambda permission allows:

```text
events.amazonaws.com
```

to invoke the fetcher.

Verification command:

```powershell
aws events describe-rule `
  --name jobhunter-fetch-schedule `
  --profile terraform-sso `
  --region us-east-2
```

Verified output included:

```text
ScheduleExpression: rate(1 day)
State: ENABLED
```

The target was also verified:

```powershell
aws events list-targets-by-rule `
  --rule jobhunter-fetch-schedule `
  --profile terraform-sso `
  --region us-east-2
```

with:

```text
Id: jobhunter-fetcher
Arn: arn:aws:lambda:...:function:jobhunter-fetcher
```

Therefore JobHunter now runs its automatic discovery step once every 24 hours without a manual Lambda invocation.

Important distinction:

```text
EventBridge runs once/day
```

does **not** mean Telegram sends once/day.

Telegram only sends when a processed job receives:

```text
recommendation == APPLY
```

With `MAX_JOBS_PER_RUN = 5`, one scheduled run can currently generate from 0 to 5 `APPLY` Telegram notifications depending on the jobs found and their scores.

# 40. Important Mistakes and Fixes — Summary Table


| Problem | Cause | Fix | Lesson |
| --- | --- | --- | --- |
| API returned Internal Server Error | Lambda treated HTTP API event as direct JSON | Parse `event["body"]`, decode JSON | Understand the API Gateway event envelope |
| Malformed JSON could reach handler | Missing JSON decode validation | Catch `json.JSONDecodeError` | Validate client input |
| JSON array caused `.get()` problems | Assumed body was always an object | `isinstance(body, dict)` check | Validate data type, not just syntax |
| Missing fields behaved inconsistently | Plain-string error bodies | Return JSON error objects | Keep API responses consistent |
| Edited Lambda package files directly | Source/package folders were confused | Clarify source vs deployment package workflow | Keep a clear source of truth |
| Fake fetcher could trigger real AI worker | Test message used real SQS queue | Use a safe smoke-test handler first | Test components independently before wiring them together |
| Remotive returned HTTP 403 | Direct `urllib` request lacked expected request headers | Add a `User-Agent` header | External APIs may reject generic clients |
| Fetcher could not write PROCESSING results | Fetcher role lacked `dynamodb:PutItem` on `jobhunter-results` | Add least-privilege inline IAM policy | New code paths often require matching IAM updates |
| PowerShell mangled inline JSON | Quotes were stripped before AWS CLI received them | Use `file://*.json` request files | File-based AWS CLI JSON is safer on PowerShell |
| Malformed SQS messages repeatedly failed | Bad manually-sent JSON entered the real queue | Use valid file-based JSON; rely on retry/DLQ behavior | Poison messages are exactly why DLQs matter |
| SNS stayed Pending/Deleted | Email subscription requires manual confirmation | Confirm subscription from email | Terraform cannot confirm an email recipient for you |
| Fetcher got DynamoDB `AccessDenied` even though policy existed | Lambda execution environment had stale credentials | Verify IAM, then force Lambda configuration refresh | Debug IAM systematically before changing policies |
| Manual Lambda update created Terraform drift | CLI changed a Terraform-managed resource | Let Terraform remove drift or declare setting in HCL | IaC should remain source of truth |
| Re-analyzing resume wasted AI calls | Every job caused repeated resume analysis | DynamoDB resume-analysis cache | Cache stable expensive computation |
| Resume was unnecessarily passed in queue messages | Worker depended on `resume_text` in each message | Store resume in S3 and load it in worker | Keep queue payloads small and stable |
| Cost estimates were guesses | No actual token metrics | Log `response.usage` | Measure before optimizing |
| Duplicate jobs would waste AI calls | No persistent seen-job state | `jobhunter-seen-jobs` + SHA-256 job key | Idempotency/deduplication should come before scheduling |
| First title filter was too broad | Generic words like `engineer`, `software`, and `developer` matched irrelevant roles | Split strong vs secondary target keywords | Cheap filtering should happen before AI |
| Rails Tech Lead still showed duplicate | It had already been stored as seen before the new filter | Delete that seen-job item and retest | Dedupe ordering can hide later filtering behavior |
| First CloudWatch alarm showed `INSUFFICIENT_DATA` | Alarm had just been created | Wait for metric datapoint | `INSUFFICIENT_DATA` is not automatically a failure |
| Telegram `getUpdates` initially returned empty | Bot had no pending user message | Start/message the bot, then call `getUpdates` | Bots cannot infer a chat until there is an interaction |
| Telegram notification could have caused false worker failures | Notification call was inside the main processing flow | Wrap Telegram send in its own `try/except` after saving `DONE` | Notification failure should not invalidate a completed job |
| Secrets could have leaked to Git | `.env`, Terraform state, test files and deployment artifacts existed locally | Build `.gitignore` and scan before staging | Public repos need an explicit secret/artifact hygiene step |
| Wrong folders were initially committed | `lambda_app` was committed while Terraform deploys from package folders | Reorganize Git tracking around actual deployment-package source files | Repo structure should match deployed structure |
| Vendored dependencies would bloat GitHub | Worker package contains OpenAI/Pydantic/etc. | Ignore package contents by default and allow-list project source files | Commit source, not generated dependency trees |

# 41. Things That Worked Especially Well

## Terraform planning before applying

A repeated workflow was:

```powershell
terraform fmt
terraform plan
```

Then inspect:

```text
Plan: X to add, Y to change, Z to destroy
```

before applying.

This caught unintended changes and made each learning step understandable.

## Small incremental changes

Instead of building the entire system in one shot, the project evolved in small steps:

```text
local matcher
    ↓
AI matcher
    ↓
Lambda
    ↓
API Gateway
    ↓
DynamoDB
    ↓
SQS worker
    ↓
GET result endpoint
    ↓
DLQ
    ↓
CloudWatch alarms
    ↓
SNS
    ↓
resume cache
    ↓
token logging
    ↓
fetcher
    ↓
seen-job dedupe
```

This made debugging much easier.

## Least privilege

Different components have different IAM permissions rather than one giant shared role.

## Real testing

The project did not stop at `terraform apply`.

It was tested with:

- PowerShell HTTP calls
- AWS CLI Lambda invocation
- CloudWatch logs
- DynamoDB `get-item`
- SNS subscription inspection
- CloudWatch alarm inspection
- IAM policy inspection
- IAM policy simulator
- repeated duplicate-detection invocations

---

# 42. Useful Commands Used During the Project

## Terraform

```powershell
terraform fmt
terraform plan
terraform apply
```

## Worker logs

```powershell
aws logs tail /aws/lambda/jobhunter-worker `
  --since 5m `
  --profile terraform-sso `
  --region us-east-2
```

## Fetcher invoke

```powershell
aws lambda invoke `
  --function-name jobhunter-fetcher `
  --payload '{}' `
  --cli-binary-format raw-in-base64-out `
  --profile terraform-sso `
  --region us-east-2 `
  fetcher-response.json

Get-Content fetcher-response.json
```

## SNS subscription status

```powershell
aws sns list-subscriptions-by-topic `
  --topic-arn "<SNS_TOPIC_ARN>" `
  --profile terraform-sso `
  --region us-east-2
```

## Inspect IAM inline policy

```powershell
aws iam get-role-policy `
  --role-name jobhunter-fetcher-role `
  --policy-name jobhunter-fetcher-seen-jobs-access `
  --profile terraform-sso
```

## IAM simulator

```powershell
aws iam simulate-principal-policy `
  --policy-source-arn arn:aws:iam::<ACCOUNT_ID>:role/jobhunter-fetcher-role `
  --action-names dynamodb:GetItem `
  --resource-arns arn:aws:dynamodb:us-east-2:<ACCOUNT_ID>:table/jobhunter-seen-jobs `
  --profile terraform-sso
```

## Check actual Lambda execution role

```powershell
aws lambda get-function-configuration `
  --function-name jobhunter-fetcher `
  --query Role `
  --output text `
  --profile terraform-sso `
  --region us-east-2
```

---

# 43. Current Folder / Deployment Concept


The public GitHub repository was cleaned so it reflects the code Terraform actually deploys without committing installed dependency trees.

Final intended tracked structure:

```text
jobhunter/
│
├── README.md
├── .gitignore
│
├── lambda_api_package/
│   └── lambda_function.py
│
├── lambda_worker_package/
│   ├── worker_function.py
│   ├── matcher.py
│   ├── ai_extractor.py
│   ├── resume_extractor.py
│   ├── skills.py
│   └── requirements.txt
│
├── lambda_fetcher_package/
│   └── fetcher_function.py
│
└── terraform/
    ├── main.tf
    └── .terraform.lock.hcl
```

The actual local `lambda_worker_package` also contains installed dependencies required by Lambda, such as OpenAI, Pydantic, AnyIO and compiled Linux wheels. Those dependency trees are intentionally ignored by Git.

Terraform currently archives the deployment directories directly:

```text
lambda_api_package
lambda_worker_package
lambda_fetcher_package
```

Ignored public-repo content includes:

```text
.env
Terraform state
generated Lambda ZIPs
temporary AWS CLI JSON payloads
resume files
job test files
installed dependency trees
Python cache files
```

This keeps the GitHub repository reproducible and readable without exposing secrets or committing generated artifacts.

# 44. What I Have Learned From JobHunter

This project has provided hands-on experience with:

- Terraform
- Lambda
- API Gateway HTTP APIs
- Lambda proxy integrations
- HTTP status codes
- JSON parsing and validation
- asynchronous architecture
- SQS
- event source mappings
- dead-letter queues
- DynamoDB
- TTL
- caching
- idempotency and deduplication
- UUIDs
- hashing
- IAM roles
- IAM inline policies
- least privilege
- IAM policy simulation
- SSM Parameter Store
- CloudWatch Logs
- CloudWatch metrics
- CloudWatch alarms
- SNS
- email alert subscriptions
- AI structured output
- AI token accounting
- latency/cost optimization
- Terraform drift
- debugging distributed AWS systems

---

# 45. Current State Checklist


## Completed

- [x] Local job matcher
- [x] Weighted skill scoring
- [x] Requirement strength classification
- [x] AI job extraction
- [x] AI resume extraction
- [x] Resume evidence weighting
- [x] Transferable skill credit
- [x] Experience scoring
- [x] `APPLY` / `STRETCH` / `SKIP`
- [x] API Gateway HTTP API
- [x] `POST /match`
- [x] API Lambda
- [x] Request validation
- [x] DynamoDB results table
- [x] Result TTL
- [x] Async SQS architecture
- [x] Worker Lambda
- [x] SQS event source mapping
- [x] `GET /results/{job_id}`
- [x] Dead-letter queue
- [x] Worker error alarm
- [x] DLQ alarm
- [x] SNS email infrastructure alerts
- [x] SSM OpenAI API-key storage
- [x] S3 resume storage
- [x] Worker loads resume from S3
- [x] Resume-analysis cache
- [x] Real cache-hit/cache-miss verification
- [x] OpenAI token logging
- [x] Fetcher Lambda
- [x] Fetcher-specific IAM role
- [x] Seen-jobs DynamoDB table
- [x] Stable SHA-256 job keys
- [x] Duplicate-job detection
- [x] Real Remotive job-source integration
- [x] Remotive HTTP 403 fix with `User-Agent`
- [x] Normalize real postings
- [x] Send unseen jobs to SQS
- [x] Create PROCESSING result from fetcher
- [x] End-to-end real Remotive job test
- [x] Title relevance filtering
- [x] Strong vs secondary target keywords
- [x] Hard cap of 5 new jobs per fetch run
- [x] EventBridge daily schedule
- [x] EventBridge target verification
- [x] EventBridge Lambda permission
- [x] Fetcher error monitoring
- [x] Telegram bot setup
- [x] Telegram token stored in SSM SecureString
- [x] Telegram chat ID stored in SSM
- [x] Worker IAM expanded only to required Telegram SSM parameters
- [x] Telegram notification only for `APPLY`
- [x] Telegram failure isolated from core worker success
- [x] Controlled Telegram `APPLY` test
- [x] Telegram HTTP `200` verification
- [x] Git repository initialized
- [x] Secrets/artifacts excluded with `.gitignore`
- [x] Terraform state excluded from Git
- [x] README added
- [x] GitHub repository created and pushed
- [x] Git tracking reorganized around actual deployment-package source

## Optional v2 / future improvements

- [ ] Include the source job URL in SQS, results, and Telegram notification
- [ ] Investigate replacing or supplementing Remotive with TMU co-op postings
- [ ] Add a job-source abstraction so multiple sources can be plugged in
- [ ] Move additional hard-coded resource names/URLs into Lambda environment variables or Terraform variables
- [ ] Add automated tests
- [ ] Add richer notification controls such as optional `STRETCH` alerts
- [ ] Consider job-analysis caching for identical postings that reappear across sources
- [ ] Refactor Terraform into multiple files/modules if the stack continues to grow
- [ ] Add a polished architecture diagram/image for the public README

# 46. Recommended Next Architecture


The intended v1 architecture has now been achieved:

```text
                         EventBridge
                         rate(1 day)
                             │
                             ▼
                    ┌──────────────────┐
                    │ Fetcher Lambda   │
                    └────────┬─────────┘
                             │
                             ▼
                       Remotive API
                             │
                             ▼
                    Normalize postings
                             │
                             ▼
                    jobhunter-seen-jobs
                       │           │
                  duplicate       unseen
                       │           │
                      skip         ▼
                          title relevance filter
                                 │
                            irrelevant?
                           /           \
                         yes            no
                          │              │
                         skip            ▼
                                 PROCESSING result
                                        │
                                        ▼
                                       SQS
                                        │
                                        ▼
                               Worker Lambda
                                 │        │
                                 │        ├── S3 resume
                                 │        ├── Resume Cache
                                 │        ├── OpenAI
                                 │        └── SSM secrets
                                 │
                                 ▼
                            Matching Engine
                                 │
                                 ▼
                            Results DynamoDB
                                 │
                            recommendation
                               == APPLY?
                              /       \
                            no         yes
                            │           │
                          finish     Telegram
```

Failures are handled separately:

```text
Worker errors ───────┐
Fetcher errors ──────┼──> CloudWatch Alarm -> SNS -> Email
DLQ messages ────────┘
```

The manual API path still exists in parallel:

```text
POST /match -> API Lambda -> SQS -> Worker
GET /results/{job_id} -> API Lambda -> DynamoDB
```

This means JobHunter supports both manually submitted matches and automatic job discovery.

# 47. Biggest Engineering Lessons From the Project

The biggest change in the project was not one AWS service. It was learning to think in terms of **systems**.

A seemingly simple question:

```text
"Does my resume fit this job?"
```

turned into separate concerns:

```text
How does a request enter?
How do I avoid making the client wait?
Where does work queue?
What happens if the worker fails?
Where do I store status?
How does the client retrieve results?
How do I protect secrets?
How do I prevent duplicates?
How do I avoid paying to analyze the same resume again?
How do I know when something breaks?
How do I make AWS send me an alert?
How do I verify IAM instead of guessing?
How do I keep Terraform as the source of truth?
How do I automatically discover jobs safely?
```

That is the main value of JobHunter as an AWS/Cloud/DevOps project: it is no longer only a Python script. It is becoming a small production-style event-driven cloud system.

---

# 48. Immediate Next Step


JobHunter v1 is no longer paused before real ingestion. The core project is complete and working.

The next logical work is v2 refinement rather than completing missing v1 infrastructure.

Highest-value next steps:

```text
1. Pass the real job URL through SQS
2. Store the URL with the result
3. Include the clickable URL in Telegram
4. Investigate TMU co-op as a replacement or additional job source
5. Keep Remotive as a fallback/source adapter if useful
```

The TMU co-op idea would change only the ingestion side:

```text
TMU Co-op Portal
      │
      ▼
authenticated source adapter
      │
      ▼
existing normalize / dedupe / filter logic
      │
      ▼
SQS
      │
      ▼
existing worker / matcher / Telegram pipeline
```

Because the TMU portal is authenticated, this should be investigated carefully before implementing automation. The current completed Remotive integration remains the working v1 source.


# 49. S3 Resume Storage Upgrade

The worker originally expected `resume_text` to arrive in the SQS message.

That was changed so the resume is stored once in S3:

```text
jobhunter-resume-storage/resume.txt
```

Worker flow:

```text
SQS message:
job_id + job_text
      │
      ▼
Worker
      │
      ▼
S3 GetObject
      │
      ▼
resume_text
```

Worker IAM was given only:

```text
s3:GetObject
```

for the specific resume object.

This reduced queue payload size and removed the need to duplicate the same resume text in every job message.

A controlled SQS test proved the worker could successfully retrieve the resume from S3, calculate the resume hash, analyze the job, and save the result.

---

# 50. Real End-to-End Remotive Test

A known Remotive `Senior DevOps Engineer` item was deliberately removed from `jobhunter-seen-jobs` so exactly one real posting could be processed as new.

The fetcher produced a new UUID job ID, wrote a `PROCESSING` result, and sent the job to SQS.

Worker logs showed:

```text
JobHunter worker started
Resume cache HIT
Using cached resume analysis.
Analyzing job with AI...
```

The real posting was analyzed as:

```text
Job title: Senior DevOps Engineer
Required experience: 4 years
Technical match: 56.86 %
Experience match: 0.0 %
Recommendation: STRETCH
Missing hard requirement: kubernetes
```

The corresponding DynamoDB row was verified as:

```text
status: DONE
recommendation: STRETCH
technical_match: 56.86
experience_match: 0.0
```

This was the first proof that the real external source could flow through:

```text
Remotive
  -> Fetcher
  -> dedupe
  -> PROCESSING row
  -> SQS
  -> Worker
  -> S3 resume
  -> resume cache
  -> AI
  -> matcher
  -> DynamoDB DONE
```

---

# 51. Job-Relevance Filtering and Cost Controls

After real ingestion worked, the fetcher started seeing postings that were obviously outside the intended target, such as marketing or unrelated roles.

A cheap title filter was added **before SQS and before AI**.

Initial keyword filtering was too broad because generic words such as:

```text
engineer
software
developer
support
```

could allow unrelated roles.

The filter was then split into stronger and secondary target groups.

Examples of strong targets:

```text
devops
cloud
infrastructure
platform
site reliability
sre
aws
```

Examples of secondary targets:

```text
qa
test
support
systems
service desk
help desk
helpdesk
```

A real false-positive test used:

```text
Tech Lead Full-Stack Rails Engineer
```

After deleting its old seen-job record and re-running the fetcher, the tighter filter correctly returned:

```text
status: irrelevant
```

and no `job_id` was created.

The fetcher also uses:

```python
MAX_JOBS_PER_RUN = 5
```

but the counter applies to **new jobs queued**, not simply the first 5 jobs inspected.

This means duplicates and irrelevant jobs can be skipped while scanning further, but no run can trigger more than 5 new AI job analyses.

---

# 52. Fetcher Error Monitoring

A separate CloudWatch alarm was added for:

```text
jobhunter-fetcher-errors
```

Configuration:

```text
Namespace: AWS/Lambda
Metric: Errors
Statistic: Sum
Period: 60
EvaluationPeriods: 1
Threshold: >= 1
TreatMissingData: notBreaching
```

Alarm action:

```text
jobhunter-alerts SNS topic
```

Immediately after creation the alarm reported:

```text
INSUFFICIENT_DATA
```

with the reason:

```text
Unchecked: Initial alarm creation
```

This was expected for a brand-new alarm before enough metric data existed.

---

# 53. Telegram APPLY Notifications

The notification system was upgraded from infrastructure-only email alerts to application-level Telegram alerts for strong job matches.

Telegram setup required:

1. Create a bot with BotFather.
2. Store the bot token in SSM as a `SecureString`.
3. Message the bot so `getUpdates` exposes the chat.
4. Obtain the `chat.id`.
5. Store the chat ID in SSM.
6. Expand the worker's existing SSM IAM policy to the exact Telegram parameter ARNs.
7. Add a Telegram helper using Python `urllib`.
8. Trigger it only when:

```python
result.get("recommendation") == "APPLY"
```

The Telegram send happens after DynamoDB is updated to `DONE`.

It is wrapped in a separate error handler:

```text
Telegram failure
      │
      ▼
log notification error
      │
      └── do NOT mark job FAILED
```

This prevents a notification outage from causing the actual job match to retry.

A controlled test posting:

```text
Junior AWS Cloud Engineer.
Experience with AWS, Terraform, EC2, IAM, networking, Linux and Python.
No prior professional experience required.
```

produced:

```text
Recommendation: APPLY
Technical match: 85.0 %
Experience match: 100 %
```

and CloudWatch confirmed:

```text
Telegram notification sent: 200
```

The Telegram message was received successfully.

---

# 54. GitHub and Repository Hardening

Before publishing the project, the repository was audited for secrets and generated artifacts.

The local project contained:

```text
.env
Terraform state
temporary AWS CLI JSON files
Lambda ZIP/build artifacts
resume files
job test files
installed Lambda dependencies
```

A `.gitignore` was created to keep these out of Git.

A PowerShell secret scan was also run for patterns such as:

```text
OpenAI-style keys
Telegram token references
AWS access key IDs
private key headers
API-key assignments
```

The results were reviewed to distinguish safe parameter names and dependency code from actual secret values.

An initial Git staging set accidentally included:

```text
terraform/jobhunter_lambda_zip
terraform/payload.json
```

These were removed from the Git index before committing.

Terraform state remained ignored.

The repo was pushed to GitHub, then one more structural issue was noticed:

```text
lambda_app
```

had been committed even though Terraform deploys from:

```text
lambda_api_package
lambda_worker_package
lambda_fetcher_package
```

Git tracking was corrected.

The public repo now tracks the project-authored source files inside the actual deployment directories while ignoring third-party dependency trees in the worker package.

This keeps the repository aligned with the deployed architecture without uploading thousands of generated dependency files.

---

# 55. Final v1 Behavior

With v1 running, the automated behavior is:

```text
Once every 24 hours
       │
       ▼
EventBridge invokes fetcher
       │
       ▼
Fetcher pulls Remotive software-development postings
       │
       ▼
For each posting:
    generate stable SHA-256 job_key
       │
       ├── already seen -> duplicate -> skip
       │
       └── unseen
              │
              ▼
        relevance filter
          │        │
     irrelevant   relevant
          │        │
         skip      ▼
              create PROCESSING row
                    │
                    ▼
                   SQS
                    │
                    ▼
                 Worker
                    │
                    ├── S3 resume
                    ├── resume cache
                    ├── OpenAI job analysis
                    └── deterministic matcher
                    │
                    ▼
                 DynamoDB
                    │
               recommendation
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
      STRETCH/SKIP           APPLY
          │                   │
        finish             Telegram
```

The EventBridge schedule runs once per day.

Telegram does **not** send on a fixed once-per-day schedule. It sends only for `APPLY` results.

Because the fetcher is capped at 5 newly queued jobs per run, the theoretical application-level notification count from one scheduled fetch run is:

```text
0 to 5 Telegram APPLY notifications
```

depending on how many new relevant jobs are found and how the matcher scores them.

---


## End of Current Project History

This document now reflects the completed JobHunter v1 project through:

- real Remotive job ingestion
- duplicate detection
- relevance filtering
- a 5-new-job-per-run safety limit
- S3 resume retrieval
- resume-analysis caching
- asynchronous SQS worker processing
- real DynamoDB `DONE` results
- EventBridge daily scheduling
- worker/fetcher/DLQ monitoring
- SNS infrastructure alerts
- Telegram `APPLY` notifications
- a successful controlled Telegram test returning HTTP `200`
- Git/GitHub cleanup and public-repository hardening

The project is now a functioning serverless, event-driven AWS job-discovery and AI matching system rather than a partially connected prototype.
