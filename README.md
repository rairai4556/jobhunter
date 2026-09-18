# JobHunter — Serverless AI Job Discovery & Matching System

> **AWS Region:** `us-east-2` (Ohio)  
> **Infrastructure as Code:** Terraform
> **Primary Languages:** Python 3.13, JavaScript
> **Status:** JobHunter v1 is complete and working end-to-end.

JobHunter is a serverless, event-driven job discovery and matching system built on AWS.

It can receive jobs through three ingestion paths:

1. A manual HTTP API using `POST /match`
2. Automated daily job discovery from Remotive, Jobicy, Remote OK, and The Muse using Amazon EventBridge
3. Authenticated TMU Co-op job collection using a Chrome extension and local collector

All three paths feed into the same asynchronous AWS processing pipeline. Jobs are queued through Amazon SQS, analyzed against a resume stored in Amazon S3, scored using AI-assisted extraction and deterministic Python logic, stored in Amazon DynamoDB, and optionally sent to Telegram when the recommendation is `APPLY`. Automated-source notifications preserve the source and canonical application link. If an `APPLY` posting explicitly requests a cover letter, JobHunter generates a resume-grounded tailored letter and attaches it as a PDF to the Telegram job message.

The system also includes resume-analysis caching, duplicate prevention, CloudWatch monitoring, SNS alerts, secure secret storage with AWS Systems Manager Parameter Store, and infrastructure managed with Terraform.

---

# 1. Why I Built JobHunter

JobHunter started as a way to reduce the amount of time spent manually reading job postings and deciding whether they were worth applying to.

The original idea was simple:

1. Read a resume.
2. Read a job posting.
3. Compare the two.
4. Calculate a match score.
5. Recommend `APPLY`, `STRETCH`, or `SKIP`.

The project gradually evolved into a complete AWS serverless system capable of discovering jobs, filtering them, preventing duplicates, asynchronously processing them, caching expensive AI analysis, storing results, monitoring failures, and sending notifications.

The final project combines:

- serverless computing
- event-driven architecture
- asynchronous queues
- AI-assisted information extraction
- deterministic scoring
- persistent cloud storage
- caching
- API design
- browser extension development
- monitoring and alerting
- secure secret management
- Infrastructure as Code

---

# 2. Core Design Principle

The central design principle behind JobHunter is:

> **AI interprets. Python decides.**

AI is used to convert unstructured job postings and resumes into structured information.

Python then performs the actual scoring and recommendation logic.

This prevents the final recommendation from simply being an unpredictable AI opinion.

The AI identifies information such as:

- required technologies
- preferred technologies
- requirement strength
- required years of experience
- resume evidence
- professional experience
- project experience

The deterministic matcher then calculates:

- technical match
- experience match
- transferable skill credit
- missing hard requirements
- missing strong requirements
- final recommendation

The final recommendation is one of:

```text
APPLY
STRETCH
SKIP
```

---

# 3. Current Architecture

JobHunter has three different job-ingestion paths that converge on the same worker pipeline.

```text
                           JobHunter

        +--------------------+--------------------+
        |                    |                    |
        v                    v                    v
   Manual API          Job APIs               TMU Co-op
   POST /match          EventBridge        Chrome Extension
        |                    |                    |
        v                    v                    v
    API Lambda          Fetcher Lambda       Local Collector
        |                    |                    |
        |                    |              POST /tmu-jobs
        |                    |                    |
        +--------------------+--------------------+
                             |
                             v
                            SQS
                             |
                             v
                       Worker Lambda
                             |
              +--------------+--------------+
              |              |              |
              v              v              v
             S3          Resume Cache     OpenAI
           Resume          DynamoDB       Analysis
              |              |              |
              +--------------+--------------+
                             |
                             v
                    Deterministic Matcher
                             |
                             v
                  APPLY / STRETCH / SKIP
                             |
                             v
                      DynamoDB Results
                             |
                    recommendation == APPLY?
                       /             \
                     no               yes
                     |                 |
                   finish          Telegram
```

This architecture allows multiple job sources to reuse the same expensive matching infrastructure.

---

# 4. AWS Services Used

JobHunter uses the following AWS services:

| Service | Purpose |
|---|---|
| AWS Lambda | API, job fetching, and asynchronous matching |
| API Gateway | HTTP interface for submitting jobs and retrieving results |
| Amazon SQS | Asynchronous job-processing queue |
| Amazon DynamoDB | Results, resume cache, and duplicate tracking |
| Amazon S3 | Resume storage |
| Amazon EventBridge | Daily automated job discovery |
| AWS Systems Manager Parameter Store | Secure API keys and application secrets |
| Amazon CloudWatch | Logging, metrics, and alarms |
| Amazon SNS | Infrastructure failure alerts |
| AWS IAM | Least-privilege permissions |
| Terraform | Infrastructure as Code |

External integrations include:

- OpenAI API
- Remotive
- Jobicy
- Remote OK
- The Muse
- Telegram
- Toronto Metropolitan University Co-op portal

---

# 5. Manual API Path

The manual API allows a client to submit arbitrary resume/job matching work.

```text
Client
   |
   | POST /match
   v
API Gateway
   |
   v
API Lambda
   |
   +--> Generate job_id
   |
   +--> Write PROCESSING record to DynamoDB
   |
   +--> Send job to SQS
             |
             v
        Worker Lambda
```

The API returns immediately instead of waiting for the AI analysis to finish.

This keeps expensive processing asynchronous.

Results can later be retrieved using:

```text
GET /results/{job_id}
```

The API Lambda reads the corresponding record from DynamoDB.

---

# 6. SQS Worker Pipeline

Amazon SQS separates job ingestion from expensive AI processing.

The API, Remotive fetcher, and TMU collector can all submit work without directly running the matcher.

```text
Job Source
    |
    v
   SQS
    |
    v
Worker Lambda
    |
    +--> Load resume
    +--> Check resume cache
    +--> Analyze job
    +--> Run matcher
    +--> Store result
    +--> Notify if APPLY
```

This architecture provides:

- asynchronous processing
- retry capability
- failure isolation
- easier scaling
- separation between ingestion and processing

A dead-letter queue is also configured for worker failures.

---

# 7. Resume Storage with S3

The worker retrieves the resume from Amazon S3.

```text
Bucket:
jobhunter-resume-storage

Object:
resume.txt
```

This means the resume does not need to be included in every SQS message.

The worker downloads the current resume when processing jobs.

---

# 8. Resume Analysis Cache

Analyzing the same resume with AI for every job would waste both time and API tokens.

JobHunter therefore hashes the resume and checks the DynamoDB table:

```text
jobhunter-resume-cache
```

Conceptually:

```text
Load resume from S3
        |
        v
Calculate resume hash
        |
        v
Check resume cache
     /       \
   HIT       MISS
    |          |
    |          v
    |     Analyze resume
    |       with AI
    |          |
    |          v
    |      Save cache
    |          |
    +----------+
        |
        v
Continue matching
```

If the resume has not changed, the previous structured analysis can be reused.

---

# 9. AI Job Extraction

The job extractor analyzes unstructured job descriptions and produces structured requirements.

It extracts information such as:

- job title
- required years of experience
- required skills
- preferred skills
- mentioned technologies
- other requirements

Requirement strengths include:

```text
HARD_REQUIREMENT
STRONG_REQUIREMENT
FAMILIARITY
EXAMPLE
PREFERRED
MENTIONED
```

This lets JobHunter distinguish between statements such as:

```text
"Must have Kubernetes experience"
```

and:

```text
"Experience with Kubernetes is an asset"
```

instead of treating both as equally important keyword matches.

---

# 10. AI Resume Extraction

The resume is analyzed separately from the job posting.

Resume evidence is classified as:

```text
PROFESSIONAL
PROJECT
EDUCATION
SKILLS_SECTION
```

This is important because simply listing a technology is weaker evidence than demonstrating its use in a real project or professional position.

For example:

```text
Skills: Terraform
```

should not necessarily receive the same evidence strength as:

```text
Built AWS infrastructure using Terraform including
VPCs, subnets, route tables, NAT gateways, ALBs,
Auto Scaling Groups, IAM, and SSM.
```

The resume extractor also avoids unsupported assumptions.

Examples:

```text
EC2 != Linux
AWS != Lambda
Docker != Kubernetes
Terraform != Ansible
EC2 != ECS
Kubernetes != EKS
```

Related experience can still receive limited transferable credit.

---

# 11. Deterministic Matching Engine

The AI does not decide whether the user should apply.

After extraction, Python performs the scoring.

Requirement multipliers include:

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

Resume evidence multipliers include:

```python
RESUME_EVIDENCE_MULTIPLIERS = {
    "PROFESSIONAL": 1.0,
    "PROJECT": 1.0,
    "EDUCATION": 0.65,
    "SKILLS_SECTION": 0.40
}
```

Transferable credit between related technologies is intentionally capped.

```python
MAX_TRANSFERABLE_CREDIT = 0.30
```

This allows related knowledge to help without pretending that related technologies are identical.

---

# 12. Experience Matching

Professional experience and project experience are handled separately.

Projects can demonstrate relevant technical ability but do not automatically count as professional years of experience.

The matcher calculates an experience percentage by comparing relevant professional experience against the posting's required years.

Jobs requiring zero years receive:

```text
Experience Match: 100%
```

The final recommendation considers both technical and experience evidence.

---

# 13. Recommendation Engine

JobHunter returns:

```text
APPLY
STRETCH
SKIP
```

The decision considers factors including:

- technical match percentage
- required technologies
- missing hard requirements
- missing strong requirements
- relevant professional experience
- required years of experience
- experience gap
- relevant project experience
- transferable technical knowledge

A candidate with strong technical evidence, sufficient experience, and no important missing requirements can receive:

```text
APPLY
```

Intermediate cases receive:

```text
STRETCH
```

Poor matches receive:

```text
SKIP
```

---

# 14. Automated Multi-Source Job Discovery

JobHunter automatically checks Remotive, Jobicy, Remote OK, and The Muse for jobs.

The automated path is:

```text
EventBridge
    |
    v
Fetcher Lambda
    |
    v
Public Job APIs
    |
    v
Normalize jobs
    |
    v
Duplicate detection
    |
    v
Relevance filtering
    |
    v
SQS
```

EventBridge invokes the fetcher once per day. Provider calls run concurrently and fail independently, so one unavailable API does not stop the others. Results are normalized to a common title, company, description, source, and canonical URL shape, then interleaved across providers before the daily queue limit is applied.

Jobicy is filtered to Canada, Remote OK is filtered to relevant technical tags, The Muse is filtered to entry-level Toronto listings, and Remotive continues to use its software-development category.

A User-Agent header is included because requests without an appropriate header previously received HTTP `403` responses.

---

# 15. Automated-Source Duplicate Detection

Automatically fetching jobs introduces the possibility of repeatedly analyzing the same posting.

The fetcher therefore uses:

```text
jobhunter-seen-jobs
```

Each posting is checked before expensive processing occurs.

Conceptually:

```text
API Job
     |
     v
Seen before?
   /     \
 yes      no
  |        |
 skip      v
       continue
```

This makes scheduled execution idempotent and avoids unnecessary AI costs.

---

# 16. Automated-Source Relevance Filtering

Not every software-development posting is useful for the intended job search.

The fetcher performs lightweight filtering before sending jobs to the worker.

Filtering considers job-title relevance and seniority.

Relevant areas include roles related to:

- software development
- cloud
- DevOps
- infrastructure
- systems
- networking
- IT support
- security
- data
- automation
- QA/testing
- platform engineering

Obviously senior positions can also be filtered before expensive matching.

The fetcher queues at most:

```text
5 new relevant jobs
```

per scheduled run.

This provides a safety limit for API cost and notification volume.

---

# 17. TMU Co-op Integration

JobHunter also supports jobs from the Toronto Metropolitan University Co-op portal.

Unlike Remotive, TMU postings require an authenticated student session.

The TMU integration therefore uses the user's normal authenticated Chrome session rather than attempting to store university credentials or automate authentication.

The architecture is:

```text
TMU Co-op Portal
      |
      v
Chrome Extension
      |
      v
Read visible posting metadata
      |
      v
Request posting detail using
authenticated browser session
      |
      v
Normalize job
      |
      v
Local Collector
127.0.0.1:8765
      |
      v
POST /tmu-jobs
      |
      v
API Gateway
      |
      v
API Lambda
      |
      v
DynamoDB + SQS
      |
      v
Existing Worker Pipeline
```

The TMU integration reuses the existing AWS matching system instead of creating a separate matcher.

---

# 18. TMU Chrome Extension

The Chrome extension is stored in:

```text
tmu_extension/
```

The extension contains:

```text
manifest.json
content.js
background.js
```

The extension runs only on the TMU recruitment portal.

It observes the currently displayed job table and extracts metadata including:

- posting ID
- job title
- company
- location
- deadline

The extension then obtains the job description using the user's existing authenticated browser session.

No TMU username or password is stored by JobHunter.

---

# 19. TMU Title Relevance Filter

The extension performs a lightweight title filter before requesting full job descriptions.

Relevant keywords include areas such as:

```text
software
developer
development
programmer
cloud
devops
infrastructure
systems
network
security
cyber
data
database
technical
technology
information technology
IT support
help desk
service desk
desktop support
computer
automation
QA
quality assurance
testing
machine learning
AI
artificial intelligence
site reliability
SRE
platform
operations engineer
cloud engineer
```

The filter intentionally prefers occasional false positives over false negatives.

A potentially relevant entry-level technology role should not be discarded simply because its title is unusual.

---

# 20. TMU Pagination

JobHunter does not automatically click through every TMU search-results page.

The user navigates the portal normally.

A `MutationObserver` detects when the visible posting table changes.

```text
User opens TMU page
       |
       v
Extension processes page
       |
       v
User clicks next page
       |
       v
TMU replaces job table
       |
       v
MutationObserver detects change
       |
       v
Extension processes new page
```

This keeps navigation under user control while removing the repetitive work of manually opening every relevant posting.

The extension also handles the case where the user changes pages while the previous page is still being processed.

A pending-page flag remembers that the visible page changed and processes it after the current batch finishes.

---

# 21. Sequential TMU Processing

Relevant TMU jobs are processed sequentially rather than firing many requests simultaneously.

For each relevant posting:

```text
Fetch detail
     |
     v
Extract description
     |
     v
Send to collector
     |
     v
Wait for result
     |
     v
Pause
     |
     v
Next job
```

There is a short delay between newly processed jobs.

This makes the integration more controlled and prevents unnecessary request bursts.

---

# 22. TMU Detail Retry

Occasionally a posting-detail response may not contain the expected job-description markers.

Instead of immediately failing permanently, the extension retries the request once after a short delay.

The retry is intentionally limited.

```text
Attempt 1
   |
description found?
 /          \
yes          no
 |            |
continue    wait
              |
              v
           Attempt 2
```

There is no infinite retry loop.

---

# 23. Local TMU Seen Cache

The Chrome extension stores successfully processed posting IDs using:

```text
chrome.storage.local
```

under:

```text
seenPostingIds
```

Before processing a posting, the extension checks this local cache.

A posting is saved as seen only after AWS reports either:

```text
PROCESSING
```

or:

```text
DUPLICATE
```

If processing fails, the posting is not marked as seen and can be retried later.

This provides fast client-side duplicate prevention while DynamoDB remains the authoritative server-side protection.

---

# 24. TMU Local Collector

The browser cannot directly perform all required local/AWS operations.

A small Python service therefore runs locally on:

```text
http://127.0.0.1:8765
```

The collector receives normalized job data from the Chrome extension.

The collector then retrieves the private ingestion key using the configured AWS CLI/SSO profile and forwards the job to:

```text
POST /tmu-jobs
```

The private key itself is never stored in the Chrome extension.

---

# 25. TMU API Authentication

The `/tmu-jobs` endpoint is protected using a private ingestion key.

The key is stored as an AWS Systems Manager Parameter Store `SecureString`.

```text
/jobhunter/tmu-ingest-key
```

The local collector retrieves the value through the authenticated AWS CLI profile.

It sends the key using the request header:

```text
x-jobhunter-key
```

The API Lambda retrieves the expected value from SSM and compares the two.

Invalid keys receive:

```text
401 Unauthorized
```

The actual secret value is never committed to GitHub or Terraform.

---

# 26. Atomic TMU Duplicate Prevention

TMU posting IDs are stable enough to use as the JobHunter identity.

The API creates IDs in the form:

```text
tmu-{postingId}
```

For example:

```text
tmu-114564
```

DynamoDB performs the authoritative duplicate check using a conditional write:

```python
ConditionExpression="attribute_not_exists(job_id)"
```

This is important because duplicate prevention is atomic.

Two requests for the same posting cannot both successfully create a new processing record.

If the record already exists, the API returns:

```text
DUPLICATE
```

instead of sending another copy to SQS.

---

# 27. TMU Company and Title Preservation

TMU provides trusted metadata such as the actual posting title and organization name.

JobHunter preserves this metadata through the entire pipeline.

```text
Chrome Extension
      |
      | title + company
      v
Local Collector
      |
      v
API Lambda
      |
      v
SQS
      |
      v
Worker Lambda
      |
      +--> DynamoDB
      |
      +--> Telegram
```

The worker uses the TMU posting title rather than relying entirely on the AI to infer a title from the job-description text.

Telegram APPLY notifications also include the company name.

---

# 28. TMU Security Boundaries

The TMU integration intentionally follows several security boundaries.

JobHunter does **not**:

- store TMU passwords
- send TMU credentials to AWS
- commit browser cookies
- send cookies to AWS
- store CSRF tokens
- send CSRF tokens to AWS
- persist session-specific action values
- commit Chrome browser profiles
- attempt to bypass Cloudflare
- attempt to bypass CAPTCHA
- use stealth browser automation to evade security controls

The integration relies on a normal Chrome session in which the user has already authenticated.

Only normalized job information is forwarded into JobHunter.

---

# 29. Telegram APPLY Notifications

After matching finishes, the worker stores the result in DynamoDB.

If the recommendation is:

```text
APPLY
```

the worker sends a Telegram notification.

The notification includes information such as:

```text
Job
Company
Recommendation
Technical Match
Experience Match
Reasons
Source
Application link
```

`STRETCH` and `SKIP` results are stored but do not trigger Telegram notifications.

The job analyzer also detects explicit cover-letter requests. For an `APPLY` match that requests one, the worker generates a 220-to-300-word tailored letter using only facts supported by the stored resume and posting. The letter is stored with the result, converted to a PDF in memory, and attached to a Telegram document message whose caption contains the job summary and application link.

Telegram failures are isolated so that a notification failure does not destroy an otherwise successful matching result.

---

# 30. Secure Secret Management

Sensitive values are stored in AWS Systems Manager Parameter Store rather than source code.

Examples include:

```text
/jobhunter/openai-api-key
/jobhunter/telegram-bot-token
/jobhunter/tmu-ingest-key
```

Application code retrieves these values at runtime.

Secrets are not hard-coded in:

- Python
- JavaScript
- Terraform
- Git
- GitHub

The project also uses AWS SSO for authenticated CLI/Terraform access.

---

# 31. IAM

JobHunter uses IAM roles and policies to give Lambda functions access only to the AWS services they require.

Permissions include actions such as:

```text
ssm:GetParameter
sqs:SendMessage
dynamodb:GetItem
dynamodb:PutItem
dynamodb:UpdateItem
s3:GetObject
logs:CreateLogGroup
logs:CreateLogStream
logs:PutLogEvents
```

Different components require different permissions.

For example:

- the API Lambda can submit jobs
- the fetcher can deduplicate and queue jobs
- the worker can retrieve the resume and store results

This follows the principle of least privilege.

---

# 32. CloudWatch Monitoring

CloudWatch provides logs and monitoring for the serverless pipeline.

Lambda logs make it possible to inspect:

- fetcher execution
- worker execution
- AI token usage
- cache hits and misses
- job-processing failures
- Telegram behavior

CloudWatch alarms monitor important failure conditions including:

- Worker Lambda errors
- Fetcher Lambda errors
- messages reaching the dead-letter queue

---

# 33. SNS Infrastructure Alerts

Infrastructure failures are separate from job-match notifications.

CloudWatch alarms can publish to the SNS topic:

```text
jobhunter-alerts
```

This provides operational alerts when the system itself is unhealthy.

Telegram serves a different purpose:

```text
SNS       -> infrastructure problems
Telegram  -> useful APPLY job matches
```

Separating these notification types keeps application results and infrastructure failures distinct.

---

# 34. EventBridge Automation

Amazon EventBridge invokes the Remotive fetcher automatically.

The schedule currently runs:

```text
rate(1 day)
```

This means the Remotive source can discover jobs without manual execution.

Telegram itself is not scheduled.

Notifications occur only when a processed job receives:

```text
APPLY
```

Because the fetcher queues at most five new jobs per scheduled run, a single Remotive run can theoretically generate:

```text
0 to 5 Telegram notifications
```

depending on the number of relevant jobs and their final recommendations.

---

# 35. Terraform

The AWS infrastructure is managed with Terraform.

The AWS provider uses:

```hcl
provider "aws" {
  region  = "us-east-2"
  profile = "terraform-sso"
}
```

Terraform manages resources including:

- Lambda functions
- IAM roles
- IAM policies
- API Gateway
- SQS
- DynamoDB
- S3
- EventBridge
- SNS
- CloudWatch alarms
- SSM access permissions

Lambda deployment packages use source-code hashes so Terraform can detect application changes and update functions when necessary.

---

# 36. Project Structure

The repository contains separate source directories for the major Lambda responsibilities.

```text
jobhunter/
|
+-- lambda_api_package/
|   +-- lambda_function.py
|
+-- lambda_fetcher_package/
|   +-- fetcher_function.py
|
+-- lambda_worker_package/
|   +-- worker_function.py
|   +-- cover_letter.py
|   +-- pdf_document.py
|   +-- matcher.py
|   +-- ai_extractor.py
|   +-- resume_extractor.py
|   +-- skills.py
|   +-- requirements.txt
|
+-- tmu_extension/
|   +-- manifest.json
|   +-- content.js
|   +-- background.js
|
+-- tmu_collector/
|   +-- collector_server.py
|   +-- submit_job.py
|
+-- terraform/
|   +-- main.tf
|   +-- .terraform.lock.hcl
|
+-- README.md
+-- JobHunter-README.md
+-- .gitignore
```

Local virtual environments, browser profiles, deployment artifacts, Terraform state, test payloads, resumes, and secrets are excluded from source control.

---

# 37. Git / Repository Security

The `.gitignore` protects files that should not be committed.

Examples include:

```text
.env
.venv/
venv/
__pycache__/
*.pyc
Terraform state
Terraform ZIP artifacts
test JSON payloads
resume.txt
resume.md
job.txt
job.md
TMU browser profiles
TMU session/cookie/token files
```

The TMU browser profile is particularly important because browser profiles may contain authenticated session information.

It must remain local and must never be committed.

Before publishing changes, the repository is also checked for possible secret-related strings.

References to SSM parameter **names** are safe to commit.

Actual secret **values** are not.

---

# 38. Important Problems Solved During Development

JobHunter was built incrementally, and several real engineering problems were encountered and fixed.

## Windows vs. Lambda Dependencies

Development occurs on Windows while Lambda runs on Linux.

Native Python packages installed for Windows cannot necessarily run in Lambda.

Linux-compatible dependencies were therefore packaged for the Lambda environment.

---

## Remotive HTTP 403

Initial requests to Remotive returned:

```text
403
```

Adding an appropriate User-Agent header fixed the request behavior.

---

## Expensive Resume Re-analysis

Originally the resume could be analyzed for every job.

A resume hash and DynamoDB cache were added so unchanged resumes reuse their existing AI analysis.

---

## Duplicate Automated Jobs

Scheduled fetching could repeatedly process the same posting.

The `jobhunter-seen-jobs` DynamoDB table was added to prevent this for Remotive.

---

## Duplicate TMU Jobs

Local browser caching alone was not sufficient protection.

Atomic DynamoDB conditional writes were added so the server remains authoritative even if two identical requests arrive close together.

---

## TMU Direct Localhost Request

Direct requests from the TMU page to localhost were blocked by the page's Content Security Policy.

A Chrome extension was introduced so the integration could operate without weakening or bypassing the site's security controls.

---

## Cloudflare and Browser Automation

An earlier browser-automation experiment encountered Cloudflare protections.

The project intentionally did not attempt to bypass them.

The final design uses the user's normal authenticated Chrome session.

---

## TMU Page Changes During Processing

The TMU portal dynamically replaces its job-results table during pagination.

A `MutationObserver`, processing lock, pending-page flag, and last-page tracking were added so page changes are not lost while another page is being processed.

---

## Missing Company in Notifications

The TMU extension collected company information, but the value originally did not survive every stage of the AWS pipeline.

The API, SQS message, worker, DynamoDB result, and Telegram notification were updated so company information is preserved end-to-end.

---

# 39. Completed End-to-End Paths

## Manual API

```text
POST /match
    |
    v
API Gateway
    |
    v
API Lambda
    |
    v
SQS
    |
    v
Worker
    |
    v
AI + Matcher
    |
    v
DynamoDB
```

---

## Automated Remotive

```text
EventBridge
    |
    v
Fetcher
    |
    v
Remotive
    |
    v
Filter + Dedupe
    |
    v
SQS
    |
    v
Worker
    |
    v
AI + Matcher
    |
    v
DynamoDB
    |
    v
Telegram if APPLY
```

---

## TMU Co-op

```text
Authenticated TMU Chrome Session
            |
            v
      Chrome Extension
            |
            v
      Local Collector
            |
            v
       POST /tmu-jobs
            |
            v
        API Lambda
            |
            v
   Atomic DynamoDB Dedupe
            |
            v
           SQS
            |
            v
        Worker Lambda
            |
            v
      AI + Matcher
            |
            v
        DynamoDB
            |
            v
    Telegram if APPLY
```

All three paths have been tested successfully.

---

# 40. Current Project Status

| Component | Status |
|---|---|
| Local matcher | Complete |
| AI job extraction | Complete |
| AI resume extraction | Complete |
| Deterministic scoring | Complete |
| Experience scoring | Complete |
| APPLY / STRETCH / SKIP engine | Complete |
| AWS Lambda deployment | Complete |
| Terraform infrastructure | Complete |
| API Gateway | Complete |
| `POST /match` | Complete |
| `GET /results/{job_id}` | Complete |
| SQS worker queue | Complete |
| Dead-letter queue | Complete |
| S3 resume storage | Complete |
| DynamoDB results | Complete |
| Resume-analysis cache | Complete |
| Remotive ingestion | Complete |
| Jobicy ingestion | Complete |
| Remote OK ingestion | Complete |
| The Muse ingestion | Complete |
| Source/application links | Complete |
| Tailored cover letters for APPLY jobs | Complete |
| Remotive duplicate detection | Complete |
| EventBridge automation | Complete |
| CloudWatch monitoring | Complete |
| SNS alerts | Complete |
| Telegram APPLY notifications | Complete |
| TMU Chrome extension | Complete |
| TMU local collector | Complete |
| `POST /tmu-jobs` | Complete |
| TMU SSM authentication | Complete |
| TMU relevance filtering | Complete |
| TMU local seen cache | Complete |
| TMU atomic DynamoDB dedupe | Complete |
| TMU pagination handling | Complete |
| TMU sequential processing | Complete |
| TMU detail retry | Complete |
| TMU company-name pipeline | Complete |

**JobHunter v1 is complete and working end-to-end.**

---

# 41. What This Project Demonstrates

JobHunter demonstrates practical experience with:

### AWS / Cloud

- AWS Lambda
- API Gateway
- Amazon SQS
- Amazon S3
- Amazon DynamoDB
- Amazon EventBridge
- Amazon CloudWatch
- Amazon SNS
- AWS Systems Manager Parameter Store
- AWS IAM

### Infrastructure / DevOps

- Terraform
- Infrastructure as Code
- IAM least privilege
- asynchronous architecture
- event-driven architecture
- serverless architecture
- monitoring and alerting
- secure secret management
- deployment packaging
- AWS CLI
- AWS SSO
- Git
- GitHub

### Software Engineering

- Python
- JavaScript
- Chrome extensions
- HTTP APIs
- JSON
- asynchronous processing
- caching
- idempotency
- conditional database writes
- retry handling
- error isolation
- API integrations

### AI Engineering

- structured AI output
- prompt-driven information extraction
- deterministic post-processing
- AI token-cost reduction through caching
- separation of AI interpretation from application decision logic

---

# 42. Key Engineering Lessons

Building JobHunter reinforced several important cloud-engineering concepts.

### Queues decouple systems

The source of a job does not need to know how the matcher works.

It only needs to submit work to the queue.

### Serverless does not mean there are no servers

AWS manages the underlying compute infrastructure while JobHunter supplies the application code and configuration.

### Idempotency matters

Scheduled systems and browser integrations can encounter the same item more than once.

Duplicate protection must therefore be part of the architecture.

### Caching can reduce AI cost

Resume analysis changes far less frequently than job analysis.

Caching it avoids unnecessary API calls.

### IAM controls what AWS resources code can access

Roles and policies are fundamental to securely connecting AWS services.

### Observability is part of the application

CloudWatch logs and alarms are not an afterthought. They are required to understand whether an asynchronous system is actually working.

### Secrets should not live in source code

Parameter Store allows applications to retrieve secrets at runtime without committing them to Git or embedding them in Terraform.

### AI and deterministic code have different strengths

AI is useful for interpreting messy natural language.

Traditional code is better for predictable calculations and business rules.

JobHunter deliberately uses both.

---

# 43. Future Improvements

JobHunter v1 is complete, but future versions could add:

- additional authorized job sources and credentialed providers such as Adzuna
- improved job-ranking algorithms
- richer notification formatting
- a web dashboard
- application-status tracking
- job shortlisting
- resume variants for different job categories
- cost dashboards
- improved AI usage metrics
- stronger API authentication for additional clients
- automated tests
- CI/CD deployment
- multi-user support

Automatic job application is intentionally outside the current v1 pipeline.

The current system focuses on:

```text
Discover -> Filter -> Analyze -> Score -> Store -> Notify
```

while keeping the final application decision with the user.

---

# 44. Final Architecture Summary

JobHunter began as a local Python keyword matcher.

It evolved into:

```text
Multiple Job Sources
        |
        v
Secure Ingestion
        |
        v
Asynchronous Queue
        |
        v
Serverless Worker
        |
        +--> S3 Resume
        |
        +--> DynamoDB Cache
        |
        +--> OpenAI Analysis
        |
        v
Deterministic Matching Engine
        |
        v
APPLY / STRETCH / SKIP
        |
        +--> DynamoDB Results
        |
        +--> Telegram APPLY Notification
        |
        v
CloudWatch Monitoring
```

The finished project combines AWS serverless infrastructure, Terraform, Python, JavaScript, AI-assisted extraction, deterministic decision logic, asynchronous processing, caching, duplicate prevention, monitoring, secure secret management, browser integration, and automated job discovery into one working system.

**JobHunter v1 is complete and operational.**
