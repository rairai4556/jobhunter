import os
import boto3
import time
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from skills import skills


# --------------------------------------------------
# Evidence for a skill found in the resume
# --------------------------------------------------

class ResumeSkillEvidence(BaseModel):
    skill: str

    evidence_type: str
    demonstrated: bool

    evidence: str
    context: str


# --------------------------------------------------
# Professional role
# --------------------------------------------------

class ProfessionalExperience(BaseModel):
    job_title: str
    company: str

    start_date: str
    end_date: str

    relevant_to_cloud_devops: bool
    relevance_reason: str


# --------------------------------------------------
# Project
# --------------------------------------------------

class ProjectExperience(BaseModel):
    project_name: str

    relevant_to_cloud_devops: bool
    relevance_reason: str

    demonstrated_skills: list[str]


# --------------------------------------------------
# Complete resume analysis
# --------------------------------------------------

class ResumeAnalysis(BaseModel):
    professional_experience: list[ProfessionalExperience]

    projects: list[ProjectExperience]

    skills: list[ResumeSkillEvidence]


# --------------------------------------------------
# OpenAI setup
# --------------------------------------------------

def get_openai_client():

    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:

        ssm = boto3.client(
            "ssm",
            region_name="us-east-2"
        )

        response = ssm.get_parameter(
            Name="/jobhunter/openai-api-key",
            WithDecryption=True
        )

        api_key = response["Parameter"]["Value"]

    return OpenAI(
        api_key=api_key
    )

# --------------------------------------------------
# Analyze resume
# --------------------------------------------------

def analyze_resume(resume_text):

    client = get_openai_client()

    allowed_skills = list(
        skills.keys()
    )

    skill_list = "\n".join(
        f"- {skill}"
        for skill in allowed_skills
    )

    start = time.time()
    response = client.responses.parse(
        model="gpt-5.6-luna",

        input=[
            {
                "role": "system",
                "content": f"""
You analyze resumes for a job matching system.

Your job is NOT to decide whether the candidate should
get a job.

Your job is to extract structured evidence from the resume.

The scoring system will make the final decision.


STANDARDIZED SKILL VOCABULARY

You MUST only use the following skill names:

{skill_list}


--------------------------------------------------
SKILL EVIDENCE
--------------------------------------------------

For every standardized skill you find in the resume,
return:

skill:
The exact standardized skill name.

evidence_type:
One of:

PROFESSIONAL
PROJECT
SKILLS_SECTION
EDUCATION

demonstrated:
true if the resume describes the candidate actually using,
building, configuring, implementing, deploying, testing,
managing, or working with the skill.

false if the skill is merely listed without evidence of use.


evidence:
A short exact excerpt from the resume supporting the result.

Do not paraphrase this field.


context:
A short explanation of where/how the skill was used.


--------------------------------------------------
EVIDENCE TYPE RULES
--------------------------------------------------

PROFESSIONAL:

Use when the skill is demonstrated in employment,
internship, co-op, contract work, or another professional
role.


PROJECT:

Use when the skill is demonstrated in a project.


SKILLS_SECTION:

Use when the technology appears only in a technical skills
or similar skills list and there is no stronger evidence
for it elsewhere.


EDUCATION:

Use when the evidence comes specifically from coursework,
education, labs, or academic study.


--------------------------------------------------
STRONGEST EVIDENCE WINS
--------------------------------------------------

A skill should appear only once.

If a skill has multiple types of evidence, return the
strongest evidence.

Use this priority:

PROFESSIONAL
>
PROJECT
>
EDUCATION
>
SKILLS_SECTION


Example:

If Python appears in the skills section AND was used in
professional experience:

Return:

PROFESSIONAL

Do not also return a SKILLS_SECTION Python entry.


--------------------------------------------------
IMPORTANT DEMONSTRATION RULE
--------------------------------------------------

Do not assume that listing a technology means the candidate
has demonstrated practical experience with it.

A skill may be marked demonstrated = true ONLY when the
resume contains concrete evidence that the candidate
actually used that skill or unmistakable components of it.

Example:

Technical Skills:
Docker, Terraform, AWS

These should normally be:

evidence_type = SKILLS_SECTION
demonstrated = false


But:

"Provisioned AWS infrastructure using Terraform"

means:

Terraform:
evidence_type = PROJECT or PROFESSIONAL
demonstrated = true

AWS:
evidence_type = PROJECT or PROFESSIONAL
demonstrated = true


DIRECT VS INFERRED EVIDENCE:

Do NOT infer one technology merely because another related
technology was used.

Examples:

An EC2 instance does NOT prove Linux.

Nginx does NOT prove Linux.

AWS does NOT prove Lambda.

Docker does NOT prove Kubernetes.

Terraform does NOT prove Ansible.

EC2 does NOT prove ECS.

Kubernetes does NOT prove EKS.


However, a standardized skill may be demonstrated through
clear concrete components of that skill.

Example:

A project describing:

- VPC
- subnets
- route tables
- Internet Gateway
- NAT Gateway
- security groups

is valid evidence for the standardized skill:

networking

because those are direct networking components.


EVIDENCE QUALITY:

The evidence excerpt must genuinely support the skill.

If the only direct evidence for a skill is its name in the
Technical Skills section, classify it as:

evidence_type = SKILLS_SECTION
demonstrated = false

Do not upgrade it to PROJECT merely because related
technologies appear in a project.

When uncertain whether a skill was actually demonstrated,
be conservative and use the weaker classification.


--------------------------------------------------
PROFESSIONAL EXPERIENCE
--------------------------------------------------

Extract each professional role.

For every role return:

job_title
company
start_date
end_date
relevant_to_cloud_devops
relevance_reason


IMPORTANT:

Do NOT classify a software-development or QA internship as
professional DevOps experience merely because the resume
also contains AWS or DevOps skills elsewhere.

Judge each role based only on the responsibilities described
for that specific role.

Cloud/DevOps relevance may include work involving:

- cloud infrastructure
- AWS
- infrastructure automation
- Terraform
- containers
- CI/CD
- deployment automation
- Linux infrastructure
- cloud networking
- SRE
- platform engineering
- systems administration

Do not invent responsibilities.


--------------------------------------------------
PROJECTS
--------------------------------------------------

Extract each project.

For every project return:

project_name
relevant_to_cloud_devops
relevance_reason
demonstrated_skills


demonstrated_skills must only contain exact names from the
standardized vocabulary.

Only include a demonstrated skill when the project
description actually provides evidence that it was used.


--------------------------------------------------
IMPORTANT SAFETY RULES
--------------------------------------------------

Only use information present in the resume.

Do not infer experience that is not supported by the text.

Do not give credit for a skill merely because a related
technology appears.

Examples:

AWS does NOT automatically prove Lambda.

Docker does NOT automatically prove Kubernetes.

Terraform does NOT automatically prove Ansible.

EC2 does NOT automatically prove ECS.

Kubernetes does NOT automatically prove EKS.

Do not invent dates.

Do not invent job responsibilities.

Do not invent projects.

Do not invent skills.
"""
            },

            {
                "role": "user",
                "content": resume_text
            }
        ],

        text_format=ResumeAnalysis
    )

    print(f"Resume analysis took {time.time() - start:.2f} seconds")
    analysis = response.output_parsed
    print("RESUME TOKEN USAGE")
    print("Input tokens:", response.usage.input_tokens)
    print("Output tokens:", response.usage.output_tokens)
    print("Total tokens:", response.usage.total_tokens)
    # --------------------------------------------------
    # Python safety check
    # --------------------------------------------------

    allowed_set = set(
        allowed_skills
    )

    allowed_evidence_types = {
        "PROFESSIONAL",
        "PROJECT",
        "SKILLS_SECTION",
        "EDUCATION"
    }


    analysis.skills = [
        item
        for item in analysis.skills
        if item.skill in allowed_set
        and item.evidence_type in allowed_evidence_types
    ]


    # --------------------------------------------------
    # Safety check project skills
    # --------------------------------------------------

    for project in analysis.projects:

        project.demonstrated_skills = [
            skill
            for skill in project.demonstrated_skills
            if skill in allowed_set
        ]


    return analysis


# --------------------------------------------------
# Run directly for testing
# --------------------------------------------------

if __name__ == "__main__":

    with open(
        "resume.txt",
        "r",
        encoding="utf-8"
    ) as resume_file:

        resume = resume_file.read()


    print()
    print("Analyzing resume with AI...")


    analysis = analyze_resume(
        resume
    )


    # --------------------------------------------------
    # Professional experience
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("PROFESSIONAL EXPERIENCE")
    print("=" * 60)


    for role in analysis.professional_experience:

        print()

        print(
            "Job Title:",
            role.job_title
        )

        print(
            "Company:",
            role.company
        )

        print(
            "Dates:",
            role.start_date,
            "-",
            role.end_date
        )

        print(
            "Cloud/DevOps Relevant:",
            role.relevant_to_cloud_devops
        )

        print(
            "Reason:",
            role.relevance_reason
        )


    # --------------------------------------------------
    # Projects
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("PROJECT EXPERIENCE")
    print("=" * 60)


    for project in analysis.projects:

        print()

        print(
            "Project:",
            project.project_name
        )

        print(
            "Cloud/DevOps Relevant:",
            project.relevant_to_cloud_devops
        )

        print(
            "Reason:",
            project.relevance_reason
        )

        print(
            "Demonstrated Skills:",
            ", ".join(
                project.demonstrated_skills
            )
        )


    # --------------------------------------------------
    # Skill evidence
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("SKILL EVIDENCE")
    print("=" * 60)


    for item in analysis.skills:

        print()

        print(
            item.skill.upper()
        )

        print(
            "Evidence Type:",
            item.evidence_type
        )

        print(
            "Demonstrated:",
            item.demonstrated
        )

        print(
            "Context:",
            item.context
        )

        print(
            "Evidence:",
            item.evidence
        )