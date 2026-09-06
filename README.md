# JobHunter — Complete Project History, Architecture, Mistakes, Fixes, and Current State

> **Project:** JobHunter — Serverless AI Job Matching / Job Discovery System  
> **AWS Region:** `us-east-2` (Ohio)  
> **IaC:** Terraform  
> **Primary language:** Python 3.13  
> **Status:** Core async matching pipeline works; monitoring, alerts, caching, token logging, fetcher Lambda, and duplicate-job detection work. Real-job-source integration is the next step.

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

The current architecture has three Lambda functions.

```text
                         ┌─────────────────────┐
                         │   Manual API User   │
                         └──────────┬──────────┘
                                    │
                              POST /match
                                    │
                                    ▼
                           API Gateway HTTP API
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  API Lambda         │
                         │  jobhunter-lambda   │
                         └──────────┬──────────┘
                                    │
                             SendMessage
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ SQS Match Queue     │
                         └──────────┬──────────┘
                                    │
                         Event Source Mapping
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Worker Lambda       │
                         │ jobhunter-worker    │
                         └──────┬─────┬────────┘
                                │     │
                    AI calls    │     │ DynamoDB
                                │     ▼
                                │  jobhunter-results
                                │
                                ├────> jobhunter-resume-cache
                                │
                                └────> SSM Parameter Store
                                      (OpenAI API key)

Results are retrieved with:

GET /results/{job_id}
        │
        ▼
API Gateway
        │
        ▼
API Lambda
        │
        ▼
jobhunter-results
```

A third ingestion path is now being built:

```text
Real Job Source
      │
      ▼
jobhunter-fetcher
      │
      ├──> jobhunter-seen-jobs
      │       │
      │       └── duplicate? -> skip
      │
      └── new job -> eventually send to SQS
```

Monitoring:

```text
Worker Lambda Errors ──────┐
                           ├──> CloudWatch Alarm
DLQ Messages ──────────────┘
                                  │
                                  ▼
                              SNS Topic
                                  │
                                  ▼
                               Email
```

---

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

The project now includes resources in these areas.

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

Separate roles for:

```text
API Lambda
Worker Lambda
Fetcher Lambda
```

with narrow inline policies and `AWSLambdaBasicExecutionRole`.

## SQS

```text
jobhunter-match-queue
jobhunter-match-dlq
```

## DynamoDB

```text
jobhunter-results
jobhunter-resume-cache
jobhunter-seen-jobs
```

## Monitoring

```text
jobhunter-worker-errors
jobhunter-dlq-messages
```

## SNS

```text
jobhunter-alerts
```

## SSM

OpenAI API key stored under:

```text
/jobhunter/openai-api-key
```

---

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

Pseudo-flow:

```text
SQS message arrives
      │
      ▼
Worker starts
      │
      ├── hash resume
      │
      ├── check resume cache
      │
      ├── cache HIT?
      │      ├── yes -> deserialize cached analysis
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
      ├── calculate experience
      │
      ├── decide APPLY/STRETCH/SKIP
      │
      ├── save resume analysis if needed
      │
      └── update jobhunter-results
```

---

# 37. Current Fetcher Logic

Right now the fetcher has only been tested with a hard-coded job.

Pseudo-flow:

```text
Fetcher starts
    │
    ▼
hard-coded job
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
         PutItem
           │
           ▼
         mark seen
```

It is **not yet connected to a real job API/feed**.

---

# 38. Next Planned Step — Real Job Source

The next planned phase is to replace the hard-coded fetcher job with a real job source.

The proposed first source was a public machine-readable job API/feed.

Planned fetcher behavior:

```text
Public job API
      │
      ▼
fetch JSON
      │
      ▼
take a small number of jobs first
      │
      ▼
normalize each posting into:
    title
    company
    url
    job_text
      │
      ▼
generate job_key
      │
      ▼
check seen-jobs table
      │
      ├── duplicate -> skip
      └── new -> eventually send to SQS
```

For safety, the first real-source test should **not immediately send jobs to SQS**.

First prove:

```text
fetch
parse
normalize
deduplicate
```

Then connect new jobs to the real worker queue.

---

# 39. Future EventBridge Scheduling

EventBridge has not been added yet.

Planned architecture:

```text
EventBridge Schedule
        │
        ▼
jobhunter-fetcher
        │
        ▼
job source
        │
        ▼
dedupe
        │
        ▼
SQS
```

Important design choice:

**Deduplication was built before scheduling.**

Without it, every EventBridge run could resend the same jobs and cause repeated AI charges.

---

# 40. Important Mistakes and Fixes — Summary Table

| Problem | Cause | Fix | Lesson |
| --- | --- | --- | --- |
| API returned Internal Server Error | Lambda treated HTTP API event as direct JSON | Parse `event["body"]`, decode JSON | Understand the API Gateway event envelope |
| Malformed JSON could reach handler | Missing JSON decode validation | Catch `json.JSONDecodeError` | Validate client input |
| JSON array caused `.get()` problems | Assumed body was always an object | `isinstance(body, dict)` check | Validate data type, not just syntax |
| Missing fields behaved inconsistently | Plain-string error bodies | Return JSON error objects | Keep API responses consistent |
| Edited Lambda deployment/package files directly | Source/package folders were confused | Use `lambda_app` as source and copy to package | Keep a single source of truth |
| Fake fetcher could trigger real AI worker | Test message used real SQS queue | Replace with safe smoke-test handler | Test components independently before wiring them together |
| SNS stayed Pending/Deleted | Email subscription requires manual confirmation | Confirm subscription from email | Terraform cannot confirm an email recipient for you |
| Fetcher got DynamoDB `AccessDenied` even though policy existed | Lambda execution environment had stale credentials | Verify IAM, then force Lambda configuration refresh | Debug IAM systematically before changing policies |
| Manual Lambda update created Terraform drift | CLI changed a Terraform-managed resource | Let Terraform remove drift or declare setting in HCL | IaC should remain source of truth |
| Re-analyzing resume wasted AI calls | Every job caused two AI analyses | DynamoDB resume-analysis cache | Cache stable expensive computation |
| Cost estimates were guesses | No actual token metrics | Log `response.usage` | Measure before optimizing |
| Duplicate jobs would waste AI calls | No persistent seen-job state | `jobhunter-seen-jobs` + SHA-256 job key | Idempotency/deduplication should come before scheduling |
| First CloudWatch alarm showed insufficient data | Alarm had just been created | Wait for metric datapoint | `INSUFFICIENT_DATA` is not automatically a failure |

---

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

Approximate structure:

```text
jobhunter/
│
├── lambda_app/
│   ├── matcher.py
│   ├── ai_extractor.py
│   ├── resume_extractor.py
│   ├── skills.py
│   └── other source files
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
│   └── packaged dependencies
│
├── lambda_fetcher_package/
│   └── fetcher_function.py
│
└── terraform/
    ├── main.tf
    ├── generated Lambda ZIP files
    └── Terraform state/local metadata
```

The exact packaging contents may evolve, but the important principle is:

```text
source code
   ↓
copy/build deployment package
   ↓
Terraform archive_file
   ↓
Lambda
```

---

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
- [x] SNS email alerts
- [x] SSM API-key storage
- [x] Resume-analysis cache
- [x] Real cache-hit/cache-miss verification
- [x] OpenAI token logging
- [x] Fetcher Lambda
- [x] Fetcher-specific IAM role
- [x] Seen-jobs DynamoDB table
- [x] Stable SHA-256 job keys
- [x] Duplicate-job detection
- [x] IAM simulator debugging
- [x] Lambda stale-credential fix
- [x] Duplicate first-run / second-run verification

## Next

- [ ] Connect fetcher to a real job API/feed
- [ ] Normalize real postings
- [ ] Test real postings without SQS first
- [ ] Send only unseen jobs to SQS
- [ ] Decide how the fetcher obtains the user's resume without sending the full resume unnecessarily
- [ ] Add EventBridge schedule
- [ ] Add safe limits per fetch run
- [ ] Add fetcher error monitoring
- [ ] Consider a job-source abstraction so multiple sources can be added
- [ ] Consider storing source/job URL metadata with match results
- [ ] Consider caching job analysis when identical postings reappear
- [ ] Optimize AI output-token usage
- [ ] Add tests
- [ ] Clean/refactor Terraform into multiple files/modules if desired
- [ ] Final GitHub README / architecture diagram
- [ ] Add JobHunter to resume once the project is considered complete

---

# 46. Recommended Next Architecture

The intended final direction is:

```text
                         EventBridge
                             │
                             ▼
                    ┌──────────────────┐
                    │ Fetcher Lambda   │
                    └────────┬─────────┘
                             │
                        Job API/feed
                             │
                             ▼
                    Normalize postings
                             │
                             ▼
                    jobhunter-seen-jobs
                       │           │
                  duplicate       new
                       │           │
                      skip         ▼
                                  SQS
                                   │
                                   ▼
                          Worker Lambda
                            │         │
                            │         ├── Resume Cache
                            │         ├── OpenAI
                            │         └── SSM secret
                            │
                            ▼
                       Results DynamoDB
                            │
                            ▼
                      GET /results/{id}

Failures:
Worker/SQS -> DLQ -> CloudWatch Alarm -> SNS -> Email
```

---

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

The project is currently paused immediately before **real job-source ingestion**.

The next implementation step is:

```text
replace hard-coded fetcher job
        ↓
call real public job source
        ↓
normalize first few jobs
        ↓
check jobhunter-seen-jobs
        ↓
print new/duplicate
```

Do **not** immediately send every fetched job to SQS.

First verify the external source and deduplication safely. Once that works, connect only unseen jobs to the queue.

---

## End of Current Project History

This document reflects the JobHunter project state through the successful duplicate-detection test in which the first fetcher invocation returned `New job found` and the second returned `Duplicate job skipped`.
