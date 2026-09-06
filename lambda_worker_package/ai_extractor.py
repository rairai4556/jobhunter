import os
import time
import boto3
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from skills import skills


# --------------------------------------------------
# Structure for each extracted skill
# --------------------------------------------------

class SkillEvidence(BaseModel):
    skill: str
    strength: str
    reason: str
    evidence: str


# --------------------------------------------------
# Structure returned by AI
# --------------------------------------------------

class JobAnalysis(BaseModel):
    job_title: str
    required_years: int

    required_skills: list[SkillEvidence]
    preferred_skills: list[SkillEvidence]
    mentioned_skills: list[SkillEvidence]

    other_requirements: list[str]


# --------------------------------------------------
# OpenAI setup
# --------------------------------------------------


def get_openai_client():

    # Local computer: try .env first
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")

    # AWS Lambda: retrieve from SSM if .env/environment variable
    # isn't available
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
# Analyze a job posting
# --------------------------------------------------

def analyze_job(job_text):
    client = get_openai_client()
    allowed_skills = list(skills.keys())

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
You analyze job postings for a resume matching system.

You MUST use the following standardized skill vocabulary:

{skill_list}

For every extracted skill, return:

- skill
- strength
- reason
- evidence

The skill MUST exactly match one item from the vocabulary.

Allowed strength values:

HARD_REQUIREMENT
STRONG_REQUIREMENT
FAMILIARITY
EXAMPLE
PREFERRED
MENTIONED


STRENGTH DEFINITIONS

HARD_REQUIREMENT:
Use when the posting uses especially strong language such as:

- must have
- is a must
- mandatory
- required hands-on experience
- candidate must
- demonstrated hands-on experience

Missing this skill should be considered a major gap.


STRONG_REQUIREMENT:
Use when the candidate is clearly expected to have the skill,
but the wording is slightly less absolute.

Examples:

- experience with
- proficiency in
- strong working knowledge
- working experience with
- knowledge of a specific technology that the role directly uses


FAMILIARITY:
Use when the job asks for familiarity, understanding,
general exposure, or knowledge of a technology.

Examples:

- familiarity with AWS services including ...
- understanding of ...
- knowledge of ...

IMPORTANT:
If several technologies appear after wording such as
"familiarity with AWS services including ...",
those individual services should normally be FAMILIARITY,
not HARD_REQUIREMENT or STRONG_REQUIREMENT.


EXAMPLE:
Use when a technology is merely one option in a list of
equivalent tools.

Examples:

- tools such as Ansible, Chef, Puppet, Terraform
- technologies like X, Y, or Z
- one of the following tools

Do NOT treat every item in this kind of list as independently
required.

If one item elsewhere in the posting has stronger wording,
use that stronger classification for that item.


PREFERRED:
Use when the posting says:

- preferred
- a plus
- nice to have
- bonus
- desirable
- similar optional wording


MENTIONED:
Use when the technology merely appears in:

- infrastructure stack
- company environment
- architecture description
- general background
- contextual technology list

and there is no candidate expectation attached to it.


CATEGORY RULES

required_skills:
May contain skills with strength:

HARD_REQUIREMENT
STRONG_REQUIREMENT
FAMILIARITY
EXAMPLE

preferred_skills:
Skills whose strength is:

PREFERRED

mentioned_skills:
Skills whose strength is:

MENTIONED


IMPORTANT CLASSIFICATION RULES

- ONLY return skills from the supplied vocabulary.
- Return skill names exactly as written in the vocabulary.
- Do not create new technical skill names.
- Do not duplicate a skill.
- Do not place a skill in multiple categories.
- If a skill appears multiple times, use the strongest
  supported strength.
- Do not automatically classify a technology as required
  simply because it appears inside a requirements section.
- Interpret the wording surrounding the technology.


required_years:

Return the minimum explicitly stated number of years of
relevant professional experience.

If no number is explicitly stated, return 0.


other_requirements:

Important candidate requirements that are not technical
skills in the supplied vocabulary.

Examples:

- on-call participation
- residency requirements
- remote collaboration
- communication expectations
- part-time availability
- demo application requirement
- incident response responsibility


EVIDENCE RULES

The evidence field must contain a short exact excerpt from
the job posting.

Do not paraphrase evidence.

The reason field should explain why the evidence supports
the selected strength.

Do not invent requirements.
"""
            },

            {
                "role": "user",
                "content": job_text
            }
        ],

        text_format=JobAnalysis
    )

    print("JOB TOKEN USAGE")
    print("Input tokens:", response.usage.input_tokens)
    print("Output tokens:", response.usage.output_tokens)
    print("Total tokens:", response.usage.total_tokens)
    analysis = response.output_parsed


    # --------------------------------------------------
    # Python safety checks
    # --------------------------------------------------

    allowed_set = set(
        allowed_skills
    )

    allowed_strengths = {
        "HARD_REQUIREMENT",
        "STRONG_REQUIREMENT",
        "FAMILIARITY",
        "EXAMPLE",
        "PREFERRED",
        "MENTIONED"
    }
    print(f"Job analysis took {time.time() - start:.2f} seconds")

    # --------------------------------------------------
    # Validate skill + strength
    # --------------------------------------------------

    analysis.required_skills = [
        item
        for item in analysis.required_skills
        if item.skill in allowed_set
        and item.strength in allowed_strengths
    ]

    analysis.preferred_skills = [
        item
        for item in analysis.preferred_skills
        if item.skill in allowed_set
        and item.strength in allowed_strengths
    ]

    analysis.mentioned_skills = [
        item
        for item in analysis.mentioned_skills
        if item.skill in allowed_set
        and item.strength in allowed_strengths
    ]


    # --------------------------------------------------
    # Prevent duplicates across categories
    #
    # required > preferred > mentioned
    # --------------------------------------------------

    required_names = {
        item.skill
        for item in analysis.required_skills
    }

    analysis.preferred_skills = [
        item
        for item in analysis.preferred_skills
        if item.skill not in required_names
    ]

    preferred_names = {
        item.skill
        for item in analysis.preferred_skills
    }

    analysis.mentioned_skills = [
        item
        for item in analysis.mentioned_skills
        if item.skill not in required_names
        and item.skill not in preferred_names
    ]

    return analysis


# --------------------------------------------------
# Run directly for testing
# --------------------------------------------------

if __name__ == "__main__":

    with open(
        "job.txt",
        "r",
        encoding="utf-8"
    ) as job_file:

        job = job_file.read()


    analysis = analyze_job(
        job
    )


    print()
    print("STRUCTURED JOB ANALYSIS")
    print("-----------------------")

    print()
    print("Job Title:")
    print(
        analysis.job_title
    )

    print()
    print("Required Years:")
    print(
        analysis.required_years
    )


    # --------------------------------------------------
    # Required skills
    # --------------------------------------------------

    print()
    print("Required Skills:")

    for item in analysis.required_skills:

        print()

        print(
            f"- {item.skill}"
        )

        print(
            f"  Strength: {item.strength}"
        )

        print(
            f"  Reason: {item.reason}"
        )

        print(
            f"  Evidence: {item.evidence}"
        )


    # --------------------------------------------------
    # Preferred skills
    # --------------------------------------------------

    print()
    print("Preferred Skills:")

    for item in analysis.preferred_skills:

        print()

        print(
            f"- {item.skill}"
        )

        print(
            f"  Strength: {item.strength}"
        )

        print(
            f"  Reason: {item.reason}"
        )

        print(
            f"  Evidence: {item.evidence}"
        )


    # --------------------------------------------------
    # Mentioned skills
    # --------------------------------------------------

    print()
    print("Mentioned Skills:")

    for item in analysis.mentioned_skills:

        print()

        print(
            f"- {item.skill}"
        )

        print(
            f"  Strength: {item.strength}"
        )

        print(
            f"  Reason: {item.reason}"
        )

        print(
            f"  Evidence: {item.evidence}"
        )


    # --------------------------------------------------
    # Other requirements
    # --------------------------------------------------

    print()
    print("Other Requirements:")

    for requirement in analysis.other_requirements:

        print(
            f"- {requirement}"
        )